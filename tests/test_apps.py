# SPDX-License-Identifier: GPL-2.0-or-later
import asyncio
import base64
import importlib.util
import json
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
from pathlib import Path

import pytest

from hubd import apps
from hubd.agents import Library
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
    assert m["default_permissions"] == {"contents": "read", "metadata": "read", "pull_requests": "write"}
    assert m["redirect_url"] == "http://127.0.0.1:1/done" and m["default_events"] == []
    assert apps.persona_permissions(LIBRARY, "triager") == {"contents": "read", "issues": "write", "metadata": "read"}
    assert apps.persona_permissions(LIBRARY, "architect") == {"contents": "read", "metadata": "read"}
    assert b"organizations/GlassineOS/settings/apps/new?state=abc" in create_app.form("reviewer", "http://x", "abc")
    assert create_app.PERSONAS == sorted(LIBRARY.families)


def test_saving_keeps_the_key_private_and_reads_back(tmp_path):
    app = {"id": 42, "slug": "glassine-reviewer", "pem": "-----BEGIN KEY-----\n"}
    key = create_app.save("reviewer", app, tmp_path)
    assert key.read_text() == app["pem"] and key.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "apps.toml").stat().st_mode & 0o777 == 0o600
    assert "KEY" not in (tmp_path / "apps.toml").read_text()
    create_app.save("triager", {"id": 43, "slug": "glassine-triager", "pem": "-----BEGIN x"}, tmp_path)
    a = Apps(tmp_path / "apps.toml")
    assert a.table()["reviewer"]["app_id"] == 42 and a.posts_as("triager") == "glassine-triager[bot]"
    with pytest.raises(SystemExit):
        create_app.save("reviewer", app, tmp_path)


# --- an App made from the hub: GitHub's manifest flow ----------------------------------------------------------------------
LIBRARY = Library(Path(__file__).resolve().parents[1] / "agents")
PEM = "-----BEGIN TEST KEY-----\nsecret\n-----END TEST KEY-----\n"
CODE = "code-abcdefgh"


class FakeConversion:
    """GitHub's conversion: the App, with everything it hands back once."""
    def __init__(self, slug="glassine-reviewer", fail=None):
        self.codes, self.slug, self.fail = [], slug, fail

    def __call__(self, code):
        self.codes.append(code)
        if self.fail:
            raise self.fail
        return {"id": 77, "slug": self.slug, "pem": PEM, "client_secret": "cs", "webhook_secret": "ws", "client_id": "Iv1"}


def creation(tmp_path, clock=None, convert=None):
    now = clock or [0.0]
    return apps.Creation(Apps(tmp_path / "apps.toml"), LIBRARY, convert=convert or FakeConversion(), clock=lambda: now[0]), now


def state_of(reply):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(reply["url"]).query)["state"][0]


def test_the_manifest_goes_to_the_org_form_and_comes_back_to_the_hub(tmp_path):
    c, _ = creation(tmp_path)
    reply = c.manifest("reviewer", "https://hub.example:9094")
    assert reply["url"].startswith("https://github.com/organizations/GlassineOS/settings/apps/new?state=")
    m = reply["manifest"]
    assert m["redirect_url"] == "https://hub.example:9094/apps/callback" and m["public"] is False
    assert m["hook_attributes"] == {"url": "https://github.com/GlassineOS", "active": False}
    assert m["default_permissions"] == apps.persona_permissions(LIBRARY, "reviewer")
    assert c.manifest("triager", "http://127.0.0.1:9094")["manifest"]["redirect_url"] == "http://127.0.0.1:9094/apps/callback"
    # GitHub's code alone turns into the key, so it may only come back to a bare origin, and in clear only on this computer
    for origin in ("http://hub.example", "https://hub.example/elsewhere", "https://u@hub.example", "https://hub.example?x=1",
                   "javascript:alert(1)", "ftp://hub.example", None, "https://" + "a" * 300):
        with pytest.raises(AppError):
            c.manifest("reviewer", origin)
    with pytest.raises(AppError, match="isn't a persona"):
        c.manifest("nobody", "https://hub.example")


def test_the_permissions_come_from_the_personas_workflows():
    # A state's github capabilities, its hub tools (and what it may ask for), and its action's result tools, never less than the reads
    reviewer = apps.persona_permissions(LIBRARY, "reviewer")
    assert reviewer["pull_requests"] == "write" and reviewer["metadata"] == "read" and "issues" not in reviewer
    steward = apps.persona_permissions(LIBRARY, "steward")  # asks first for the board and the runs
    assert steward["organization_projects"] == "write" and steward["actions"] == "write"
    with pytest.raises(AppError):
        apps.persona_permissions(LIBRARY, "nobody")


