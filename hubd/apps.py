# SPDX-License-Identifier: GPL-2.0-or-later
"""GitHub Apps: what a persona posts as, instead of the login of whoever runs the hub.

apps.toml names one for each persona that has one (the hub's GitHub Apps page and deploy/create-app.py write it):

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
import os
import re
import secrets
import subprocess
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import machine
from .ghpolicy import ORG
from .machine import GITHUB

log = logging.getLogger("hubd.apps")
API = "https://api.github.com"
# Installation tokens last an hour. One this close to the end is renewed: a session's file must outlast a long command.
RENEW_BEFORE = 600
_READ_VERBS = {"list", "view", "diff"}
# What every scoped token reads. GitHub gives each App metadata anyway; contents is what a clone of a private repository needs.
_BASE = {"metadata": "read", "contents": "read"}
# A capability of a state's grant (the names are machine.GITHUB's), as the GitHub App permissions it takes. GitHub doesn't
# separate pushing from merging: both are contents:write, so a grant with push can merge, and only a guard outside the token
# stops it. Comments and labels on a pull request go through the issues API, which takes either issues or pull_requests write.
_PERMISSIONS = {
    "read": {},
    "issues.read": {"issues": "read"},
    "issues.write": {"issues": "write"},
    "issues.comment": {"issues": "write"},
    "issues.label": {"issues": "write"},
    "issues.delete": {"administration": "write"},
    "pr.read": {"pull_requests": "read"},
    "pr.write": {"pull_requests": "write"},
    "pr.comment": {"pull_requests": "write"},
    "pr.review": {"pull_requests": "write"},
    "pr.label": {"pull_requests": "write"},
    "push": {"contents": "write"},
    "merge": {"contents": "write", "pull_requests": "write"},
    "runs.read": {"actions": "read"},
    "runs.write": {"actions": "write"},
    "runs.trigger": {"actions": "write"},
    "runs.rerun": {"actions": "write"},
    "runs.cancel": {"actions": "write"},
    "runs.approve": {"actions": "write"},
    "repo.public": {"administration": "write"},
    "repo.delete": {"administration": "write"},
}
if set(_PERMISSIONS) != set(GITHUB):  # a name added to one list and not the other mustn't load
    raise ImportError(f"apps: GitHub capabilities differ from machine.GITHUB: {sorted(set(_PERMISSIONS) ^ set(GITHUB))}")
CAPABILITIES = {name: _PERMISSIONS[name] for name in GITHUB}
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

    def installed(self, persona) -> bool | None:
        """True while a token of this persona's App is held, which only an installation gives; otherwise not known without asking GitHub."""
        now = self._clock()
        return True if any(k[0] == persona and ends > now for k, (_t, ends) in self._tokens.items()) else None

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


# --- creating a persona's App: GitHub's manifest flow ------------------------------------------------------------------
NEW_APP_URL = f"https://github.com/organizations/{ORG}/settings/apps/new"
CALLBACK_PATH = "/apps/callback"  # on the hub's own origin; the app's page passes code and state on to hubd
NONCE_LIFE = 900  # seconds from the manifest to GitHub's redirect back: the maintainer reads GitHub's form in between
MAX_PENDING = 16
# GitHub made the App before it sent the maintainer back: one whose code isn't turned into a key here has no use.
_ORPHAN = "If GitHub made the App, delete it on GitHub (Settings, Developer settings, GitHub Apps), then start again from the hub."
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{8,128}")  # a manifest code and a state nonce both look like this
_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
_LOOPBACK = ("127.0.0.1", "localhost", "::1")
STATUS_CAPABILITIES = ("issues.comment", "pr.comment")  # what a workflow's status line takes (FR-025)
# The hub tools that write to GitHub, as the capabilities they take. hubd makes these writes as the session's persona, so its
# App needs them whether the session calls the tool itself or a press applies its result.
TOOL_CAPABILITIES = {
    "create_issue": ("issues.write",), "comment_issue": ("issues.comment",), "close_issue": ("issues.write",),
    "edit_issue": ("issues.write",), "tick_item": ("issues.write",), "edit_comment": ("issues.write",),
    "reopen_issue": ("issues.write",), "label_issue": ("issues.label",), "comment_pr": ("pr.comment",),
    "review_pr": ("pr.review",), "merge_pr": ("merge",), "close_pr": ("pr.write",),
    "rerun": ("runs.rerun",), "cancel_run": ("runs.cancel",), "dispatch_workflow": ("runs.trigger",),
}
# Writes no capability name covers: the organization's project board is an organization permission.
TOOL_PERMISSIONS = {"roadmap_add": {"organization_projects": "write"}, "roadmap_move": {"organization_projects": "write"}}
# Writes that stay in the hub or the workspace: they need nothing of an App.
HUB_WRITES = frozenset({"decision_request", "decision_end", "docs_reindex", "message_started_session", "message_session",
                        "spawn_session", "plan_work", "suggest_session", "submit_drafts", "submit_result", "notes_apply",
                        "request_move", "start_managed", "return_result", "report_up", "withdraw_report", "answer_report", "draft_workflow"})
