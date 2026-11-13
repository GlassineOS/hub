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
# Installation tokens last an hour. One this close to the end is renewed: a session's file must outlast a long command.
RENEW_BEFORE = 600
_READ_VERBS = {"list", "view", "diff"}
# What every scoped token reads. GitHub gives each App metadata anyway; contents is what a clone of a private repository needs.
_BASE = {"metadata": "read", "contents": "read"}
# A capability of a state's grant, as the GitHub App permissions it takes. GitHub doesn't separate pushing from merging:
# both are contents:write, so a grant with push can merge, and only a guard outside the token stops it.
CAPABILITIES = {
    "read": {},
    "issues.read": {"issues": "read"},
    "pr.read": {"pull_requests": "read"},
    "runs.read": {"actions": "read"},
    "issues.write": {"issues": "write"},
    "pr.write": {"pull_requests": "write"},
    "pr.review": {"pull_requests": "write"},
    "push": {"contents": "write"},
    "merge": {"contents": "write", "pull_requests": "write"},
    "runs.write": {"actions": "write"},
    "runs.approve": {"actions": "write"},
    "repo.public": {"administration": "write"},
    "repo.delete": {"administration": "write"},
}
_LEVELS = {"read": 1, "write": 2}
# What a session keeps when it may only read: a fork's pull request is an outsider's code running beside the token.
READ_CAPABILITIES = frozenset(c for c, p in CAPABILITIES.items() if all(level == "read" for level in p.values()))


class AppError(Exception):
    """A persona has an App and it can't be used. Nothing falls back to posting as you."""


def is_write(argv) -> bool:
    """Reads stay on the hub's login, which sees what the views need. Writes carry the persona's name."""
    if not isinstance(argv, list) or len(argv) < 2 or argv[0] == "api":
        return False
    return argv[1] not in _READ_VERBS


def permissions_for(github_caps: list[str]) -> dict[str, str]:
    """The permissions a list of capabilities needs, never less than the reads. An unknown name is refused, not ignored."""
    if not isinstance(github_caps, list) or not all(isinstance(c, str) for c in github_caps):
        raise AppError("GitHub capabilities are a list of names")
    unknown = sorted(set(github_caps) - set(CAPABILITIES))
    if unknown:
        raise AppError(f"unknown GitHub capabilities: {', '.join(unknown)}")
    permissions = dict(_BASE)
    for cap in github_caps:
        for name, level in CAPABILITIES[cap].items():
            if _LEVELS[level] > _LEVELS.get(permissions.get(name), 0):  # write beats read
                permissions[name] = level
    return permissions


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


def _fetch(method: str, url: str, bearer: str, body: dict | None = None) -> dict:
    headers = {"Authorization": f"Bearer {bearer}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, method=method, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as reply:  # noqa: S310 - API is a fixed https URL
        return json.loads(reply.read())


class Apps:
    def __init__(self, path: Path, fetch=_fetch, clock=time.time):
        self.path = Path(path)
        self._fetch = fetch
        self._clock = clock
        self._tokens: dict[tuple, tuple[str, float]] = {}

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

    async def token(self, persona, repositories: list[str] | None = None, permissions: dict[str, str] | None = None) -> str | None:
        """A token for this persona's App; None if it has none. With repositories or permissions, GitHub limits it to them.

        Repositories are names within the organization, without the owner. An empty list or table is refused: GitHub
        could read it as no limit at all."""
        if repositories is not None and (not isinstance(repositories, list) or not repositories
                                         or not all(isinstance(r, str) and r and "/" not in r for r in repositories)):
            raise AppError("a token's repositories are one or more names, without the owner")
        if permissions is not None and (not isinstance(permissions, dict) or not permissions
                                        or not all(isinstance(k, str) and v in _LEVELS for k, v in permissions.items())):
            raise AppError("a token's permissions are one or more names, each read or write")
        entry = self.table().get(persona) if isinstance(persona, str) else None
        if not entry:
            return None
        key = (persona, tuple(sorted(set(repositories))) if repositories is not None else None,
               tuple(sorted(permissions.items())) if permissions is not None else None)
        now = self._clock()
        kept = self._tokens.get(key)
        if kept and kept[1] - RENEW_BEFORE > now:
            return kept[0]
        body = {}
        if repositories is not None:
            body["repositories"] = list(key[1])
        if permissions is not None:
            body["permissions"] = dict(key[2])
        try:
            token, expires = await asyncio.to_thread(self._new_token, entry, body or None)
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            raise AppError(f"couldn't get a token for {entry.get('slug', persona)}: {e}") from e
        for old in [k for k, (_t, ends) in self._tokens.items() if ends <= now]:  # scopes of sessions long gone
            del self._tokens[old]
        self._tokens[key] = (token, expires)
        return token

    def _new_token(self, entry: dict, body: dict | None = None) -> tuple[str, float]:
        bearer = jwt(entry["app_id"], entry["key"], self._clock())
        installation = self._fetch("GET", f"{API}/orgs/{ORG}/installation", bearer)
        url = f"{API}/app/installations/{installation['id']}/access_tokens"
        reply = self._fetch("POST", url, bearer, body) if body else self._fetch("POST", url, bearer)
        expires = calendar.timegm(time.strptime(reply["expires_at"], "%Y-%m-%dT%H:%M:%SZ"))
        return reply["token"], expires