def test_a_states_github_grant_widens_its_personas_app(tmp_path):
    from hubd import machine

    class Lib:
        families = {"tester": {"name": "T", "initials": "T", "family": "build"}}
        actions = {"a": {"id": "a", "personas": ["tester"], "workflow": "w"}}
        workflows = {"w": machine.parse('schema = 1\nname = "w"\ninitial = "look"\n'
                                        '[state.look]\n[state.look.grant]\ntools = ["Bash"]\ngithub = ["runs.read"]\n'
                                        '[[state.look.exit]]\nto = "fix"\ndecided_by = "hand"\n'
                                        '[state.fix]\nfinal = true\n[state.fix.grant]\ntools = ["Bash"]\ngithub = ["push", "issues.label"]\n'
                                        '[state.other]\nfinal = true\npersonas = ["someone-else"]\n[state.other.grant]\ntools = ["Bash"]\ngithub = ["repo.delete"]\n')}
    assert apps.persona_permissions(Lib, "tester") == {"actions": "read", "contents": "write", "issues": "write", "metadata": "read"}


def test_a_full_state_may_write_through_any_hub_tool():
    """A full session's hub tool writes go out as its persona's App (its scope carries the persona), and it may call any tool."""
    from hubd import machine

    class Lib:
        families = {"builder": {"name": "B", "initials": "B", "family": "build"}}
        actions = {"a": {"id": "a", "personas": ["builder"], "workflow": "w"}}
        workflows = {"w": machine.parse('schema = 1\nname = "w"\ninitial = "s"\n[state.s]\nfinal = true\n[state.s.grant]\naccess = "full"\n')}
    wanted = apps.permissions_for(sorted({c for caps in apps.TOOL_CAPABILITIES.values() for c in caps}))
    wanted["organization_projects"] = "write"
    assert apps.persona_permissions(Lib, "builder") == dict(sorted(wanted.items()))
    assert apps.persona_permissions(Lib, "builder")["contents"] == "write"  # merge_pr: GitHub has no merge apart from push


def test_every_write_tool_is_placed():
    """A new tool that writes to GitHub as the persona must say what its App needs; one that stays in the hub says so too."""
    source = (Path(__file__).resolve().parents[1] / "app" / "hub" / "tools.py").read_text()
    writes = set(re.findall(r"@mcp\.tool\(annotations=(?:WRITE|HARD)\)\s+@_says_why\s+async def (\w+)", source))
    assert writes and writes <= set(apps.TOOL_CAPABILITIES) | set(apps.TOOL_PERMISSIONS) | apps.HUB_WRITES
    from hubd.results import APPLY_TOOLS
    assert {t for tools in APPLY_TOOLS.values() for t in tools} <= set(apps.TOOL_CAPABILITIES) | apps.HUB_WRITES


def test_the_code_becomes_a_private_key_and_an_entry_and_nothing_else_leaves(tmp_path):
    convert = FakeConversion()
    c, _ = creation(tmp_path, convert=convert)
    state = state_of(c.manifest("reviewer", "https://hub.example"))
    reply = asyncio.run(c.convert(CODE, state))
    assert reply == {"persona": "reviewer", "app_id": 77, "slug": "glassine-reviewer", "replaced": False,
                     "install_url": "https://github.com/apps/glassine-reviewer/installations/new"}
    assert convert.codes == [CODE]
    entry = Apps(tmp_path / "apps.toml").table()["reviewer"]
    assert entry["app_id"] == 77 and entry["slug"] == "glassine-reviewer"
    key = Path(entry["key"])
    assert key.parent == tmp_path / "apps" and key.read_text() == PEM and key.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "apps.toml").stat().st_mode & 0o777 == 0o600 and (tmp_path / "apps").stat().st_mode & 0o777 == 0o700
    text = (tmp_path / "apps.toml").read_text()
    assert "secret" not in text and "cs" not in text.split() and "ws" not in text.split()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["apps", "apps.toml"]  # no temporary file left beside them
    assert c.list()[[r["persona"] for r in c.list()].index("reviewer")]["app"] is True


def test_a_nonce_works_once_for_its_persona_and_not_for_long(tmp_path):
    convert = FakeConversion()
    c, now = creation(tmp_path, convert=convert)
    used = state_of(c.manifest("triager", "https://hub.example"))
    convert.slug = "glassine-triager"
    asyncio.run(c.convert(CODE, used))
    with pytest.raises(AppError, match="unknown, used or expired"):
        asyncio.run(c.convert(CODE, used))
    late = state_of(c.manifest("reviewer", "https://hub.example"))
    now[0] += apps.NONCE_LIFE + 1
    with pytest.raises(AppError, match="unknown, used or expired"):
        asyncio.run(c.convert(CODE, late))
    other = state_of(c.manifest("reviewer", "https://hub.example"))
    with pytest.raises(AppError, match="no code"):
        asyncio.run(c.convert("bad code!", other))
    with pytest.raises(AppError, match="unknown, used or expired"):  # a refused try used it up too
        asyncio.run(c.convert(CODE, other))
    for state in ("made-up-state", None, "x" * 200, "a\nb"):
        with pytest.raises(AppError):
            asyncio.run(c.convert(CODE, state))
    # The persona is the nonce's, never the request's: there is nothing in convert to name one
    assert convert.codes == [CODE] and set(Apps(tmp_path / "apps.toml").table()) == {"triager"}