if bad := sorted(c for caps in TOOL_CAPABILITIES.values() for c in caps if c not in CAPABILITIES):
    raise ImportError(f"apps: tool capabilities that aren't GitHub capabilities: {bad}")


def _leaves_for(library, persona: str) -> list[tuple[machine.Definition, str]]:
    """The states a persona's sessions can be in: every leaf of the workflows of its actions and of what a state starts as it,
    that names no other persona (a state names its personas, or takes its parents'), and every leaf that names this one."""
    own = {a["workflow"] for a in library.actions.values() if persona in a.get("personas", ())}
    own |= {m.workflow for d in library.workflows.values() for s in d.states.values() for m in s.manages if m.persona == persona}
    found = []
    for name, d in library.workflows.items():
        for sid, s in d.states.items():
            if s.initial is not None:  # a session is always in a leaf
                continue
            named = next((d.states[a].personas for a in machine.ancestors(d, sid) if d.states[a].personas), ())
            if persona in named or (name in own and not named):
                found.append((d, sid))
    return found


def persona_permissions(library, persona: str) -> dict[str, str]:
    """What a persona's App needs: the union, over every state its workflows can hold it in, of the state's GitHub capabilities
    and of the hub tools it may write through (its list and what it may ask for; a full session may call any), with the tools
    its actions' results are applied through. Never less than the reads."""
    if persona not in library.families:
        raise AppError(f"{persona!r} isn't a persona of the library")
    caps, tools = set(), set()
    for d, sid in _leaves_for(library, persona):
        grant = machine.effective(d, sid)
        caps.update(grant.github)
        if d.status:  # its moves post a status line as this persona (statusline.py)
            caps.update(STATUS_CAPABILITIES)
        tools.update(set(TOOL_CAPABILITIES) | set(TOOL_PERMISSIONS) if grant.access == "full" else (*grant.hub_tools, *grant.asks_first))
    for action in library.actions.values():
        if persona in action.get("personas", ()):
            tools.update(action.get("result_tools", ()))
    for tool in tools:
        caps.update(TOOL_CAPABILITIES.get(tool, ()))
    permissions = permissions_for(sorted(caps))
    for tool in sorted(tools):
        for name, level in TOOL_PERMISSIONS.get(tool, {}).items():
            if _LEVELS[level] > _LEVELS.get(permissions.get(name), 0):
                permissions[name] = level
    return dict(sorted(permissions.items()))


def manifest(persona: str, redirect: str, permissions: dict[str, str]) -> dict:
    """The App GitHub's form opens with. Private, no webhook, no events: the hub only asks it for tokens."""
    return {"name": f"glassine-{persona}", "url": f"https://github.com/{ORG}", "public": False, "redirect_url": redirect,
            "description": f"The {persona} agent of the GlassineOS hub. Its posts are written by an AI agent.",
            "hook_attributes": {"url": f"https://github.com/{ORG}", "active": False},
            "default_permissions": dict(permissions), "default_events": []}


def callback_url(origin) -> str:
    """The hub's callback on the origin the maintainer's browser reached it at. Only a bare origin: anything else would send
    GitHub's code, which alone turns into the App's private key, somewhere other than the hub."""
    if not isinstance(origin, str) or len(origin) > 255:
        raise AppError("the hub's origin is a short text")
    parts = urllib.parse.urlsplit(origin)
    try:
        port = parts.port
    except ValueError:
        raise AppError("the hub's origin has a bad port") from None
    if (parts.scheme not in ("http", "https") or not parts.hostname or parts.path or parts.query or parts.fragment
            or parts.username is not None or parts.password is not None or (port is not None and not 0 < port < 65536)):
        raise AppError("the hub's origin is scheme, host and port only")
    if parts.scheme == "http" and parts.hostname not in _LOOPBACK:
        raise AppError("the hub's origin is https, or http on this computer only")
    return f"{parts.scheme}://{parts.netloc.lower()}{CALLBACK_PATH}"


def install_url(slug: str) -> str:
    return f"https://github.com/apps/{slug}/installations/new"


def convert_code(code: str) -> dict:
    """GitHub's App for a manifest code: the code alone is the credential, good once, for an hour."""
    request = urllib.request.Request(f"{API}/app-manifests/{urllib.parse.quote(code, safe='')}/conversions", method="POST", data=b"",
                                     headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(request, timeout=30) as reply:  # noqa: S310 - API is a fixed https URL
        return json.loads(reply.read())


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)  # a JSON string is a TOML basic string
    raise AppError(f"apps.toml holds a value this can't write back: {value!r}")


