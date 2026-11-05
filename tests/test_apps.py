# SPDX-License-Identifier: GPL-2.0-or-later
import asyncio
import base64
import importlib.util
import json
import shutil
import subprocess
import urllib.error
from pathlib import Path

import pytest

from hubd import apps
from hubd.apps import AppError, Apps, is_write
from hubd.server import Hubd

needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl is not installed")
spec = importlib.util.spec_from_file_location("create_app", Path(__file__).resolve().parents[1] / "deploy" / "create-app.py")
create_app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(create_app)


@pytest.fixture
def key(tmp_path):
    path = tmp_path / "k.pem"
    if shutil.which("openssl"):
        subprocess.run(["openssl", "genrsa", "-out", str(path), "2048"], capture_output=True, check=True)
    return path


def table(tmp_path, key, persona="reviewer"):
    path = tmp_path / "apps.toml"
    path.write_text(f'["{persona}"]\napp_id = 42\nslug = "glassine-{persona}"\nkey = "{key}"\n')
    return path


def test_what_counts_as_a_write():
    for argv in (["pr", "comment", "1"], ["pr", "review", "1"], ["pr", "merge", "1"], ["issue", "edit", "1"], ["run", "rerun", "1"]):
        assert is_write(argv)
    for argv in (["pr", "view", "1"], ["pr", "diff", "1"], ["run", "list"], ["api", "repos/x"], None, ["pr"]):
        assert not is_write(argv)


@needs_openssl
def test_the_jwt_is_signed_by_the_key_and_short_lived(tmp_path, key):
    token = apps.jwt(42, str(key), 1_000_000)
    head, claims, signature = token.split(".")
    decoded = json.loads(base64.urlsafe_b64decode(claims + "=" * (-len(claims) % 4)))
    assert decoded == {"iat": 999_940, "exp": 1_000_540, "iss": "42"}
    public = tmp_path / "pub.pem"
    subprocess.run(["openssl", "rsa", "-in", str(key), "-pubout", "-out", str(public)], capture_output=True, check=True)
    (tmp_path / "sig").write_bytes(base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)))
    subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(public), "-signature", str(tmp_path / "sig")],
                   input=f"{head}.{claims}".encode(), capture_output=True, check=True)


def test_a_bad_key_is_an_app_error(tmp_path):
    with pytest.raises(AppError):
        apps.jwt(42, str(tmp_path / "missing.pem"), 1)


@needs_openssl
def test_tokens_are_kept_until_near_their_end(tmp_path, key):
    calls = []

    def fetch(method, url, bearer):
        calls.append((method, url))
        if method == "GET":
            return {"id": 7}
        return {"token": f"t{len(calls)}", "expires_at": "2026-11-01T12:00:00Z"}
    expiry = 1793534400  # 2026-11-01T12:00:00Z
    now = [expiry - 3600]
    a = Apps(table(tmp_path, key), fetch=fetch, clock=lambda: now[0])
    assert asyncio.run(a.token("reviewer")) == "t2"
    assert calls == [("GET", "https://api.github.com/orgs/GlassineOS/installation"),
                     ("POST", "https://api.github.com/app/installations/7/access_tokens")]
    assert asyncio.run(a.token("reviewer")) == "t2" and len(calls) == 2
    now[0] = expiry - 100
    assert asyncio.run(a.token("reviewer")) == "t4"


def test_no_app_means_no_token(tmp_path, key):
    a = Apps(table(tmp_path, key))
    assert asyncio.run(a.token("triager")) is None and asyncio.run(a.token(None)) is None
    assert a.posts_as("reviewer") == "glassine-reviewer[bot]" and a.posts_as("triager") is None
    assert asyncio.run(Apps(tmp_path / "none.toml").token("reviewer")) is None


@needs_openssl
def test_an_app_that_fails_doesnt_fall_back(tmp_path, key):
    def fetch(method, url, bearer):
        raise urllib.error.URLError("not installed")
    with pytest.raises(AppError, match="glassine-reviewer"):
        asyncio.run(Apps(table(tmp_path, key), fetch=fetch).token("reviewer"))


class Recording:
    def __init__(self):
        self.tokens = []

    async def run(self, argv, stdin=None, timeout=None, token=None):
        self.tokens.append(token)
        return {"code": 0, "stdout": "", "stderr": ""}


class FakeApps:
    async def token(self, persona):
        if persona == "broken":
            raise AppError("no")
        return f"app-{persona}" if persona == "reviewer" else None


class FakeAgents:
    def scope(self, token):
        return {"s-rev": {"persona": "reviewer"}, "s-eng": {"persona": "engineer"}, "s-bad": {"persona": "broken"}}.get(token)


def _hubd():
    return Hubd(Recording(), None, None, "general", agents=FakeAgents(), apps=FakeApps())


def test_only_a_session_with_an_app_writes_as_it():
    h = _hubd()
    comment = ["pr", "comment", "1", "-R", "GlassineOS/boot"]

    async def go():
        await h.request({"op": "gh", "argv": comment, "agent_token": "s-rev"})
        await h.request({"op": "gh", "argv": ["pr", "view", "1"], "agent_token": "s-rev"})  # a read
        await h.request({"op": "gh", "argv": comment, "agent_token": "s-eng"})  # no App
        await h.request({"op": "gh", "argv": comment, "agent_token": "general"})  # a shell
        await h.request({"op": "gh", "argv": comment})  # the dashboard
        await h.request({"op": "gh", "argv": comment, "agent_token": "made-up"})
    asyncio.run(go())
    assert h.gh.tokens == ["app-reviewer", None, None, None, None, None]


def test_a_broken_app_stops_the_write():
    h = _hubd()
    with pytest.raises(AppError):
        asyncio.run(h.request({"op": "gh", "argv": ["pr", "comment", "1"], "agent_token": "s-bad"}))
    assert h.gh.tokens == []


def test_gh_gets_the_token_and_nothing_inherited(monkeypatch):
    from hubd.ghrun import _env
    monkeypatch.setenv("GH_TOKEN", "from-the-environment")
    assert "GH_TOKEN" not in _env() and _env("mine")["GH_TOKEN"] == "mine"


def test_manifests_have_only_what_the_persona_needs():
    m = create_app.manifest("reviewer", "http://127.0.0.1:1/done")
    assert m["name"] == "glassine-reviewer" and m["public"] is False and m["hook_attributes"]["active"] is False
    assert m["default_permissions"] == {"contents": "read", "pull_requests": "write"}
    assert create_app.PERSONAS["triager"] == {"issues": "write"}
    assert b"organizations/GlassineOS/settings/apps/new?state=abc" in create_app.form("reviewer", "http://x", "abc")


def test_saving_keeps_the_key_private_and_reads_back(tmp_path):
    app = {"id": 42, "slug": "glassine-reviewer", "pem": "-----KEY-----\n"}
    key = create_app.save("reviewer", app, tmp_path)
    assert key.read_text() == app["pem"] and key.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "apps.toml").stat().st_mode & 0o777 == 0o600
    assert "KEY" not in (tmp_path / "apps.toml").read_text()
    create_app.save("triager", {"id": 43, "slug": "glassine-triager", "pem": "x"}, tmp_path)
    a = Apps(tmp_path / "apps.toml")
    assert a.table()["reviewer"]["app_id"] == 42 and a.posts_as("triager") == "glassine-triager[bot]"
    with pytest.raises(SystemExit):
        create_app.save("reviewer", app, tmp_path)
