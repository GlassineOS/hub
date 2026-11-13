#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Creates a persona's GitHub App: deploy/create-app.py reviewer

The same as the hub's GitHub Apps page, for a hub that isn't running: it opens GitHub's own form with the
App already described (hubd/apps.py says what it holds); you press Create. GitHub hands back the App's
private key to this script, which keeps it in a 0600 file. Nothing is printed but where it went. Then
install the App on the repositories it should work in, with the link at the end.
"""
from __future__ import annotations

import argparse
import html
import http.server
import json
import secrets
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hubd import apps as appslib  # noqa: E402
from hubd.agents import Library  # noqa: E402
from hubd.server import config_dir  # noqa: E402

LIBRARY = Library(ROOT / "agents")
PERSONAS = sorted(LIBRARY.families)


def manifest(persona: str, redirect: str) -> dict:
    return appslib.manifest(persona, redirect, appslib.persona_permissions(LIBRARY, persona))


def form(persona: str, redirect: str, state: str) -> bytes:
    action = f"{appslib.NEW_APP_URL}?{urllib.parse.urlencode({'state': state})}"
    value = html.escape(json.dumps(manifest(persona, redirect)), quote=True)
    return (f'<!doctype html><meta charset="utf-8"><title>Create glassine-{persona}</title>'
            f'<form method="post" action="{html.escape(action, quote=True)}"><input type="hidden" name="manifest" value="{value}">'
            f'<p>Creating the GitHub App glassine-{persona} in {appslib.ORG}.</p><button>Continue on GitHub</button></form>').encode()


def save(persona: str, app: dict, config: Path) -> Path:
    """The key in a file of its own, and apps.toml extended. Refuses to replace a persona's App."""
    try:
        return appslib.save_app(config / "apps.toml", persona, app)
    except appslib.AppError as e:
        raise SystemExit(str(e)) from None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Create a persona's GitHub App.")
    p.add_argument("persona", choices=PERSONAS)
    a = p.parse_args(argv)
    if a.persona in appslib.Apps(config_dir() / "apps.toml").table():
        print(f"{a.persona} already has an App in {config_dir() / 'apps.toml'}", file=sys.stderr)
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
            done["app"] = appslib.convert_code(query["code"][0])
            done["key"] = save(a.persona, done["app"], config_dir())
            self._answer(200, b"Created. You can close this tab and go back to the terminal.")

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    print(f"Open this on this computer, and press the button: http://127.0.0.1:{server.server_address[1]}/")
    while "app" not in done:
        server.handle_request()
    server.server_close()
    print(f"Key: {done['key']}")
    print(f"Now install it on the repositories it should work in: {appslib.install_url(done['app']['slug'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