def _write_private(path: Path, text: str) -> None:
    """Whole or not at all, 0600 from its first byte: a file beside it, then renamed over it."""
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def save_app(table: Path, persona: str, app: dict, replace: bool = False) -> Path:
    """The key in a 0600 file of its own and the persona's entry in apps.toml, which is written whole and renamed into place:
    that rename is the moment the persona's App changes. An entry the persona has is kept unless replace says otherwise."""
    if not isinstance(persona, str) or not machine._NAME.fullmatch(persona):
        raise AppError("a persona is a short lower-case name")
    if not (isinstance(app.get("id"), int) and isinstance(app.get("slug"), str) and _SLUG_RE.fullmatch(app["slug"])
            and isinstance(app.get("pem"), str) and app["pem"].startswith("-----BEGIN")):
        raise AppError("GitHub's answer doesn't name an App with a key")
    table = Path(table)
    try:
        existing = tomllib.loads(table.read_text())
    except FileNotFoundError:
        existing = {}
    except (OSError, ValueError) as e:
        raise AppError(f"can't read {table}: {e}") from e
    if persona in existing and not replace:
        raise AppError(f"{persona} already has an App in {table}")
    keys = table.parent / "apps"
    keys.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = keys / f"{persona}-{app['id']}.pem"  # one per App: a replaced one's key stays until its entry is gone
    _write_private(key, app["pem"])
    existing[persona] = {"app_id": app["id"], "slug": app["slug"], "key": str(key)}
    lines = []
    for name, entry in existing.items():
        if not isinstance(entry, dict):
            raise AppError(f"apps.toml: {name} isn't a table")
        lines += ["", f"[{json.dumps(name)}]"] + [f"{k} = {_toml_value(v)}" for k, v in entry.items()]
    _write_private(table, "\n".join(lines).lstrip("\n") + "\n")
    return key


class Creation:
    """One persona's App made through GitHub's manifest flow: the manifest out, a nonce with it, and the code back. The nonce is
    good once, for NONCE_LIFE, for the persona it was made for; only a login reaches either end. It isn't tied to the login
    token: by the time the code comes back GitHub has made the App, and signing in again on the way mustn't strand it. The
    code is turned into the App here, so its key never leaves hubd."""

    def __init__(self, apps: Apps, library, convert=convert_code, clock=time.monotonic):
        self.apps = apps
        self.library = library
        self._convert = convert
        self._clock = clock
        self._pending: dict[str, dict] = {}

    def list(self) -> list[dict]:
        try:
            table, error = self.apps.table(), None
        except AppError as e:
            table, error = {}, str(e)
        rows = []
        for persona in sorted(self.library.families):
            entry = table.get(persona) if isinstance(table.get(persona), dict) else None
            slug = entry.get("slug") if entry and isinstance(entry.get("slug"), str) and _SLUG_RE.fullmatch(entry["slug"]) else None
            rows.append({"persona": persona, "name": self.library.families[persona]["name"], "app": bool(entry), "slug": slug,
                         "install_url": install_url(slug) if slug else None, "installed": self.apps.installed(persona) if entry else None,
                         "permissions": persona_permissions(self.library, persona)})
        return rows if error is None else rows + [{"error": error}]

    def manifest(self, persona, origin, replace=False) -> dict:
        if not isinstance(persona, str) or persona not in self.library.families:
            raise AppError(f"{str(persona)[:64]!r} isn't a persona of the library")
        if replace is not True and persona in self.apps.table():
            raise AppError(f"{persona} already has an App: replacing it is a choice of its own")
        redirect = callback_url(origin)
        now = self._clock()
        for state in [s for s, r in self._pending.items() if r["until"] <= now]:
            del self._pending[state]
        while len(self._pending) >= MAX_PENDING:  # the oldest goes: a page left open long ago
            del self._pending[min(self._pending, key=lambda s: self._pending[s]["until"])]
        state = secrets.token_urlsafe(24)
        self._pending[state] = {"persona": persona, "replace": replace is True, "until": now + NONCE_LIFE}
        return {"persona": persona, "manifest": manifest(persona, redirect, persona_permissions(self.library, persona)),
                "url": f"{NEW_APP_URL}?{urllib.parse.urlencode({'state': state})}", "expires_in": NONCE_LIFE}

    async def convert(self, code, state) -> dict:
        if not isinstance(state, str) or not _TOKEN_RE.fullmatch(state):
            raise AppError("GitHub's answer has no state the hub gave out")
        record = self._pending.pop(state, None)  # used up here, whatever happens next
        if record is None or record["until"] <= self._clock():
            raise AppError(f"This App request is unknown, used or expired. {_ORPHAN}")
        if not isinstance(code, str) or not _TOKEN_RE.fullmatch(code):
            raise AppError("GitHub's answer has no code")
        persona = record["persona"]
        if not record["replace"] and persona in self.apps.table():
            raise AppError(f"{persona} got an App in the meantime, so nothing was exchanged. {_ORPHAN}")
        try:
            app = await asyncio.to_thread(self._convert, code)
        except urllib.error.HTTPError as e:
            raise AppError(f"GitHub refused the code ({e.code}): it works once, within an hour. {_ORPHAN}") from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise AppError(f"couldn't reach GitHub to finish the App: {e}") from None
        if not isinstance(app, dict):
            raise AppError("GitHub's answer doesn't name an App with a key")
        await asyncio.to_thread(save_app, self.apps.path, persona, app, record["replace"])
        log.info("created the GitHub App %s for %s", app["slug"], persona)
        # Only what the page shows: the reply's client and webhook secrets and the key stop here.
        return {"persona": persona, "app_id": app["id"], "slug": app["slug"], "install_url": install_url(app["slug"]),
                "replaced": record["replace"]}