def test_a_failed_exchange_burns_the_nonce_and_writes_nothing(tmp_path):
    c, _ = creation(tmp_path, convert=FakeConversion(fail=urllib.error.HTTPError("u", 404, "Not Found", {}, None)))
    state = state_of(c.manifest("reviewer", "https://hub.example"))
    with pytest.raises(AppError, match="works once"):
        asyncio.run(c.convert(CODE, state))
    with pytest.raises(AppError, match="unknown, used or expired"):
        asyncio.run(c.convert(CODE, state))
    assert not (tmp_path / "apps.toml").exists()


def test_an_existing_app_is_replaced_only_when_asked(tmp_path):
    convert = FakeConversion()
    c, _ = creation(tmp_path, convert=convert)
    asyncio.run(c.convert(CODE, state_of(c.manifest("reviewer", "https://hub.example"))))
    with pytest.raises(AppError, match="already has an App"):
        c.manifest("reviewer", "https://hub.example")
    # Asked before the first one existed, then the first one came: the exchange doesn't run, so no second App is made
    c2, _ = creation(tmp_path / "x", convert=convert)
    (tmp_path / "x").mkdir()
    early = state_of(c2.manifest("triager", "https://hub.example"))
    apps.save_app(tmp_path / "x" / "apps.toml", "triager", {"id": 1, "slug": "glassine-triager", "pem": PEM})
    with pytest.raises(AppError, match="in the meantime"):
        asyncio.run(c2.convert(CODE, early))
    assert convert.codes == [CODE]
    convert.slug = "glassine-reviewer-2"
    old_key = Apps(tmp_path / "apps.toml").table()["reviewer"]["key"]
    reply = asyncio.run(c.convert(CODE, state_of(c.manifest("reviewer", "https://hub.example", replace=True))))
    entry = Apps(tmp_path / "apps.toml").table()["reviewer"]
    assert reply["replaced"] is True and entry["slug"] == "glassine-reviewer-2" and entry["key"] == old_key  # same App id in the fake
    with pytest.raises(AppError):
        apps.save_app(tmp_path / "apps.toml", "reviewer", {"id": 2, "slug": "Bad Slug", "pem": PEM}, replace=True)
    with pytest.raises(AppError):
        apps.save_app(tmp_path / "apps.toml", "reviewer", {"id": 2, "slug": "ok", "pem": "not a key"}, replace=True)


def test_only_a_login_reaches_the_app_ops(tmp_path):
    from hubd import auth
    sessions = auth.Sessions()
    login = sessions.create()
    c, _ = creation(tmp_path)
    h = Hubd(Recording(), None, sessions, "agent-secret", agents=FakeAgents(), apps=FakeApps(), app_creation=c)

    async def go():
        for op in ("apps.list", "apps.manifest", "apps.convert"):
            for token in (None, "agent-secret", "s-rev", "made-up"):
                reply = await h.request({"op": op, "token": token, "agent_token": token, "persona": "reviewer", "origin": "https://h.example"})
                assert reply["denied"] and not reply["ok"]
        listed = await h.request({"op": "apps.list", "token": login})
        made = await h.request({"op": "apps.manifest", "token": login, "persona": "reviewer", "origin": "https://h.example"})
        done = await h.request({"op": "apps.convert", "token": login, "code": CODE, "state": state_of(made)})
        return listed, made, done
    listed, made, done = asyncio.run(go())
    assert listed["ok"] and any(r["persona"] == "reviewer" and r["app"] is False for r in listed["apps"])
    assert made["ok"] and done["ok"] and done["slug"] == "glassine-reviewer"


def test_the_tool_server_has_no_app_tools():
    source = (Path(__file__).resolve().parents[1] / "app" / "hub" / "tools.py").read_text()
    assert "apps." not in source and "manifest" not in source


# --- tokens scoped to a session's repositories and capabilities ---------------------------------
class FakeGitHub:
    """GitHub's two calls, with what the token request carried."""
    def __init__(self, expires_at="2026-11-01T12:00:00Z"):
        self.bodies, self.expires_at = [], expires_at

    def __call__(self, method, url, bearer, body=None):
        if method == "GET":
            return {"id": 7}
        self.bodies.append(body)
        return {"token": f"t{len(self.bodies)}", "expires_at": self.expires_at}


