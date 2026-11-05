#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Creates a persona's GitHub App: deploy/create-app.py reviewer

Opens GitHub's own form with the App already described; you press Create. GitHub hands back
the App's private key to this script, which keeps it in a 0600 file. Nothing is printed but where
it went. Then install the App on the repositories it should work in, with the link at the end.
"""
from __future__ import annotations

import argparse
import html
import http.server
import json
import os
import secrets
import sys
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path

ORG = "GlassineOS"
PERSONAS = {
    "reviewer": {"contents": "read", "pull_requests": "write"},
    "security-auditor": {"contents": "read", "pull_requests": "write"},
    "triager": {"issues": "write"},
    "steward": {"actions": "write", "contents": "write", "issues": "write", "pull_requests": "write", "organization_projects": "write"},
}


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / "glassine-hub"


def manifest(persona: str, redirect: str) -> dict:
    return {"name": f"glassine-{persona}", "url": f"https://github.com/{ORG}", "public": False, "redirect_url": redirect,
            "description": f"The {persona} agent of the GlassineOS hub. Its posts are written by an AI agent.",
            "hook_attributes": {"url": f"https://github.com/{ORG}", "active": False},
            "default_permissions": PERSONAS[persona], "default_events": []}


def form(persona: str, redirect: str, state: str) -> bytes:
    action = f"https://github.com/organizations/{ORG}/settings/apps/new?state={state}"
    value = html.escape(json.dumps(manifest(persona, redirect)), quote=True)
    return (f'<!doctype html><meta charset="utf-8"><title>Create glassine-{persona}</title>'
            f'<form method="post" action="{action}"><input type="hidden" name="manifest" value="{value}">'
            f'<p>Creating the GitHub App glassine-{persona} in {ORG}.</p><button>Continue on GitHub</button></form>').encode()


def convert(code: str) -> dict:
    request = urllib.request.Request(f"https://api.github.com/app-manifests/{urllib.parse.quote(code, safe='')}/conversions",
                                     method="POST", headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as reply:  # noqa: S310 - a fixed https URL
        return json.loads(reply.read())


def save(persona: str, app: dict, config: Path) -> Path:
    """The key in a file of its own, and apps.toml extended. Refuses to replace a persona's App."""
    table = config / "apps.toml"
    existing = tomllib.loads(table.read_text()) if table.exists() else {}
    if persona in existing:
        raise SystemExit(f"{persona} already has an App in {table}")
    keys = config / "apps"
    keys.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = keys / f"{persona}.pem"
    fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(app["pem"])
    with table.open("a") as f:
        f.write(f'\n["{persona}"]\napp_id = {int(app["id"])}\nslug = {json.dumps(app["slug"])}\nkey = {json.dumps(str(key))}\n')
    table.chmod(0o600)
    return key


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Create a persona's GitHub App.")
    p.add_argument("persona", choices=sorted(PERSONAS))
    a = p.parse_args(argv)
    if (config_dir() / "apps" / f"{a.persona}.pem").exists():
        print(f"{a.persona} already has a key in {config_dir() / 'apps'}", file=sys.stderr)
        return 1
    state = secrets.token_urlsafe(16)
    done = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # the query holds the code

        def _answer(self, status, body):
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            redirect = f"http://127.0.0.1:{self.server.server_address[1]}/done"
            if url.path == "/":
                return self._answer(200, form(a.persona, redirect, state))
            query = urllib.parse.parse_qs(url.query)
            if url.path != "/done" or query.get("state") != [state] or "code" not in query:
                return self._answer(400, b"Not what this was waiting for.")
            done["app"] = convert(query["code"][0])
            done["key"] = save(a.persona, done["app"], config_dir())
            self._answer(200, b"Created. You can close this tab and go back to the terminal.")

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    print(f"Open this on this computer, and press the button: http://127.0.0.1:{server.server_address[1]}/")
    while "app" not in done:
        server.handle_request()
    server.server_close()
    print(f"Key: {done['key']}")
    print(f"Now install it on the repositories it should work in: https://github.com/apps/{done['app']['slug']}/installations/new")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
