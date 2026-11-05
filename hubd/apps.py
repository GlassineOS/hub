# SPDX-License-Identifier: GPL-2.0-or-later
"""GitHub Apps: what a persona posts as, instead of the login of whoever runs the hub.

apps.toml names one for each persona that has one (deploy/create-app.py writes it):

    [reviewer]
    app_id = 123
    slug = "glassine-reviewer"
    key = "/path/to/reviewer.pem"

Standard library and the openssl command only, as hubd is.
"""
from __future__ import annotations

import asyncio
import base64
import calendar
import json
import logging
import subprocess
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

from .ghpolicy import ORG

log = logging.getLogger("hubd.apps")
API = "https://api.github.com"
# Installation tokens last an hour; one this close to the end could expire mid-call.
RENEW_BEFORE = 300
_READ_VERBS = {"list", "view", "diff"}


class AppError(Exception):
    """A persona has an App and it can't be used. Nothing falls back to posting as you."""


def is_write(argv) -> bool:
    """Reads stay on the hub's login, which sees what the views need. Writes carry the persona's name."""
    if not isinstance(argv, list) or len(argv) < 2 or argv[0] == "api":
        return False
    return argv[1] not in _READ_VERBS


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def jwt(app_id: int, key: str, now: float, openssl: str = "openssl") -> str:
    # Backdated, as GitHub allows for clock drift; ten minutes is its limit.
    claims = {"iat": int(now) - 60, "exp": int(now) + 540, "iss": str(app_id)}
    head = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()) + "." + _b64(json.dumps(claims).encode())
    try:
        signed = subprocess.run([openssl, "dgst", "-sha256", "-sign", key], input=head.encode(), capture_output=True,
                                check=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError) as e:
        raise AppError(f"couldn't sign with {key}: {e}") from e
    return f"{head}.{_b64(signed)}"


def _fetch(method: str, url: str, bearer: str) -> dict:
    request = urllib.request.Request(url, method=method, headers={
        "Authorization": f"Bearer {bearer}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(request, timeout=30) as reply:  # noqa: S310 - API is a fixed https URL
        return json.loads(reply.read())


class Apps:
    def __init__(self, path: Path, fetch=_fetch, clock=time.time):
        self.path = Path(path)
        self._fetch = fetch
        self._clock = clock
        self._tokens: dict[str, tuple[str, float]] = {}

    def table(self) -> dict:
        """Read each time: adding an App shouldn't need a restart."""
        try:
            return tomllib.loads(self.path.read_text())
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            raise AppError(f"can't read {self.path}: {e}") from e

    def posts_as(self, persona) -> str | None:
        try:
            entry = self.table().get(persona)
        except AppError:
            return None
        return f"{entry['slug']}[bot]" if entry else None

    async def token(self, persona) -> str | None:
        """A token for this persona's App; None if it has none."""
        entry = self.table().get(persona) if isinstance(persona, str) else None
        if not entry:
            return None
        kept = self._tokens.get(persona)
        if kept and kept[1] - RENEW_BEFORE > self._clock():
            return kept[0]
        try:
            token, expires = await asyncio.to_thread(self._new_token, entry)
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            raise AppError(f"couldn't get a token for {entry.get('slug', persona)}: {e}") from e
        self._tokens[persona] = (token, expires)
        return token

    def _new_token(self, entry: dict) -> tuple[str, float]:
        bearer = jwt(entry["app_id"], entry["key"], self._clock())
        installation = self._fetch("GET", f"{API}/orgs/{ORG}/installation", bearer)
        reply = self._fetch("POST", f"{API}/app/installations/{installation['id']}/access_tokens", bearer)
        expires = calendar.timegm(time.strptime(reply["expires_at"], "%Y-%m-%dT%H:%M:%SZ"))
        return reply["token"], expires