def scoped(tmp_path, now):
    github = FakeGitHub()
    a = Apps(table(tmp_path, tmp_path / "unused.pem"), fetch=github, clock=lambda: now[0])
    return a, github


@pytest.fixture
def no_signing(monkeypatch):
    monkeypatch.setattr(apps, "jwt", lambda *_a: "jwt")


EXPIRY = 1793534400  # 2026-11-01T12:00:00Z


def test_the_request_carries_names_and_permissions(tmp_path, no_signing):
    a, github = scoped(tmp_path, [EXPIRY - 3600])
    assert asyncio.run(a.token("reviewer", ["hub", "boot"], {"issues": "write", "metadata": "read"})) == "t1"
    assert github.bodies == [{"repositories": ["boot", "hub"], "permissions": {"issues": "write", "metadata": "read"}}]
    asyncio.run(a.token("reviewer"))
    assert github.bodies[-1] is None  # the persona's token as before: no body


def test_the_cache_keys_on_the_scope(tmp_path, no_signing):
    a, github = scoped(tmp_path, [EXPIRY - 3600])
    first = asyncio.run(a.token("reviewer", ["hub", "boot"], {"issues": "write", "contents": "read"}))
    assert asyncio.run(a.token("reviewer", ["boot", "hub"], {"contents": "read", "issues": "write"})) == first
    assert asyncio.run(a.token("reviewer", ["boot"], {"contents": "read", "issues": "write"})) != first
    assert asyncio.run(a.token("reviewer", ["hub", "boot"], {"contents": "read"})) != first
    assert asyncio.run(a.token("reviewer")) != first
    assert len(github.bodies) == 4


def test_a_scoped_token_is_renewed_ten_minutes_before_its_end(tmp_path, no_signing):
    now = [EXPIRY - 3600]
    a, github = scoped(tmp_path, now)
    scope = (["hub"], {"contents": "read"})
    assert asyncio.run(a.token("reviewer", *scope)) == "t1"
    now[0] = EXPIRY - 601
    assert asyncio.run(a.token("reviewer", *scope)) == "t1"
    now[0] = EXPIRY - 599
    assert asyncio.run(a.token("reviewer", *scope)) == "t2"


@pytest.mark.parametrize("repos, permissions", [
    ([], None), (["GlassineOS/hub"], None), ("hub", None), ([""], None),
    (["hub"], {}), (["hub"], {"issues": "admin"}), (["hub"], ["issues"]),
])
def test_an_empty_or_odd_scope_is_refused_not_widened(tmp_path, no_signing, repos, permissions):
    a, github = scoped(tmp_path, [EXPIRY - 3600])
    with pytest.raises(AppError):
        asyncio.run(a.token("reviewer", repos, permissions))
    assert github.bodies == []


def test_permissions_for_capabilities():
    base = {"metadata": "read", "contents": "read"}
    assert apps.permissions_for([]) == base == apps.permissions_for(["read"])
    assert apps.permissions_for(["issues.write"]) == {**base, "issues": "write"}
    assert apps.permissions_for(["pr.write"]) == apps.permissions_for(["pr.review"]) == {**base, "pull_requests": "write"}
    # GitHub can't tell pushing from merging: both are contents:write
    assert apps.permissions_for(["push"]) == {**base, "contents": "write"}
    assert apps.permissions_for(["merge"]) == {**base, "contents": "write", "pull_requests": "write"}
    assert apps.permissions_for(["runs.write"]) == apps.permissions_for(["runs.approve"]) == {**base, "actions": "write"}
    assert apps.permissions_for(["repo.public"]) == apps.permissions_for(["repo.delete"]) == {**base, "administration": "write"}
    assert apps.permissions_for(["pr.read", "pr.write", "runs.read"]) == {**base, "pull_requests": "write", "actions": "read"}


@pytest.mark.parametrize("caps", [["issues.admin"], ["push", "secrets.write"], "push", [1]])
def test_unknown_capabilities_are_refused(caps):
    with pytest.raises(AppError):
        apps.permissions_for(caps)


def test_a_workflow_with_a_status_line_gives_its_personas_app_comments():
    from hubd import machine

    class Lib:
        families = {"tester": {"name": "T", "initials": "T", "family": "build"}}
        actions = {"a": {"id": "a", "personas": ["tester"], "workflow": "w"}}
        workflows = {"w": machine.parse('schema = 1\nname = "w"\ninitial = "look"\nstatus = true\n'
                                        '[state.look]\n[[state.look.exit]]\nto = "done"\ndecided_by = "hand"\n[state.done]\nfinal = true\n')}
    assert apps.persona_permissions(Lib, "tester") == {"contents": "read", "issues": "write", "metadata": "read", "pull_requests": "write"}
