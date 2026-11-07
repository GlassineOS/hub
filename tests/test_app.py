# SPDX-License-Identifier: GPL-2.0-or-later
"""The app against a stand-in for hubd that records what it is asked."""
import asyncio
import json
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import tomllib
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

pytest.importorskip("starlette")
from starlette.testclient import TestClient  # noqa: E402
import uvicorn  # noqa: E402
from mcp_types import CLIENT_CAPABILITIES_META_KEY, CLIENT_INFO_META_KEY, PROTOCOL_VERSION_META_KEY  # noqa: E402

from hub import hubd_client
from hub import main, tools, web  # noqa: E402
from hub.docsearch import STALE_GRACE, DocSearch  # noqa: E402
from hub.github import BadRequest, GitHub  # noqa: E402
from hub.hubd_client import SEES, GhError, Hubd, HubdError  # noqa: E402
from hub.workstore import WorkStore  # noqa: E402

CONFIG = Path(__file__).resolve().parents[1] / "config" / "repos.toml"
HEAD = "a" * 40
ORIGIN = {"origin": "http://testserver"}


def node(name, issues=1, prs=0, state="SUCCESS"):
    return {"name": name, "description": "", "isPrivate": False, "isArchived": False, "url": f"https://x/{name}",
            "pushedAt": None, "issues": {"totalCount": issues}, "pullRequests": {"totalCount": prs},
            "latestRelease": None,
            "defaultBranchRef": {"name": "main", "target": {"oid": "a", "committedDate": None, "messageHeadline": "m",
                                                            "statusCheckRollup": {"state": state},
                                                            "history": {"totalCount": 3}}}}


class FakeHubd(Hubd):
    def __init__(self):
        super().__init__("/nonexistent")
        self.commands = []
        self.logins = []
        self.answers = {}
        self.nodes = [node("hub"), node("boot", prs=2, state="FAILURE"), node("newrepo")]
        self.project_error = None

    async def call(self, **request):
        op = request["op"]
        if op == "auth.check":
            return {"ok": True} if request.get("token") == "good" else {"ok": False}
        if op == "auth.login":
            if request["password"] != "right":
                raise HubdError("login failed")
            return {"ok": True, "token": "good", "user": request["user"]}
        if op == "auth.logout":
            return {"ok": True}
        if op == "auth.check_agent":
            if request.get("token") == "scoped":
                return {"ok": True, "scope": {"session": "s", "tools": ["overview"], "persona": "reviewer"}}
            return {"ok": request.get("token") == "agent", "scope": {"session": None, "tools": None, "persona": None}}
        if op == "ping":
            return {"ok": True, "user": "u", "gh": True, "tmux": False, "socket": "/run/user/1000/glassine-hub/hubd.sock"}
        if op == "shell.list":
            return {"ok": True, "sessions": [{"name": "a"}]}
        if op.startswith("decision."):
            self.commands.append((op, request))
            if op == "decision.list":
                return {"ok": True, "decisions": [], "holding": {"holding": False, "words": "words"}}
            if op in ("decision.check", "decision.request", "decision.end_go"):
                return {"ok": True, "answer": "no", "id": "d-1", "words": "No: words"}
            if op in ("decision.have_device", "decision.done"):
                return {"ok": True, "ended": 2, "holding": {"holding": op == "decision.have_device", "words": "words"}}
            return {"ok": True, "decision": {"id": "d-1"}}
        if op.startswith("notes."):
            self.commands.append((op, request))
            if op == "notes.status":
                return {"ok": True, "here": False, "says": "There are no notes yet."}
            if request["words"] == "broken":
                raise HubdError("the index can't be used")
            return {"ok": True, "here": True, "says": "1 row from notes", "rows": [{"state": "retracted", "where": "a/b:3", "label": "c1", "text": "t"}], "total": 1, "warnings": [], "extra": "not passed on"}
        if op == "device.status":
            self.commands.append((op, request))
            return {"ok": True, "devices": [{"device": "na1", "reported": 1.0, "lines": ["Free when last reported, just now"]}],
                    "only": "Only `mkdir` on the device decides.", "says": "na1: Free when last reported, just now."}
        raise AssertionError(op)

    async def gh(self, *argv, stdin=None, timeout=None, login=None):
        self.commands.append((list(argv), stdin))
        self.logins.append(login)
        for prefix, answer in self.answers.items():
            if " ".join(argv).startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                return answer
        return "[]"

    async def graphql(self, name, **variables):
        self.commands.append(([name], variables))
        if name == "org_overview":
            return {"organization": {"repositories": {"nodes": self.nodes}}}
        if name == "org_projects":
            if self.project_error:
                raise self.project_error
            return {"organization": {"projectsV2": {"nodes": [
                {"id": "P", "number": 1, "title": "GlassineOS roadmap", "closed": False, "url": "u"}]}}}
        if name == "content_id":
            return {"repository": {"issueOrPullRequest": {"id": "NODE"}}}
        if name == "project_add_item":
            return {"addProjectV2ItemById": {"item": {"id": "ITEM"}}}
        if name == "project_items":
            return {"organization": {"projectV2": {
                "id": "P", "title": "t", "url": "u",
                "fields": {"nodes": [{}, {"id": "F", "name": "Status", "options": [{"id": "todo", "name": "Todo"},
                                                                                     {"id": "done", "name": "Done"}]}]},
                "items": {"nodes": [
                    {"id": "I1", "content": {"__typename": "Issue", "number": 1, "title": "a", "url": "x", "state": "OPEN",
                                             "repository": {"name": "hub"}, "labels": {"nodes": [{"name": "epic"}]}},
                     "fieldValues": {"nodes": [{}, {"name": "Done", "optionId": "done", "field": {"name": "Status"}}]}},
                    {"id": "I2", "content": {"__typename": "DraftIssue", "title": "b"}, "fieldValues": {"nodes": []}},
                ]}}}}
        return {}


class FakeDocs:
    async def search(self, q, k=5):
        return {"query": q, "results": []}

    async def status(self):
        return {"state": "current"}

    async def reindex(self):
        return {"started": False}


@pytest.fixture
def hubd():
    return FakeHubd()


@pytest.fixture
def github(hubd):
    return GitHub(hubd, CONFIG)


@pytest.fixture
def client(hubd, github):
    c = TestClient(web.build(hubd, github, FakeDocs(), secure_cookie=False, allowed_hosts={"testserver"}))
    return c


def signed_in(client):
    r = client.post("/api/login", json={"user": "u", "password": "right"}, headers=ORIGIN)
    assert r.status_code == 200
    return client


def test_overview_groups_and_totals(github):
    view = asyncio.run(github.overview())
    groups = {g["key"]: g for g in view["groups"]}
    assert [r["name"] for r in groups["strategy"]["repos"]] == ["hub"]
    assert groups["system"]["totals"] == {"repos": 1, "issues": 1, "prs": 2, "failing": 1}
    # a repository nobody placed is shown, not lost
    assert [r["name"] for r in groups["unplaced"]["repos"]] == ["newrepo"]
    assert view["totals"]["repos"] == 3 and view["totals"]["failing"] == 1


def test_overview_is_cached_until_fresh(github, hubd):
    asyncio.run(github.overview())
    asyncio.run(github.overview())
    assert len(hubd.commands) == 1
    asyncio.run(github.overview(fresh=True))
    assert len(hubd.commands) == 2


def test_issue_body_goes_through_stdin(github, hubd):
    hubd.answers["issue create"] = "https://github.com/GlassineOS/hub/issues/7\n"
    result = asyncio.run(github.create_issue("hub", "t", "--body-file /etc/passwd", ["epic"]))
    assert result["number"] == 7
    argv, stdin = hubd.commands[-1]
    assert stdin == "--body-file /etc/passwd" and "/etc/passwd" not in argv
    assert argv[argv.index("-R") + 1] == "GlassineOS/hub" and "--label" in argv


@pytest.mark.parametrize("repo", ["../evil", "a/b", "", None, "x y"])
def test_bad_repo_names(github, repo):
    with pytest.raises(BadRequest):
        asyncio.run(github.issue(repo, 1))


@pytest.mark.parametrize("number", ["1; rm", "-1", "--web", None, 0])
def test_bad_numbers(github, number):
    with pytest.raises(BadRequest):
        asyncio.run(github.issue("boot", number))


def test_merge_validates_the_method(github, hubd):
    with pytest.raises(BadRequest):
        asyncio.run(github.merge_pr("boot", 1, "--admin"))
    asyncio.run(github.merge_pr("boot", 1, "rebase", delete_branch=True, head=HEAD))
    argv = hubd.commands[-1][0]
    assert argv[:3] == ["pr", "merge", "1"] and "--rebase" in argv and "--delete-branch" in argv


def test_across_repositories_survives_one_failure(github, hubd):
    hubd.answers["issue list -R GlassineOS/boot"] = GhError("issues are disabled")
    hubd.answers["issue list -R GlassineOS/hub"] = json.dumps([{"number": 1, "updatedAt": "2", "comments": [1, 2]}])
    rows = asyncio.run(github.issues())
    assert rows == [{"number": 1, "updatedAt": "2", "comments": 2, "repo": "hub"}]
    with pytest.raises(GhError):  # asked for that repository by name: say so
        asyncio.run(github.issues("boot"))


def test_pr_rollup_words(github, hubd):
    hubd.answers["pr list"] = json.dumps([
        {"number": 1, "updatedAt": "1", "statusCheckRollup": [{"conclusion": "SUCCESS"}, {"conclusion": "FAILURE"}]},
        {"number": 2, "updatedAt": "2", "statusCheckRollup": [{"status": "IN_PROGRESS"}]},
        {"number": 3, "updatedAt": "3", "statusCheckRollup": [{"conclusion": "SUCCESS"}, {"state": "SUCCESS"}]},
        {"number": 4, "updatedAt": "4", "statusCheckRollup": []},
    ])
    rows = {r["number"]: r["checks"] for r in asyncio.run(github.prs("boot"))}
    assert rows == {1: "failing", 2: "pending", 3: "passing", 4: "none"}


def test_add_to_roadmap_resolves_the_issue_itself(github, hubd):
    result = asyncio.run(github.add_to_project("hub", 4))
    assert result == {"item": "ITEM"}
    assert (["content_id"], {"repo": "hub", "number": 4}) in hubd.commands
    assert hubd.commands[-1] == (["project_add_item"], {"projectId": "P", "contentId": "NODE"})


def test_new_issue_on_the_roadmap(github, hubd):
    hubd.answers["issue create"] = "https://github.com/GlassineOS/hub/issues/7\n"
    assert asyncio.run(github.create_issue("hub", "t", roadmap=True))["roadmap"] is True
    hubd.project_error = GhError("no scope")
    result = asyncio.run(github.create_issue("hub", "t", roadmap=True))
    assert "no scope" in result["roadmap_error"]  # the issue still exists, and it says so


def test_board_columns(github):
    board = asyncio.run(github.project())
    assert [(c["name"], [i["id"] for i in c["items"]]) for c in board["columns"]] == [
        ("No status", ["I2"]), ("Todo", []), ("Done", ["I1"])]
    assert board["status_field"] == "F"


def test_board_says_when_the_scope_is_missing(github, hubd):
    hubd.project_error = GhError("requires one of the following scopes: ['read:project']")
    assert asyncio.run(github.project())["needs_scope"] is True


# --- the web layer -------------------------------------------------------------------
def test_api_needs_login(client):
    for path in ("overview", "issues", "prs", "runs", "project", "shells", "docs/status", "host"):
        assert client.get(f"/api/{path}").status_code == 401, path
    assert client.get("/").status_code == 200  # the login page itself


def test_login_needs_same_origin_and_sets_a_strict_cookie(client):
    assert client.post("/api/login", json={"user": "u", "password": "right"},
                       headers={"origin": "http://evil.example"}).status_code == 403
    assert client.post("/api/login", json={"user": "u", "password": "right"}).status_code == 403
    assert client.post("/api/login", json={"user": "u", "password": "no"}, headers=ORIGIN).status_code == 401
    r = client.post("/api/login", json={"user": "u", "password": "right"}, headers=ORIGIN)
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_writes_need_same_origin(client, hubd):
    signed_in(client)
    before = len(hubd.commands)
    for headers in ({}, {"origin": "http://evil.example"}):
        r = client.post("/api/prs/boot/1/merge", json={}, headers=headers)
        assert r.status_code == 403
    assert len(hubd.commands) == before


def test_read_and_write_through_the_api(client, hubd):
    signed_in(client)
    assert client.get("/api/overview").json()["totals"]["repos"] == 3
    r = client.post("/api/issues/boot/3/comment", json={"body": "hello"}, headers=ORIGIN)
    assert r.status_code == 200 and hubd.commands[-1] == (
        ["issue", "comment", "3", "-R", "GlassineOS/boot", "--body-file", "-"], "hello")
    assert client.post("/api/issues/boot/3/comment", json={"body": " "}, headers=ORIGIN).status_code == 400
    assert client.post("/api/issues/boot/3/nonsense", json={}, headers=ORIGIN).status_code == 400
    assert client.post("/api/prs/boot/3/merge", content="[]", headers=ORIGIN).status_code == 400


def test_errors_keep_their_meaning(client, hubd):
    signed_in(client)
    hubd.answers["run list"] = HubdError("not allowed", refused=True)
    assert client.get("/api/runs?repo=boot").status_code == 403
    hubd.answers["run list"] = GhError("gh broke")
    r = client.get("/api/runs?repo=boot")
    assert r.status_code == 502 and r.json()["error"] == "gh broke"


def test_other_hosts_are_refused(hubd, github):
    app = web.build(hubd, github, FakeDocs(), secure_cookie=False, allowed_hosts={"hub.example:9094"})
    rebound = TestClient(app, base_url="http://evil.example:9094")
    assert rebound.get("/").status_code == 421
    assert rebound.post("/api/login", json={"user": "u", "password": "right"},
                        headers={"origin": "http://evil.example:9094"}).status_code == 421
    assert TestClient(app, base_url="http://hub.example:9094").get("/").status_code == 200


def test_login_rejects_a_non_object(client):
    assert client.post("/api/login", content="[]", headers=ORIGIN).status_code == 400


def test_security_headers(client):
    headers = client.get("/").headers
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert "unsafe-eval" not in headers["content-security-policy"]
    assert headers["x-content-type-options"] == "nosniff"


def test_terminal_refuses_other_origins(client):
    signed_in(client)
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect("/api/shells/a/attach", headers={"origin": "http://evil.example"}):
            pass
    assert e.value.code == 4403


# --- the docs index ---------------------------------------------------------------------
class FakeSearcher:
    profile = "static"

    class site:
        manifest = {"commit": "old", "chunks": {"count": 3}}


class Docs(DocSearch):
    def __init__(self, hubd, github, now):
        super().__init__(github, clock=lambda: now[0], loader=lambda: FakeSearcher())
        hubd.answers["api repos/GlassineOS/docs/commits/main"] = '{"sha": "new"}'


def runs(status="completed", conclusion="success", sha="old"):
    return json.dumps([{"status": status, "conclusion": conclusion, "headSha": sha, "createdAt": "1"}])


@pytest.mark.parametrize("answer,state", [
    (runs(), "stale"),
    (runs("in_progress", None, "new"), "building"),
    (runs("completed", "failure", "new"), "failed"),
])
def test_index_states(hubd, github, answer, state):
    hubd.answers["run list"] = answer
    assert asyncio.run(Docs(hubd, github, [0.0]).status())["state"] == state


def test_index_current(hubd, github):
    docs = Docs(hubd, github, [0.0])
    hubd.answers["api repos/GlassineOS/docs/commits/main"] = '{"sha": "old"}'
    assert asyncio.run(docs.status())["state"] == "current"
    assert asyncio.run(docs.reindex())["started"] is False


def dispatches(hubd):
    return [c for c, _ in hubd.commands if c[:2] == ["workflow", "run"]]


def test_reindex_starts_ci_only_when_needed(hubd, github):
    docs = Docs(hubd, github, [0.0])
    hubd.answers["run list"] = runs("in_progress", None, "new")
    assert asyncio.run(docs.reindex())["started"] is False and not dispatches(hubd)
    hubd.answers["run list"] = runs()
    assert asyncio.run(docs.reindex())["started"] is True
    assert dispatches(hubd) == [["workflow", "run", "docs.yml", "-R", "GlassineOS/docs", "--ref", "main"]]


def test_watcher_waits_then_starts_ci_once_per_commit(hubd, github):
    now = [0.0]
    docs = Docs(hubd, github, now)
    hubd.answers["run list"] = runs()
    asyncio.run(docs.tick())
    assert not dispatches(hubd)  # a push just happened, maybe: give its CI time
    now[0] += STALE_GRACE + 1
    asyncio.run(docs.tick())
    assert len(dispatches(hubd)) == 1
    now[0] += STALE_GRACE + 1
    asyncio.run(docs.tick())
    assert len(dispatches(hubd)) == 1  # it didn't help: don't keep trying


# --- the tool server ----------------------------------------------------------------------
def test_tool_list_and_hints(github):
    mcp = tools.build(github, FakeDocs())
    listed = {t.name: t for t in asyncio.run(mcp.list_tools())}
    for name in ("overview", "roadmap", "list_issues", "merge_pr", "dispatch_workflow", "docs_search", "docs_reindex", "work_search", "work_status"):
        assert name in listed
    assert not any("shell" in name for name in listed)
    assert listed["merge_pr"].annotations.destructive_hint is True
    assert listed["review_pr"].annotations.destructive_hint is True
    assert listed["list_prs"].annotations.read_only_hint is True


def test_tool_server_needs_the_token(hubd, github):
    app = main.agent_app(hubd, github, FakeDocs(), 9095)
    client = TestClient(app, base_url="http://127.0.0.1:9095")
    assert client.post("/mcp", json={}).status_code == 401
    assert client.post("/mcp", json={}, headers={"authorization": "Bearer nope"}).status_code == 401


def _tool_call(client, name, token="scoped"):
    return client.post("/mcp", json={"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": name, "arguments": {}}},
                       headers={"authorization": f"Bearer {token}", "accept": "application/json, text/event-stream"})


def test_a_session_token_only_reaches_its_tools(hubd, github):
    with TestClient(main.agent_app(hubd, github, FakeDocs(), 9095), base_url="http://127.0.0.1:9095") as client:
        refused = _tool_call(client, "merge_pr")
        assert refused.status_code == 200 and "doesn't have the tool merge_pr" in refused.json()["error"]["message"]
        assert refused.json()["id"] == 7
        batch = client.post("/mcp", json=[{"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "merge_pr"}}],
                            headers={"authorization": "Bearer scoped"})
        assert "merge_pr" in batch.json()["error"]["message"]
        odd = client.post("/mcp", content=b"{not json", headers={"authorization": "Bearer scoped"})
        assert odd.status_code == 400
        # what it does have gets through, and so does anything for the unscoped token
        assert "error" not in _tool_call(client, "overview").json()
        assert "doesn't have the tool" not in _tool_call(client, "merge_pr", token="agent").text


def test_a_scoped_call_waits_for_the_real_disconnect():
    """The tool server loops on receive() until a disconnect. An answer every time froze the whole app."""
    async def go():
        disconnect = asyncio.Event()

        async def receive():
            await disconnect.wait()
            return {"type": "http.disconnect"}
        replay = main._replaying(b"body", receive)
        assert await replay() == {"type": "http.request", "body": b"body", "more_body": False}
        waiting = asyncio.create_task(replay())
        await asyncio.sleep(0.01)
        assert not waiting.done()
        disconnect.set()
        assert (await waiting)["type"] == "http.disconnect"
    asyncio.run(go())


def _real_tool_server(hubd_call, live):
    """The tool server on a real socket, in a daemon thread: if the bug this tests comes back, it can't be stopped."""
    plain = Hubd("/nonexistent")
    plain.call = hubd_call.__get__(plain)
    live.hubd = plain
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(main.agent_app(plain, live, FakeDocs(), port), host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    until = time.monotonic() + 5
    while not server.started and time.monotonic() < until:
        time.sleep(0.01)
    return server, port


def _post(port, body, timeout, **headers):
    return urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/mcp", data=json.dumps(body).encode(), headers={
        "authorization": "Bearer session-token", "accept": "application/json, text/event-stream", "content-type": "application/json", **headers}),
        timeout=timeout)


def test_an_open_subscription_leaves_the_event_loop_running():
    """Claude Code keeps this stream open. It's the one request the tool server waits on for a disconnect,
    and with a scoped token that froze every page and tool."""
    async def call(self, **request):
        return {"ok": True, "scope": {"session": "s", "tools": ["rate_limit"], "persona": "x", "all_repos": False}}
    live = GitHub(Hubd("/nonexistent"), CONFIG)

    async def rate_limit():
        await asyncio.sleep(0.05)
        return {"remaining": 1}
    live.rate_limit = rate_limit
    server, port = _real_tool_server(call, live)
    version = "2026-07-28"
    envelope = {PROTOCOL_VERSION_META_KEY: version, CLIENT_INFO_META_KEY: {"name": "t", "version": "1"}, CLIENT_CAPABILITIES_META_KEY: {}}
    streams = []
    threading.Thread(target=lambda: streams.append(_post(port, {
        "jsonrpc": "2.0", "id": 1, "method": "subscriptions/listen", "params": {"_meta": envelope, "notifications": {"toolsListChanged": True}}},
        5, **{"mcp-protocol-version": version, "mcp-method": "subscriptions/listen"})), daemon=True).start()
    time.sleep(0.3)
    with _post(port, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "rate_limit", "arguments": {}}}, 3) as reply:
        assert b"remaining" in reply.read()
    assert streams and streams[0].status == 200 and "event-stream" in streams[0].headers["content-type"]
    server.should_exit = True


def test_a_write_from_a_tool_carries_its_callers_token(hubd):
    """Through the real server: hubd takes who is posting from this, so it has to arrive."""
    asked = []

    async def gh_op(**request):
        asked.append(request)
        return {"ok": True, "code": 0, "stdout": "https://x/1\n", "stderr": ""}
    real = Hubd.call

    async def call(self, **request):
        if request.get("op") == "gh":
            return await gh_op(**request)
        if request.get("op") == "auth.check_agent":
            return {"ok": True, "scope": {"session": "s", "tools": ["comment_pr"], "persona": "reviewer"}}
        if request.get("op") == "gh.graphql":
            return {"ok": True, "code": 0, "stdout": "{}", "stderr": ""}
        return await real(self, **request)
    plain = Hubd("/nonexistent")
    plain.call = call.__get__(plain)
    live = GitHub(plain, CONFIG)
    with TestClient(main.agent_app(plain, live, FakeDocs(), 9095), base_url="http://127.0.0.1:9095") as client:
        reply = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "comment_pr", "arguments": {"repo": "boot", "number": 1, "body": "text"}}},
            headers={"authorization": "Bearer session-token", "accept": "application/json, text/event-stream"})
    assert "error" not in reply.json() and not reply.json()["result"].get("isError"), reply.text
    assert [r["agent_token"] for r in asked] == ["session-token"]


@pytest.mark.parametrize("all_repos,seen", [(True, {"boot", "secret"}), (False, {"boot"}), (None, {"boot"}), ("yes", {"boot"})])
@pytest.mark.parametrize("tool", ["list_issues", "list_prs", "list_runs"])
def test_listing_all_repositories_comes_from_the_token_scope(hubd, tool, all_repos, seen):
    """Through the real server: only a session whose scope says so sees private repositories unasked."""
    real = Hubd.call

    async def call(self, **request):
        if request.get("op") == "auth.check_agent":
            return {"ok": True, "scope": {"session": "s", "tools": [tool], "persona": "x", "all_repos": all_repos}}
        return await real(self, **request)
    plain = Hubd("/nonexistent")
    plain.call = call.__get__(plain)
    live = GitHub(plain, CONFIG)

    async def rows(repo=None, *_args):
        names = [repo] if repo else ["boot", "secret"]
        return [{"repo": n, "updatedAt": "2026-01-01T00:00:00Z"} for n in names]

    async def public():
        return {"boot"}
    live.issues = live.prs = live.runs = rows
    live._public_repos = public
    with TestClient(main.agent_app(plain, live, FakeDocs(), 9095), base_url="http://127.0.0.1:9095") as client:
        reply = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": {}}},
                            headers={"authorization": "Bearer session-token", "accept": "application/json, text/event-stream"})
    result = reply.json()["result"]
    assert not result.get("isError"), reply.text
    assert {r["repo"] for r in result["structuredContent"]["result"]} == seen


def test_the_stewards_tools_only_read(hubd, github):
    """Its writes ask you first: on its allowed list, it has no write tool at all."""
    action = tomllib.loads((Path(__file__).parents[1] / "agents" / "actions" / "project-steward.toml").read_text())
    listed = {t.name: t for t in asyncio.run(tools.build(github, FakeDocs()).list_tools())}
    # These write only a suggestion, or a message to a session of its own that can't write. hubd checks that part.
    for name in set(action["hub_tools"]) - {"plan_work", "suggest_session", "message_started_session"}:
        assert listed[name].annotations.read_only_hint is True, name
    for name in action["asks_first"]:
        assert listed[name].annotations.read_only_hint is False and name not in action["hub_tools"], name


def test_suggest_session_hands_covers_to_hubd(github, hubd):
    """005 contract: covers as repo#N go to hubd, which checks them; leaving them out sends none, as before."""
    calls = []

    async def call(**request):
        calls.append(request)
        return {"ok": True, "id": "w1"}
    hubd.call = call
    asyncio.run(github.suggest_session("issue-implement", "epd", 9, "why", covers=["kernel#204"]))
    asyncio.run(github.suggest_session("issue-implement", "epd", 9, "why", also_numbers=[11]))
    assert calls[0]["op"] == "work.suggest" and calls[0]["covers"] == ["kernel#204"]
    assert "covers" not in calls[1] and calls[1]["also_numbers"] == [11]


def test_review_pr_checks_its_event_and_uses_stdin(github, hubd):
    asyncio.run(github.review_pr("boot", 1, "approve", ""))
    argv, stdin = hubd.commands[-1]
    assert argv[:2] == ["pr", "review"] and "--approve" in argv and stdin == ""
    asyncio.run(github.review_pr("boot", 1, "request-changes", "fix this"))
    assert hubd.commands[-1][1] == "fix this" and "fix this" not in hubd.commands[-1][0]
    with pytest.raises(BadRequest):
        asyncio.run(github.review_pr("boot", 1, "dismiss", "x"))
    with pytest.raises(BadRequest):
        asyncio.run(github.review_pr("boot", 1, "comment", "  "))


def test_tool_errors_say_why(hubd, github):
    mcp = tools.build(github, FakeDocs())
    from mcp.server.mcpserver.exceptions import ToolError
    with pytest.raises(ToolError, match="not a repository name"):
        asyncio.run(mcp._tool_manager.call_tool("list_issues", {"repo": "../evil"}, None))


@pytest.mark.parametrize("name", ["boot", "GlassineOS/boot"])
def test_tools_take_a_repository_with_or_without_the_organization(hubd, github, name):
    mcp = tools.build(github, FakeDocs())
    asyncio.run(mcp._tool_manager.call_tool("list_issues", {"repo": name}, None))
    assert "GlassineOS/boot" in hubd.commands[-1][0]
    assert "GlassineOS/GlassineOS/boot" not in " ".join(hubd.commands[-1][0])


@pytest.mark.parametrize("name", ["Other/boot", "GlassineOS/../boot", "GlassineOS/GlassineOS/boot", "glassineos/boot"])
def test_only_the_organizations_own_prefix_comes_off(hubd, github, name):
    from mcp.server.mcpserver.exceptions import ToolError
    mcp = tools.build(github, FakeDocs())
    with pytest.raises(ToolError, match="not a repository name"):
        asyncio.run(mcp._tool_manager.call_tool("list_issues", {"repo": name}, None))


def test_resume_goes_through_with_the_login(client, hubd):
    signed_in(client)
    calls = []
    real = hubd.call

    async def call(**request):
        if request["op"] in ("agent.stopped", "agent.resume"):
            calls.append(request)
            return {"ok": True, "sessions": [{"name": "x"}], "name": "x"}
        return await real(**request)
    hubd.call = call
    assert client.get("/api/agents/stopped").json() == [{"name": "x"}]
    assert client.post("/api/agents/resume", json={"name": "x"}, headers=ORIGIN).json()["name"] == "x"
    assert calls[-1]["op"] == "agent.resume" and calls[-1]["name"] == "x" and calls[-1]["token"] == "good"


def test_listing_tools_take_the_agents_view(hubd, github, monkeypatch):
    """Without a repository, a tool lists what an agent may see, not what the dashboard shows you."""
    seen = []

    async def agent_issues(*args):
        seen.append("issues")
        return []

    async def agent_prs(*args):
        seen.append("prs")
        return []
    monkeypatch.setattr(github, "agent_issues", agent_issues)
    monkeypatch.setattr(github, "agent_prs", agent_prs)
    mcp = tools.build(github, FakeDocs())
    asyncio.run(mcp._tool_manager.call_tool("list_issues", {}, None))
    asyncio.run(mcp._tool_manager.call_tool("list_prs", {}, None))
    assert seen == ["issues", "prs"]


def test_lan_without_tls_is_refused(monkeypatch, capsys):
    monkeypatch.setenv("HUB_BIND", "192.168.1.5")
    monkeypatch.delenv("HUB_TLS_CERT", raising=False)
    monkeypatch.delenv("HUB_TLS_KEY", raising=False)
    assert asyncio.run(main.run()) == 2
    assert "without TLS" in capsys.readouterr().err


def test_rollup_of_sub_issues():
    from hub.github import _rollup_subs, _run_mark
    rows = _rollup_subs([{"state": "CLOSED", "repository": {"name": "boot"}}, {"state": "OPEN", "repository": {"name": "boot"}},
                         {"state": "OPEN", "repository": {"name": "docs"}}])
    assert rows == [{"repo": "boot", "done": 1, "total": 2}, {"repo": "docs", "done": 0, "total": 1}]
    assert _run_mark({"status": "in_progress"}) == "run"
    assert _run_mark({"status": "completed", "conclusion": "success"}) == "pass"
    assert _run_mark({"status": "completed", "conclusion": "failure"}) == "fail"
    assert _run_mark({"status": "completed", "conclusion": "cancelled"}) == "fail"


# --- review threads ------------------------------------------------------------------------------
THREADS = {"repository": {"pullRequest": {"reviewThreads": {"nodes": [{
    "id": "PRRT_1", "isResolved": False, "isOutdated": True, "path": "a.c", "line": 88, "diffSide": "RIGHT",
    "comments": {"nodes": [{"author": None, "body": "Fix", "createdAt": "2026-01-01T00:00:00Z", "url": "u", "diffHunk": "@@"}]}}]}}}}


def thread_hubd():
    h = FakeHubd()
    seen = []

    async def graphql(name, **variables):
        seen.append((name, variables))
        return THREADS if name == "pr_threads" else {"addPullRequestReviewThreadReply": {"comment": {"url": "posted"}}}
    h.graphql = graphql
    return h, seen


def test_threads_are_read_from_github_and_shaped():
    h, seen = thread_hubd()
    rows = asyncio.run(GitHub(h, CONFIG).pr_threads("hub", 5))
    assert seen == [("pr_threads", {"repo": "hub", "number": 5})]
    assert rows == [{"id": "PRRT_1", "resolved": False, "outdated": True, "path": "a.c", "line": 88, "side": "RIGHT",
                     "comments": [{"author": None, "body": "Fix", "createdAt": "2026-01-01T00:00:00Z", "url": "u", "hunk": "@@"}]}]


def test_a_pull_request_that_isnt_there_has_no_threads():
    h, _ = thread_hubd()

    async def nothing(name, **variables):
        return {"repository": {"pullRequest": None}}
    h.graphql = nothing
    assert asyncio.run(GitHub(h, CONFIG).pr_threads("hub", 5)) == []


def test_resolving_and_replying_go_through_named_documents():
    h, seen = thread_hubd()
    g = GitHub(h, CONFIG)
    assert asyncio.run(g.resolve_thread("hub", 5, "PRRT_1"))["resolved"] is True
    asyncio.run(g.resolve_thread("hub", 5, "PRRT_1", False))
    assert asyncio.run(g.reply_thread("hub", 5, "PRRT_1", "done"))["url"] == "posted"
    assert [s[0] for s in seen] == ["thread_resolve", "thread_unresolve", "thread_reply"]
    assert seen[2][1] == {"threadId": "PRRT_1", "body": "done"}


@pytest.mark.parametrize("thread,body", [("a b", "x"), (None, "x"), ("T" * 201, "x"), ("T", ""), ("T", "   "), ("T", None)])
def test_a_bad_thread_or_empty_reply_is_refused(thread, body):
    h, seen = thread_hubd()
    with pytest.raises(BadRequest):
        asyncio.run(GitHub(h, CONFIG).reply_thread("hub", 5, thread, body))
    assert seen == []


def test_agents_can_read_threads_and_not_change_them(hubd, github):
    listed = {t.name: t for t in asyncio.run(tools.build(github, FakeDocs()).list_tools())}
    assert listed["get_pr_threads"].annotations.read_only_hint is True
    assert not {"resolve_thread", "reply_thread"} & set(listed)


# --- what a session sees -----------------------------------------------------------------------
def listed_for(scope):
    plain = Hubd("/nonexistent")

    async def call(**request):
        return {"ok": True, "scope": scope}
    plain.call = call
    headers = {"authorization": "Bearer session-token", "accept": "application/json, text/event-stream"}
    with TestClient(main.agent_app(plain, GitHub(plain, CONFIG), FakeDocs(), 9095), base_url="http://127.0.0.1:9095") as client:
        reply = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=headers)
    return {t["name"]: t for t in reply.json()["result"]["tools"]}


def test_a_session_sees_only_the_tools_it_can_call():
    assert set(listed_for({"session": "s", "tools": ["get_pr", "docs_search"], "persona": "x"})) == {"get_pr", "docs_search"}
    assert listed_for({"session": "s", "tools": [], "persona": "x"}) == {}


def test_a_general_token_sees_every_tool():
    assert {"merge_pr", "overview"} <= set(listed_for({"session": None, "tools": None, "persona": None}))
    assert {"merge_pr", "overview"} <= set(listed_for(None))


@pytest.mark.parametrize("step", ["plan", "run"])
def test_notes_and_pins_go_through_to_hubd(client, hubd, step):
    signed_in(client)
    calls = []
    real = hubd.call

    async def call(**request):
        if request["op"] == f"agent.{step}":
            calls.append(request)
            return {"ok": True}
        return await real(**request)
    hubd.call = call
    pins = [{"kind": "ref", "label": "hub#1"}]
    client.post(f"/api/agents/{step}", json={"action": "pr-review", "repo": "hub", "number": 1, "notes": "n", "pins": pins}, headers=ORIGIN)
    assert calls[-1]["notes"] == "n" and calls[-1]["pins"] == pins


def test_spawn_session_goes_to_hubd_under_the_sessions_token(github, hubd):
    async def go():
        hubd_client.CALLER.set("session-token")
        return await github.spawn_session("pr-review", "boot", 5)
    original = hubd.call

    async def call(**request):
        assert request == {"op": "started.spawn", "agent_token": "session-token", "action": "pr-review", "repo": "boot", "number": 5}
        return {"name": "pr-review-boot-5"}
    hubd.call = call
    assert asyncio.run(go()) == {"started": "pr-review-boot-5"}
    hubd.call = original


def test_typed_words_go_only_to_say_and_a_button_says_its_own():
    seen = []

    class Hubd(FakeHubd):
        async def call(self, **request):
            if not request["op"].startswith("agent."):
                return await super().call(**request)
            seen.append(request)
            return {"ok": True, "sent": True}
    client = TestClient(web.build(Hubd(), None, FakeDocs(), secure_cookie=False, allowed_hosts={"testserver"}))
    signed_in(client)
    body = {"name": "steward", "button": "status", "kind": "run", "selection": "hub#1", "text": "my own words"}
    assert client.post("/api/agents/press", json=body, headers=ORIGIN).status_code == 200
    press = next(r for r in seen if r["op"] == "agent.press")
    assert (press["name"], press["button"], press["kind"], press["selection"]) == ("steward", "status", "run", "hub#1")
    assert "text" not in press
    # Typed words have their own route (004 FR-008), and carry only the name, the words and where.
    assert client.post("/api/agents/say", json={**body, "where": "Work"}, headers=ORIGIN).status_code == 200
    say = next(r for r in seen if r["op"] == "agent.say")
    assert (say["name"], say["text"], say["where"]) == ("steward", "my own words", "Work")
    assert not {"button", "kind", "selection"} & set(say)
    assert client.post("/api/agents/send", json=body, headers=ORIGIN).status_code == 400


def test_the_page_says_where_it_shows_a_session():
    seen = []

    class Hubd(FakeHubd):
        async def call(self, **request):
            if not request["op"].startswith("agent."):
                return await super().call(**request)
            seen.append(request)
            return {"ok": True, "view": {"mode": request["mode"], "where": request["where"], "ref": request.get("ref")}}
    client = TestClient(web.build(Hubd(), None, FakeDocs(), secure_cookie=False, allowed_hosts={"testserver"}))
    body = {"name": "s1", "mode": "embedded", "where": "Work", "ref": "boot#5", "text": "not this"}
    assert client.post("/api/agents/view", json=body, headers=ORIGIN).status_code == 401
    signed_in(client)
    assert client.post("/api/agents/view", json=body).status_code == 403  # same origin only
    reply = client.post("/api/agents/view", json=body, headers=ORIGIN)
    assert reply.status_code == 200 and reply.json()["view"]["mode"] == "embedded"
    view = next(r for r in seen if r["op"] == "agent.view")
    assert (view["name"], view["mode"], view["where"], view["ref"]) == ("s1", "embedded", "Work", "boot#5") and "text" not in view


def test_a_graphql_call_says_which_session_made_it():
    seen = []

    class Client(hubd_client.Hubd):
        def __init__(self):
            pass

        async def call(self, **request):
            seen.append(request)
            return {"code": 0, "stdout": '{"data": {}}', "stderr": ""}

    async def go():
        hubd_client.CALLER.set("the-session")
        await Client().graphql("project_move", itemId="x")
    asyncio.run(go())
    assert seen[0]["agent_token"] == "the-session"


def test_what_sessions_ask_goes_to_hubd_with_a_login():
    seen = []

    class Hubd(FakeHubd):
        async def call(self, **request):
            if not request["op"].startswith("ask."):
                return await super().call(**request)
            seen.append(request)
            return {"ok": True, "ask": {"id": 3}} if request["op"] == "ask.answer" else {"ok": True, "open": [], "answered": []}
    client = TestClient(web.build(Hubd(), None, FakeDocs(), secure_cookie=False, allowed_hosts={"testserver"}))
    assert client.get("/api/asks").status_code == 401
    assert client.post("/api/asks/a3/answer", json={"verdict": "allow"}, headers=ORIGIN).status_code == 401
    signed_in(client)
    assert client.get("/api/asks").json() == {"open": [], "answered": []}
    body = {"verdict": "deny", "reason": "later", "answers": None, "extra": "x"}
    assert client.post("/api/asks/a3/answer", json=body, headers=ORIGIN).json() == {"id": 3}
    answer = seen[-1]
    assert (answer["op"], answer["id"], answer["verdict"], answer["reason"], answer["token"]) == ("ask.answer", "a3", "deny", "later", "good")
    assert "extra" not in answer


ran = []


def tool_server_replies(granted, body=None):
    """granted: how many calls have your yes."""
    plain = Hubd("/nonexistent")
    asked = []
    left = [int(granted)]

    async def call(**request):
        if request["op"] == "ask.grant_use":
            asked.append(request)
            if left[0] > 0:
                left[0] -= 1
                return {"ok": True}
            return {"ok": False, "refused": True, "error": "you weren't allowed"}
        if request["op"] != "auth.check_agent":
            ran.append(request)
            return {"ok": True, "code": 0, "stdout": "https://github.com/GlassineOS/boot/issues/1#issuecomment-1\n", "stderr": ""}
        return {"ok": True, "scope": {"session": "steward", "tools": ["comment_issue"], "persona": "steward", "asks_first": ["comment_issue"]}}
    plain.call = call
    headers = {"authorization": "Bearer session-token", "accept": "application/json, text/event-stream"}
    arguments = {"repo": "boot", "number": 1, "body": "x"}
    with TestClient(main.agent_app(plain, GitHub(plain, CONFIG), FakeDocs(), 9095), base_url="http://127.0.0.1:9095") as client:
        reply = client.post("/mcp", json=body or {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "comment_issue", "arguments": arguments}}, headers=headers)
    return reply, asked, arguments, ran


def test_the_tool_server_refuses_a_write_without_your_yes():
    ran.clear()
    reply, asked, arguments, done = tool_server_replies(False)
    assert "you weren't allowed" in reply.json()["error"]["message"]
    assert asked == [{"op": "ask.grant_use", "agent_token": "session-token", "tool": "comment_issue", "arguments": arguments}]
    assert done == []


def test_the_tool_server_runs_a_write_you_allowed_with_its_arguments():
    ran.clear()
    reply, asked, _arguments, done = tool_server_replies(1)
    assert "error" not in reply.json() and len(asked) == 1
    assert [r for r in done if r["op"] == "gh" and "comment" in r["argv"] and "boot" in " ".join(r["argv"])], done


def test_a_batch_cant_stretch_one_yes_to_two_calls():
    ran.clear()
    arguments = {"repo": "boot", "number": 1, "body": "x"}
    one = lambda i: {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": "comment_issue", "arguments": arguments}}
    reply, asked, _arguments, done = tool_server_replies(1, body=[one(1), one(2)])
    assert "you weren't allowed" in reply.json()["error"]["message"] and len(asked) == 2
    assert done == []


def test_merge_pr_passes_on_the_head_it_names(github, hubd):
    asyncio.run(github.merge_pr("boot", 1, "squash", False, HEAD))
    assert "--match-head-commit" in hubd.commands[-1][0] and HEAD in hubd.commands[-1][0]
    assert hubd.logins[-1] is None, "a tool call has no login"


@pytest.mark.parametrize("head", [None, "", "abc", "--admin", HEAD.upper(), HEAD + "0", 7])
def test_merge_pr_wont_go_without_a_full_head(github, hubd, head):
    with pytest.raises(BadRequest):
        asyncio.run(github.merge_pr("boot", 1, "squash", False, head))
    assert not hubd.commands


def test_a_merge_from_the_page_carries_the_head_and_the_login(client, hubd):
    signed_in(client)
    assert client.post("/api/prs/boot/1/merge", json={"method": "squash", "head": HEAD}, headers=ORIGIN).status_code == 200
    argv = hubd.commands[-1][0]
    assert argv[argv.index("--match-head-commit") + 1] == HEAD and hubd.logins[-1] == "good"


def test_a_page_from_before_the_change_is_refused_a_merge(client, hubd):
    signed_in(client)
    r = client.post("/api/prs/boot/1/merge", json={"method": "squash"}, headers=ORIGIN)
    assert r.status_code == 400 and "reload the page" in r.json()["error"]
    assert not hubd.commands


@pytest.mark.parametrize("pr, threads, words", [
    ({"checks": "passing", "reviewDecision": "APPROVED"}, 0, []),
    ({"checks": "pending", "reviewDecision": "APPROVED"}, 0, ["checks are still running"]),
    ({"checks": "failing", "reviewDecision": "APPROVED"}, 0, ["checks have failed"]),
    ({"checks": "failing", "reviewDecision": None}, 1, ["checks have failed", "not approved yet", "1 review thread open"]),
    ({"checks": "none", "reviewDecision": "APPROVED"}, 0, []),
    ({"checks": "passing", "reviewDecision": "REVIEW_REQUIRED"}, 0, ["not approved yet"]),
    ({"checks": "passing", "reviewDecision": ""}, None, ["not approved yet"]),
    ({"checks": "passing", "reviewDecision": "CHANGES_REQUESTED"}, 0, ["changes were requested"]),
    ({"checks": "passing", "reviewDecision": "APPROVED"}, 1, ["1 review thread open"]),
    ({"checks": "pending", "reviewDecision": None}, 3, ["checks are still running", "not approved yet", "3 review threads open"]),
])
def test_merge_blockers_name_each_reason(pr, threads, words):
    from hub.github import merge_blockers
    assert [b["why"] for b in merge_blockers(pr, threads)] == words


def _open_pr(**extra):
    return json.dumps({"number": 4, "title": "t", "state": "OPEN", "headRefOid": HEAD, "baseRefName": "main", "statusCheckRollup": [],
                       "reviewDecision": "APPROVED", "files": [], "labels": [], **extra})


def test_an_open_pr_says_how_far_behind_it_is_from_compare(github, hubd):
    hubd.answers["pr view 4"] = _open_pr()
    hubd.answers["api repos/GlassineOS/boot/compare/main..."] = json.dumps({"behind_by": 3, "ahead_by": 1})
    row = asyncio.run(github.pr_page("boot", 4))
    assert row["behind_by"] == 3 and row["open_threads"] == 0
    assert ["api", f"repos/GlassineOS/boot/compare/main...{HEAD}"] in [c[0] for c in hubd.commands]
    assert [b["why"] for b in row["merge_blockers"]] == [], "no checks, approved, no threads: nothing stops the merge"


def test_a_failed_compare_leaves_behind_unknown(github, hubd):
    hubd.answers["pr view 4"] = _open_pr()
    hubd.answers["api repos/GlassineOS/boot/compare"] = GhError("Not Found")
    assert asyncio.run(github.pr_page("boot", 4))["behind_by"] is None


def test_a_closed_pr_asks_nothing_more(github, hubd):
    hubd.answers["pr view 4"] = _open_pr(state="MERGED", mergedBy={"login": "moritz"})
    row = asyncio.run(github.pr_page("boot", 4))
    assert "behind_by" not in row and row["mergedBy"]["login"] == "moritz"
    assert not any(c[0][0] == "api" for c in hubd.commands)


def test_pr_files_marks_large_files_and_doesnt_guess_at_binary_ones(github, hubd):
    hubd.answers["pr view 4"] = _open_pr(files=[{"path": "a.py", "additions": 10, "deletions": 2},
                                                  {"path": "big.json", "additions": 390, "deletions": 11},
                                                  {"path": "moved.py", "additions": 0, "deletions": 0}])
    files = asyncio.run(github.pr_files("boot", 4))
    # #37 review 5: a rename or a mode change has no counted lines either, so it is not "binary", and its diff can be shown
    assert [(f["path"], f["large"]) for f in files] == [("a.py", False), ("big.json", True), ("moved.py", False)]


def test_labels_reopen_and_assign_me_go_out_with_the_login(client, hubd):
    signed_in(client)
    hubd.answers["pr view 4"] = json.dumps({"labels": [{"name": "bug"}]})
    hubd.answers["api repos/GlassineOS/boot/issues/7"] = json.dumps({"title": "t", "body": "", "assignees": [{"login": "moritz"}]})
    r = client.post("/api/prs/boot/4/labels", json={"add": ["bug"], "remove": ["wip"]}, headers=ORIGIN)
    assert r.status_code == 200 and r.json() == {"labels": ["bug"]}
    edit = next(c[0] for c in hubd.commands if c[0][:2] == ["pr", "edit"])
    assert edit == ["pr", "edit", "4", "-R", "GlassineOS/boot", "--add-label", "bug", "--remove-label", "wip"]
    assert client.post("/api/prs/boot/4/reopen", json={}, headers=ORIGIN).status_code == 200
    assert client.post("/api/issues/boot/7/labels", json={"add": ["x"]}, headers=ORIGIN).status_code == 200
    r = client.post("/api/issues/boot/7/assign-me", json={}, headers=ORIGIN)
    assert r.status_code == 200 and r.json() == {"assignees": ["moritz"]}
    assert ["issue", "edit", "7", "-R", "GlassineOS/boot", "--add-assignee", "@me"] in [c[0] for c in hubd.commands]
    writes = [login for (argv, _), login in zip(hubd.commands, hubd.logins) if argv[:2] in (["pr", "edit"], ["pr", "reopen"], ["issue", "edit"])]
    assert writes == ["good"] * 4, "every write the work item makes carries the page's login"


def test_the_repository_labels_are_read_from_the_api(client, hubd):
    signed_in(client)
    # gh --paginate prints one array per page, run together
    page = lambda *names: json.dumps([{"name": n, "color": "d73a4a", "description": None, "id": 1} for n in names])
    hubd.answers["api --paginate repos/GlassineOS/boot/labels?per_page=100"] = page("bug") + page("later") + "\n"
    assert client.get("/api/labels/boot").json() == [{"name": n, "color": "d73a4a", "description": ""} for n in ("bug", "later")]


def test_the_failed_step_marks_its_error_lines(client, hubd):
    signed_in(client)
    hubd.answers["api repos/GlassineOS/boot/actions/runs/9/jobs"] = json.dumps({"jobs": [
        {"name": "lint", "conclusion": "success", "steps": []},
        {"name": "test", "conclusion": "failure", "html_url": "https://github.com/GlassineOS/boot/actions/runs/9/job/1",
         "steps": [{"name": "Set up", "conclusion": "success"}, {"name": "Run tests", "conclusion": "failure"}]}]})
    hubd.answers["run view 9"] = ("test\tSet up\t2026-11-06T10:00:00.0000000Z ok\n"
                                  "test\tRun tests\t\ufeff2026-11-06T10:00:01.0000000Z ^[[36;1mcollected 3 items^[[0m\n"
                                  "test\tRun tests\t2026-11-06T10:00:02.0000000Z FAILED tests/test_a.py::test_x\n"
                                  "test\tRun tests\t2026-11-06T10:00:03.0000000Z ##[error]Process completed with exit code 1.\n")
    r = client.get("/api/runs/boot/9/failed-step").json()
    assert r["job"] == "test" and r["step"] == "Run tests" and r["log_url"].endswith("/job/1")
    assert [(l["n"], l["text"], l["error"]) for l in r["lines"]] == [
        (1, "collected 3 items", False), (2, "FAILED tests/test_a.py::test_x", True), (3, "##[error]Process completed with exit code 1.", True)]


def test_a_run_with_no_failed_job_has_no_step(client, hubd):
    signed_in(client)
    hubd.answers["api repos/GlassineOS/boot/actions/runs/9/jobs"] = json.dumps({"jobs": [{"name": "lint", "conclusion": "success"}]})
    assert client.get("/api/runs/boot/9/failed-step").json() == {"job": None, "step": None, "lines": [], "log_url": None}


def test_the_merge_button_sends_the_head_it_showed():
    script = (Path(__file__).resolve().parents[1] / "app" / "hub" / "static" / "app.js").read_text()
    assert "/merge`, { method, head: data.headRefOid })" in script


def _app_js():
    return (Path(__file__).resolve().parents[1] / "app" / "hub" / "static" / "app.js").read_text()


def test_needs_you_is_one_modal_with_decisions_go_and_grants_in_it():
    """A static check: the page isn't run here. Asks, decisions and new work are one Feed in a modal; the Go and
    "I've got the device" are in it, and the old pages are gone, their addresses opening it with the matching filter."""
    script = _app_js()
    nav = re.search(r"const NAV = \[(.*?)\];", script)[1]
    assert '"decisions"' not in nav and '"shells", "Sessions"' in nav
    for gone in ("function DecisionsPage(", "function Inbox(", "function ActiveDecisions(", "decisions: DecisionsPage", "ASK_FILTERS", 'tab: "needs"', 'tab: "active"'):
        assert gone not in script, gone
    modal = _component(script, "NeedsYouModal")
    assert "<${GoPanel} asks=${asks} />" in modal and "<${Feed} " in modal and "showModal()" in modal
    assert '["grants", "Active grants"]' in script and '["decisions", "Decisions"]' in script and '["settled", "Settled"]' in script
    assert "handled in this view" in modal and "<select value=${session}" in modal
    feed = _component(script, "Feed")
    assert feed.index("Blocking") < feed.index("Decisions asked for") < feed.index("Results ready")
    assert '["all", "All"], ["steward", "The Steward"], ["others", "Other sessions"]' in script
    # The old addresses open it: the Decisions page with every decision, Active with the grants.
    assert 'route.path === "decisions" ? "decisions"' in script and 'route.query.tab === "active" ? "grants"' in script
    assert 'api("interactions")' in script and 'api("asks")' not in script and 'api("decisions")' not in script, "one poll"
    assert 'api("new-work")' in script, "LaunchModal and SetAside read the Launch records"
    assert 'post("device/holding"' in script and 'post("decisions", { kind: "go"' in script, "the same login-checked routes"
    for card in ("Ask", "DecisionRow", "SuggestedSession", "WorkWaiting"):
        assert "answerAt(" in _component(script, card), f"{card} answers through interaction.answer, saying where"
    assert "GoPanel" not in _component(script, "DeviceCard") and 'needsYou({ filter: "grants" })' in _component(script, "DeviceCard")


def test_the_header_has_six_views_needs_you_new_work_and_the_meter():
    """A static check: the page isn't run here. FR-082-FR-086a, 007 FR-003, and the old addresses still land somewhere."""
    script = _app_js()
    nav = re.search(r"const NAV = \[(.*?)\];", script)[1]
    assert re.findall(r'\["(\w+)", "([^"]+)"\]', nav) == [("overview", "Overview"), ("roadmap", "Roadmap"), ("work", "Work"),
                                                       ("knowledge", "Knowledge"), ("notes", "Notes"), ("shells", "Sessions")]
    views = re.search(r"const views = \{(.*?)\};", script)[1]
    assert "knowledge: Knowledge" in views and "notes: NotesPage" in views and "device" not in views and "docs" not in views
    for gone in ("function DeviceView(", "function DocsTabs(", "function Docs(", "function Budget(", "nav-count"):
        assert gone not in script, gone
    # Old addresses: the Work pages are tabs, Docs is Knowledge (its notes tab is Notes), Device is Overview's card.
    moved = _component(script, "movedRoute")
    assert 'route.path === "docs") return { path: q.tab === "notes" ? "notes" : "knowledge"' in moved
    assert 'route.path === "device") return { path: "overview"' in moved
    assert 'const OLD_WORK_PAGES = new Set(["issues", "prs", "actions", "queue"])' in script
    assert '["queue", "Queue"]' in script and 'query.tab === "queue" ? html`<${WorkQueue} />`' in script
    # Needs you: yellow (data-waits) only when something blocks, outlined while anything waits, plain at none.
    button = _component(script, "NeedsButton")
    assert 'c.blocking > 0 ? "blocking" : c.pending > 0 ? "pending" : "none"' in button
    assert 'data-waits=${state === "blocking" ? "" : undefined}' in button and "aria-label=${needsLabel(asks)}" in button
    css = (Path(__file__).resolve().parents[1] / "app" / "hub" / "static" / "style.css").read_text()
    assert '.needs-open[data-waits]' in css and '.top .needs-open[data-state="none"]' in css
    assert ".top nav a[aria-current] { background: var(--mark)" not in css, "yellow is only for what waits for you"
    hub = _component(script, "Hub")
    assert "<${NeedsButton} asks=${asks} />" in hub and 'class="primary new-work" onClick=${() => launch({ from: { view: SEEN_SCREEN[here] || "Overview" } })}' in hub
    assert "<${UsageMeter} />" in hub and "host.hubd" in hub and "hubd can't be reached" in hub and 'api("host"), [], 15000' in hub
    overview = _component(script, "Overview")
    assert "<${NeedsYouCard} asks=${asks} />" in overview and "<${BudgetStat} />" in overview and "<${DeviceCard} asks=${asks} />" in overview
    assert "ApiBudget" not in script and "function NeedsYou(" not in script, "the budget is a stat now, and Needs you is a card"
    meter = _component(script, "UsageMeter")
    assert 'api("usage")' in meter and '" · low"' in meter and '"not known"' in meter and "aria-label=${label}" in meter
    # The Steward is told where the person is, in the screens hubd knows.
    seen = re.search(r"const SEEN_SCREEN = \{(.*?)\};", script)[1]
    assert 'knowledge: "Knowledge"' in seen and 'notes: "Notes"' in seen and "Device" not in seen and "Decisions" not in seen
    assert 'tab === "queue") return { screen: "Queue"' in _component(script, "seenFrom")


def test_the_header_reads_the_hubd_address_and_the_usage():
    class Hubd(FakeHubd):
        async def call(self, **request):
            if request["op"] == "usage.status":
                self.commands.append(("usage.status", request))
                return {"ok": True, "known": True, "used": 0.85, "low": True, "says": "85% of the rate limit used, low", "resets": 1, "source": "rate limit", "extra": "x"}
            return await super().call(**request)
    hubd = Hubd()
    client = TestClient(web.build(hubd, None, FakeDocs(), secure_cookie=False, allowed_hosts={"testserver"}))
    assert client.get("/api/usage").status_code == 401
    signed_in(client)
    assert client.get("/api/host").json()["hubd"] == "/run/user/1000/glassine-hub/hubd.sock"
    usage = client.get("/api/usage").json()
    assert usage["low"] is True and "extra" not in usage and hubd.commands[-1][1]["token"] == "good"


def test_interactions_need_a_login_and_answers_the_same_origin():
    seen = []

    class Hubd(FakeHubd):
        async def call(self, **request):
            if request["op"].startswith("interaction."):
                seen.append(request)
                if request["op"] == "interaction.list":
                    return {"ok": True, "items": [], "grants": [], "counts": {"pending": 0, "blocking": 0, "by_kind": {}, "longest_wait": 0}, "holding": None}
                return {"ok": True, "item": {"id": request["id"], "status": "allowed"}}
            return await super().call(**request)
    client = TestClient(web.build(Hubd(), None, FakeDocs(), secure_cookie=False, allowed_hosts={"testserver"}))
    assert client.get("/api/interactions").status_code == 401
    assert client.post("/api/interactions/a:x/answer", json={"verdict": "allow"}, headers=ORIGIN).status_code == 401
    signed_in(client)
    listed = client.get("/api/interactions?session=steward")
    assert listed.status_code == 200 and set(listed.json()) == {"items", "grants", "counts", "holding"}
    assert seen[-1]["session"] == "steward"
    assert client.post("/api/interactions/a:x/answer", json={"verdict": "allow"}).status_code == 403, "same origin only"
    body = {"verdict": "approve", "words": "go on", "scope": {"actions": ["reboot"]}, "ends": {"runs": 1}, "where": "Needs you", "token": "not this"}
    reply = client.post("/api/interactions/d-0123456789ab/answer", json=body, headers=ORIGIN)
    assert reply.status_code == 200 and reply.json() == {"item": {"id": "d-0123456789ab", "status": "allowed"}}
    sent = seen[-1]
    assert (sent["op"], sent["id"], sent["verdict"], sent["where"], sent["ends"]) == ("interaction.answer", "d-0123456789ab", "approve", "Needs you", {"runs": 1})
    assert sent["token"] == "good", "the login's token, never one from the body"


def test_the_merge_tool_makes_the_head_required(github):
    mcp = tools.build(github, FakeDocs())
    merge = next(t for t in asyncio.run(mcp.list_tools()) if t.name == "merge_pr")
    assert "head" in merge.input_schema["required"]


def test_the_device_view_goes_through_a_login_and_the_tool_through_a_token(client, hubd, github):
    assert client.get("/api/device").status_code == 401
    signed_in(client)
    reply = client.get("/api/device").json()
    assert reply["devices"][0]["lines"] and reply["only"].startswith("Only `mkdir`") and "says" not in reply
    assert hubd.commands[-1][1]["token"] == "good"
    token = hubd_client.CALLER.set("session")
    try:
        assert asyncio.run(github.device_status("na1")) == {"says": "na1: Free when last reported, just now."}
    finally:
        hubd_client.CALLER.reset(token)
    assert hubd.commands[-1][1]["agent_token"] == "session" and hubd.commands[-1][1]["device"] == "na1" and "token" not in hubd.commands[-1][1]


def test_device_status_is_read_only_and_only_a_full_session_sees_it():
    assert listed_for({"session": None, "tools": None, "persona": None})["device_status"]["annotations"]["readOnlyHint"] is True
    assert "device_status" not in listed_for({"session": "s", "tools": ["get_pr"], "persona": "x"})


def test_decisions_on_the_page_go_with_the_login(client, hubd):
    assert client.get("/api/decisions").status_code == 401
    assert client.post("/api/decisions", json={}, headers=ORIGIN).status_code == 401
    signed_in(client)
    assert client.post("/api/decisions", json={"kind": "go"}).status_code == 403, "same origin"
    assert client.get("/api/decisions").json()["holding"]["words"] == "words"
    assert client.post("/api/decisions", json={"kind": "go", "words": "w", "scope": {"actions": ["reboot"]}, "ends": {"runs": 1}}, headers=ORIGIN).status_code == 200
    assert hubd.commands[-1][0] == "decision.add" and hubd.commands[-1][1]["token"] == "good"
    assert client.post("/api/decisions/d-1/approve", json={"words": "yes"}, headers=ORIGIN).status_code == 200
    assert hubd.commands[-1][0] == "decision.approve" and hubd.commands[-1][1]["id"] == "d-1" and hubd.commands[-1][1]["token"] == "good"
    assert client.post("/api/decisions/d-1/nonsense", json={}, headers=ORIGIN).status_code == 400
    assert client.post("/api/device/holding", json={"holding": True}, headers=ORIGIN).json() == {"holding": {"holding": True, "words": "words"}, "ended": 2}
    assert client.post("/api/device/holding", json={"holding": False}, headers=ORIGIN).json()["holding"]["holding"] is False
    before = len(hubd.commands)
    for body in ({}, {"holding": "true"}, {"holding": None}, {"holding": 0}):
        assert client.post("/api/device/holding", json=body, headers=ORIGIN).status_code == 400, body
    assert len(hubd.commands) == before, "a body that says nothing doesn't press Done"


def queue_store():
    store = WorkStore(":memory:")
    author = {"login": "a"}
    store.upsert({"__typename": "PullRequest", "id": "P1", "number": 7, "title": "A PR", "body": "Set: fix, 1 of 1\nTested: host\nSee #2", "state": "OPEN", "isDraft": False, "url": "u",
                  "createdAt": "2026-01-01T00:00:00Z", "updatedAt": "2026-01-01T00:00:00Z", "headRefName": "fix", "baseRefName": "main", "headRefOid": "a" * 40, "reviewDecision": "APPROVED",
                  "mergeable": "MERGEABLE", "author": author, "repository": {"name": "hub"}, "labels": {"nodes": []}, "assignees": {"nodes": []}, "comments": {"totalCount": 0, "nodes": []},
                  "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "SUCCESS"}}}]}})
    for number, label in ((2, "blocks-merge"), (3, "bug")):
        store.upsert({"__typename": "Issue", "id": f"I{number}", "number": number, "title": f"Issue {number}", "body": "Why", "state": "OPEN", "url": "u", "createdAt": "2026-01-01T00:00:00Z",
                      "updatedAt": "2026-01-01T00:00:00Z", "author": author, "repository": {"name": "hub"}, "labels": {"nodes": [{"name": label, "color": "", "description": ""}]},
                      "assignees": {"nodes": []}, "comments": {"totalCount": 0, "nodes": []}})
    store.put("synced_at", "100.0")
    return store


def test_the_queue_goes_with_the_login_and_says_so_before_a_sync(client, hubd, github):
    assert client.get("/api/queue").status_code == 401
    client.post("/api/login", json={"user": "u", "password": "right"}, headers=ORIGIN)
    answer = client.get("/api/queue").json()
    assert answer["ready"] is False and "hasn't synced" in answer["says"]
    assert hubd.commands[-1][1]["token"] == "good", "your decisions, by your login"


def test_the_queue_reads_the_store_and_asks_github_nothing(client, hubd, github):
    client.post("/api/login", json={"user": "u", "password": "right"}, headers=ORIGIN)
    github.store = queue_store()
    github.sync = type("Sync", (), {"ready": lambda self: True, "status": lambda self: {"synced_at": 100.0}, "wake": lambda self: None})()
    hubd.commands.clear()
    answer = client.get("/api/queue").json()
    assert [c[0] for c in hubd.commands] == ["decision.list"], "no gh, and nothing else"
    row = answer["sets"][0]["rows"][0]
    assert answer["ready"] and answer["synced_at"] == 100.0 and answer["sets"][0]["name"] == "fix"
    assert (row["repo"], row["number"], row["head"], row["next"], row["tested"]) == ("hub", 7, "a" * 40, True, "It says: host")
    assert row["reviews"] == "Approved by a reviewer" and row["approval"]["state"] == "none", "GitHub's review isn't yours"
    assert [b["number"] for b in row["blockers"]] == [2]
    assert [b["number"] for b in answer["blockers"]] == [2], "only what carries the label"
    assert client.post("/api/queue", json={}, headers=ORIGIN).status_code == 405, "it only reads"


def test_approving_from_the_queue_is_a_decision_for_the_head_shown(client, hubd):
    client.post("/api/login", json={"user": "u", "password": "right"}, headers=ORIGIN)
    scope = {"repo": "hub", "number": 7, "head": "a" * 40}
    assert client.post("/api/decisions", json={"kind": "merge", "words": "Approved on the queue page.", "scope": scope}, headers=ORIGIN).status_code == 200
    assert hubd.commands[-1][0] == "decision.add" and hubd.commands[-1][1]["scope"] == scope and hubd.commands[-1][1]["token"] == "good"


def test_no_tool_has_the_queue():
    assert "merge_queue" not in Path(tools.__file__).read_text()


def test_notes_on_the_page_go_with_the_login(client, hubd):
    assert client.get("/api/notes").status_code == 401
    assert client.post("/api/notes/find", json={"words": "x"}, headers=ORIGIN).status_code == 401
    assert not hubd.commands, "nothing reached hubd without a login"
    client.post("/api/login", json={"user": "u", "password": "right"}, headers=ORIGIN)
    assert client.get("/api/notes").json() == {"here": False, "says": "There are no notes yet."}
    assert client.post("/api/notes/find", json={"words": "x"}).status_code == 403, "same origin"
    found = client.post("/api/notes/find", json={"words": "fault", "limit": 5}, headers=ORIGIN).json()
    assert found == {"here": True, "says": "1 row from notes", "rows": [{"state": "retracted", "where": "a/b:3", "label": "c1", "text": "t"}], "total": 1, "warnings": []}
    assert hubd.commands[-1] == ("notes.find", {"op": "notes.find", "token": "good", "words": "fault", "limit": 5})
    answer = client.post("/api/notes/find", json={"words": "broken"}, headers=ORIGIN)
    assert answer.status_code == 502 and answer.json()["error"] == "the index can't be used", "said in words"


def test_no_tool_reaches_notes():
    source = Path(tools.__file__).read_text() + Path(sys.modules["hub.github"].__file__).read_text()
    assert 'op="notes' not in source and "/api/notes" not in source


def test_decision_tools_send_only_the_sessions_token(hubd, github):
    token = hubd_client.CALLER.set("session")
    try:
        assert asyncio.run(github.decision_check("go", "reboot", "na1")) == {"answer": "no", "words": "No: words"}
        assert hubd.commands[-1] == ("decision.check", {"op": "decision.check", "agent_token": "session", "kind": "go", "actions": "reboot", "target": "na1"})
        assert asyncio.run(github.decision_request("go", {"actions": ["reboot"]}, "why"))["id"] == "d-1"
        assert asyncio.run(github.decision_end("d-1", "done"))["words"]
    finally:
        hubd_client.CALLER.reset(token)
    assert not any(c[0] in ("decision.add", "decision.approve") for c in hubd.commands)


def test_the_merge_tools_name_one_route_for_each_kind_of_session():
    """A tool's text is the same for every session, so it says which route is whose."""
    listed = listed_for({"session": None, "tools": None, "persona": None})
    merge, ask = listed["merge_pr"]["description"], listed["decision_request"]["description"]
    assert "card" in merge and "decision_request" in merge and "decision_check" in merge
    assert "merge_pr" in ask and "cards" in ask


def test_decision_tools_are_annotated_and_held_to_a_list():
    listed = listed_for({"session": None, "tools": None, "persona": None})
    assert listed["decision_check"]["annotations"]["readOnlyHint"] is True
    assert listed["decision_request"]["annotations"]["readOnlyHint"] is False and listed["decision_end"]["annotations"]["readOnlyHint"] is False
    held = listed_for({"session": "s", "tools": ["get_pr"], "persona": "x"})
    assert not {"decision_check", "decision_request", "decision_end", "device_status"} & set(held)


def test_every_running_session_row_says_whether_its_repository_is_private(hubd, github):
    """hubd lists the sessions and the app adds `private`, as the Steward's persona says every row has."""
    real = hubd.call

    async def call(**request):
        if request["op"] == "started.running":
            return {"ok": True, "sessions": [{"name": "a", "repo": "boot"}, {"name": "b", "repo": "secret"}]}
        return await real(**request)

    async def public():
        return {"boot"}
    hubd.call = call
    github._public_repos = public
    rows = asyncio.run(github.running_sessions())
    assert {r["name"]: r["private"] for r in rows} == {"a": False, "b": True}


def test_the_session_tools_give_what_a_session_covers_as_refs(hubd, github):
    """hubd's rows name covered items as repo#N: an item's title is an outsider's text, and these rows reach any session."""
    real = hubd.call
    rows = [{"name": "a", "title": "Implement an issue", "repo": "boot", "number": 9, "also_numbers": [11],
             "covers": ["boot#9", "boot#11", "kernel#2"], "state": "Working"}]

    async def call(**request):
        if request["op"] in ("started.running", "started.list"):
            return {"ok": True, "sessions": [dict(r) for r in rows]}
        return await real(**request)

    async def public():
        return {"boot"}
    hubd.call = call
    github._public_repos = public
    # #29 review: a session on a public repository that covers a private one's item is private.
    assert asyncio.run(github.running_sessions())[0]["private"] is True
    rows[0]["covers"] = ["boot#9", "boot#11"]
    assert asyncio.run(github.running_sessions())[0]["private"] is False
    rows[0]["covers"] = ["boot#9", "boot#11", "kernel#2"]
    for found in (asyncio.run(github.running_sessions()), asyncio.run(github.started_sessions())):
        assert found[0]["covers"] == ["boot#9", "boot#11", "kernel#2"]
        assert all(isinstance(c, str) and re.fullmatch(r"[A-Za-z0-9._-]+#[0-9]+", c) for c in found[0]["covers"])
        assert not {"titles", "items"} & set(found[0])


def test_an_attribute_takes_one_value():
    """Two in a row make a string: the item panel once showed "[object Object][object Object],"."""
    from pathlib import Path
    text = (Path(__file__).parents[1] / "app/hub/static/app.js").read_text()
    assert "</button>`}${open && spawn(" not in text


def _style_css():
    return (Path(__file__).resolve().parents[1] / "app" / "hub" / "static" / "style.css").read_text()


def _component(script, name):
    """The source of one function in app.js, up to the next top-level function."""
    start = script.index(f"function {name}(")
    following = re.search(r"\n(?:function |const |let |// ---)", script[start + 1:])
    return script[start:start + 1 + following.start()] if following else script[start:]


def test_family_tints_pen_and_mark_are_tokens_defined_once():
    """A static check (002 FR-012, 001 FR-011, 001 FR-013): each colour is one token, and nothing else writes the value."""
    css, script = _style_css(), _app_js()
    for token, value in (("--family-build", "#d6e2ff"), ("--family-review", "#eadcff"), ("--mark-2", "#ffd9b8"),
                         ("--family-write", "#d4efdc"), ("--mark-3", "#e2e2e2"), ("--pen", "#2747b8"), ("--mark", "#ffd86b")):
        assert css.lower().count(value) == 1, value
        assert re.search(rf"{token}:\s*{value}", css, re.I), token
        assert value not in script.lower(), f"{value} is written into app.js instead of using its token"
    for family in ("investigate", "organise"):
        assert re.search(rf"--family-{family}:\s*var\(--mark-[23]\)", css)
    for family in ("build", "review", "investigate", "write", "organise"):
        assert f".pbadge.{family} {{ background: var(--family-{family}); }}" in css
    # Night paper for terminals and logs (001 FR-014); the dark block gives the light tints dark values.
    assert "--night: #121212" in css and ".term { background: var(--night)" in css
    dark = css[css.index("@media (prefers-color-scheme: dark)"):]
    dark = dark[:dark.index("\n}")]
    assert all(f"--family-{f}:" in dark for f in ("build", "review", "write"))


def test_severity_is_an_outline_and_pills_never_fill_by_state():
    """A static check (002 FR-003, 001 FR-012): no ItemPill rule sets a background but paper; states pick an outline class."""
    css, script = _style_css(), _app_js()
    for cls, border in (("high", "double"), ("medium", "solid"), ("low", "solid"), ("info", "dashed")):
        assert re.search(rf"\.sev-{cls} {{ border: [\d.]+px {border} var\(--ink\); }}", css), cls
    pill_rules = [line for line in css.splitlines() if ".itempill" in line]
    assert pill_rules and all("background" not in line or "background: var(--paper)" in line for line in pill_rules)
    pill = _component(script, "ItemPill")
    assert "background" not in pill and "style=" not in pill.replace('style="gap: 6px; flex-wrap: nowrap; min-width: 0"', "")
    states = re.search(r"const PILL_STATE = \{(.*?)\};", script, re.S)[1]
    assert set(re.findall(r"(\w+): \[", states)) == {"open", "draft", "merged", "closed", "failing", "running", "passed", "cancelled", "skipped"}
    assert all(re.search(rf'{s}: \["{s}", "sev-', states) for s in ("open", "failing", "draft")), "each state has its word"
    assert "aria-label=${name}" in pill and "Remove ${ref(item)}" in pill


def test_the_repo_picker_shows_a_count_past_three():
    """A static check (002 FR-007): more than 3 chosen repositories read as a count, never as a list of pills."""
    picker = _component(_app_js(), "RepoPicker")
    assert "chosen.length > 3 ? `${chosen.length} repos`" in picker
    assert "localStorage" not in picker and "readPicks" in picker, "storage goes through the try/catch helpers"
    keys = _component(_app_js(), "listKeys")
    assert all(k in keys for k in ('"ArrowDown"', '"ArrowUp"', '"Enter"', '"Escape"')), "002 FR-010"
    picks = _component(_app_js(), "readPicks") + _component(_app_js(), "writePicks")
    assert picks.count("try {") == 2


def test_yellow_marks_only_a_session_that_waits():
    """A static check (002 FR-017, 001 FR-011): a chip is yellow only under [data-waits], set only when it waits."""
    css, script = _style_css(), _app_js()
    chip_rules = [line for line in css.splitlines() if line.startswith(".sesschip")]
    assert [line for line in chip_rules if "var(--mark)" in line] == [
        ".sesschip[data-waits], .sesschip[data-waits]:hover:not(:disabled) { background: var(--mark); font-weight: 600; }"]
    chip = _component(script, "SessionChip")
    assert '"data-waits": waits ? "" : undefined' in chip and "aria-label" in chip
    assert "${pending} waiting" in chip and "state.toUpperCase()" in chip
    state = _component(script, "sessionState")
    assert all(f'"{s}"' in state for s in ("done", "waiting", "attached", "running"))


def test_the_steward_and_plain_shells_have_their_own_badges():
    """A static check (002 FR-013, 002 FR-014): the pen-blue S is drawn for the Steward only; a plain shell is no family."""
    badge = _component(_app_js(), "PersonaBadge")
    assert 'persona.id === STEWARD) return html`<span class="pbadge steward"' in badge
    assert 'if (!persona) return html`<span class="pbadge shell"' in badge
    assert '"aria-label": label' in badge
    css = _style_css()
    assert ".pbadge.steward { background: var(--pen);" in css


def test_the_shared_components_are_used():
    """A static check (tasks.md 002 T014): each component has a place in this release, so none is dead code."""
    script = _app_js()
    for used in ("<${SessionChip} ", "<${ItemPill} ", "<${RepoPicker} ", "<${PersonaBadge} ", "<${FamilyLegend} />", "<${ItemPicker} "):
        assert used in script.replace(_component(script, "FamilyLegend"), "").replace(_component(script, "SessionChip"), ""), used
    assert "RepoSelect" not in script and 'class="sesschip" href' not in script


def test_every_component_the_page_renders_is_defined():
    """A removed view must not leave a <${Name} /> behind: it only fails when that branch renders."""
    script = _app_js()
    used = set(re.findall(r"<\$\{([A-Za-z_]\w*)\}", script))
    defined = set(re.findall(r"(?:function|const|let|class)\s+([A-Za-z_]\w*)", script))
    defined |= {n.strip() for group in re.findall(r"import\s*\{([^}]*)\}", script) for n in group.split(",")}
    assert used - defined == set()


def test_a_page_that_cant_reach_hubd_is_told_so_not_signed_out():
    """001 FR-005, 001 FR-020: no hubd is a 503 the page shows as a banner; a refused login is still a 401. Neither reads anything."""
    class Gone(FakeHubd):
        async def call(self, **request):
            if request["op"] == "auth.check":
                raise HubdError("hubd is not reachable: no such file", unreachable=True)
            return await super().call(**request)
    client = TestClient(web.build(Gone(), None, FakeDocs(), secure_cookie=False, allowed_hosts={"testserver"}))
    client.cookies.set("hub_session", "good")
    reply = client.get("/api/interactions")
    assert reply.status_code == 503 and reply.json() == {"error": "hubd can't be reached", "unreachable": True}
    client = TestClient(web.build(FakeHubd(), None, FakeDocs(), secure_cookie=False, allowed_hosts={"testserver"}))
    client.cookies.set("hub_session", "nope")
    assert client.get("/api/interactions").status_code == 401
    assert "hostPoll.error || listed.error" in _component(_app_js(), "Hub")


def test_a_reset_on_another_day_names_the_day():
    words = re.search(r"const resetWords = .*?\n};", _app_js(), re.S)[0]
    assert "toDateString() === new Date().toDateString() ? time :" in words and "toLocaleDateString" in words
    node = shutil.which("node")
    if node:  # run it: today gives the time alone, a week on gives the date too
        out = subprocess.run([node, "-e", words.replace("const resetWords", "var resetWords") + """
const now = Math.floor(Date.now() / 1000);
console.log(JSON.stringify([resetWords(now), resetWords(now + 7 * 86400), resetWords("Monday")]));"""], capture_output=True, text=True, check=True).stdout
        today, later, text = json.loads(out)
        assert len(later) > len(today) + 4 and text == "Monday"


def test_a_failed_reload_keeps_what_the_views_showed():
    """001 FR-005: the banner says "showing what was last read", so useLoad keeps its data on an error (not for other deps)."""
    script = _app_js()
    load = _component(script, "useLoad")
    assert "set({ error: error.message" not in load, "an error alone would drop the data the banner promises"
    assert "...(loadedFor.current === sig ? s : {}), error: error.message, loading: false" in load
    assert "loadedFor.current = sig; set({ data, loading: false })" in load, "a good read clears the error and notes what it was for"
    for view in ("IssueDetail", "PrDetail", "RunDetail"):
        source = _component(script, view)
        assert "if (error && !data) return" in source and "if (error) return" not in source, f"{view} keeps the item it showed"
        assert re.search(r"<\$\{Err\} text=\$\{[\w. |]*\berror\} />", source), f"{view} shows the error beside the item"


def test_every_claude_session_is_a_chat():
    """A static check (004 FR-008, 010 FR-006): the Steward panel and Sessions both have a message field, posting to say."""
    script = _app_js()
    field = _component(script, "MessageField")
    assert 'post("agents/say", { name, text, where })' in field and "agents/press" not in field
    assert 'role="status"' in field and "<${Err} text=${act.error}" in field and "<label" in field
    # Both draw it through the SessionView, which has the field for every Claude session.
    assert "<${MessageField} key=${name} name=${name} where=${where}" in _component(script, "SessionView")
    assert '<${SessionView} session=${session} mode="compact"' in _component(script, "StewardSession")
    assert '<${SessionView} key=${current.name} session=${current} mode="full"' in _component(script, "Shells")


def test_the_work_item_has_its_black_github_button_and_its_sections():
    """A static check (006 FR-011–FR-033): the black split button acts as you, every entry in its menu has a branch for
    why it's off, Merge goes through hubd's merge path with the head, and the item's sections are where the spec puts them."""
    script, css = _app_js(), _style_css()
    entries = _component(script, "ghEntries")
    ids = re.findall(r'\{ id: "([a-z-]+)"', entries) + re.findall(r'id: `close-\$\{reason\}`', entries)
    assert len(ids) >= 13
    assert entries.count("disabled:") >= len(ids) + 1, "every entry, Open on GitHub too, says whether it's off"
    assert "blockers.join" in entries and "merged pull requests can't reopen" in entries
    assert "HOST_USER" not in entries and "assigned to you" not in entries, "the host's Unix user is not a GitHub login"
    gh = _component(script, "GhActions")
    assert 'class="gh"' in gh and "On GitHub, as" in gh and 'aria-haspopup="menu"' in gh and 'role="menuitem"' in gh
    assert "/merge`, { method, head: data.headRefOid })" in gh and "confirm({ ...e.confirm, danger: true }, doIt)" in gh
    assert 'class="primary"' not in gh and 'class="pen"' not in gh, "the GitHub button is never blue"
    assert "background: var(--ink)" in re.search(r"\nbutton\.gh, \.button\.gh \{[^}]*\}", css).group(0)
    frame = _component(script, "ItemFrame")
    assert 'aria-label="Breadcrumb"' in frame and "Details" in frame and "<${DetailsFlyout}" in frame
    assert "Large file — load the diff" in _component(script, "FileDiff") and "diffRows(diff.data)" in _component(script, "FileDiff")
    assert '<li class=${l.error ? "err" : ""}' in _component(script, "FailedStep")
    assert "Sessions on ${here} · ${sessions.length}" in _component(script, "SessionsOn") and "sent to background" in _component(script, "SessionsOn")
    assert "<${SuggestBest} " in _component(script, "SessionsOn")
    assert 'launch({ verb: "address", covers: [{ kind: "pr", repo, number }], pins: address.map(threadPin)' in _component(script, "Threads")
    assert 'launch({ verb: "review", covers: [{ kind: "pr", repo, number }]' in _component(script, "PrDetail")
    assert "＋ New work from this…" in _component(script, "LaunchRow") and "bestAction(kind, facts, offered)" in _component(script, "LaunchRow")


ALL_VERBS = ("review", "fix", "address", "triage", "implement", "investigate")


@pytest.mark.parametrize("facts, kind, verb, offered", [
    ({"failing": True}, "pr", "fix", ALL_VERBS), ({"failing": True}, "run", "fix", ALL_VERBS),
    ({"failing": True}, "run", "investigate", ("investigate", "review")),  # no fix offered: investigate
    ({"changesRequested": True, "openThreads": 0}, "pr", "address", ALL_VERBS),
    ({"openThreads": 2}, "pr", "address", ALL_VERBS), ({"untriaged": True}, "issue", "triage", ALL_VERBS), ({}, "pr", "review", ALL_VERBS),
    ({}, "issue", "implement", ALL_VERBS), ({}, "run", "investigate", ALL_VERBS),
])
def test_best_action_picks_by_the_items_state(facts, kind, verb, offered):
    """bestAction (006 FR-007) runs in node, on the function as it is in app.js. Work's rows and the item page share it."""
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node isn't installed")
    script = _app_js()
    src = script[script.index("const BEST_VERB"):script.index("const useKindActions")]
    actions = [{"id": v, "verb": v} for v in offered]
    code = src + f"\nconsole.log(bestAction({json.dumps(kind)}, {{openThreads: 0, ...{json.dumps(facts)}}}, {json.dumps(actions)}).verb);"
    assert subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout.strip() == verb


def test_one_session_view_everywhere():
    """A static check (004 FR-001, FR-005, FR-009, FR-011): one SessionView in Sessions, Work and the Steward panel;
    its terminal on night paper; Stop only after a confirmation; the old manifest column gone."""
    script, css = _app_js(), _style_css()
    view = _component(script, "SessionView")
    assert "<${SessionsOn} " in _component(script, "WorkLists")
    assert '<${SessionView} key=${current.name} session=${current} mode="embedded"' in _component(script, "SessionsOn")
    assert "function Manifest(" not in script and "<${Manifest}" not in script and ".manifest" not in css
    assert "background: var(--night)" in re.search(r"\n\.term \{[^}]*\}", css).group(0)
    assert "background: var(--night)" in re.search(r"\n\.svterm \{[^}]*\}", css).group(0)
    assert 'getPropertyValue("--night")' in script and "background: nightPaper()" in _component(script, "TerminalView")
    # Stop: a Confirm first, then the DELETE, never the DELETE on its own.
    stop = view[view.index("const stop = () => confirm("):]
    stop = stop[:stop.index("\n  );")]
    assert 'danger: true' in stop and stop.index("confirm(") < stop.index('method: "DELETE"')
    assert view.count('method: "DELETE"') == 1 and "onClick=${stop}" in view
    # The spec, the origin in words, the state in words, the stored view, the other items.
    spec = _component(script, "SessionSpec")
    for row in ("Persona", "Action", "Model", "Permission mode", "Ceiling", "Covered items", "Worktree", "Branch", "Start command"):
        assert f"<dt>{row}</dt>" in spec, row
    assert "started before origins were kept" in _component(script, "originWords")
    assert 'post("agents/view"' in view and 'aria-label="Also on these items"' in view and "Ask} key=${x.id}" in view
    assert "Waiting for you" in _component(script, "sessionWords")


def test_work_says_when_stop_kept_the_checkout():
    """A static check only (the JS isn't run): Stop from a Work item uses shell.kill's reply, as Sessions does (#34 review 4)."""
    lists = _component(_app_js(), "WorkLists")
    assert "onEnded=${(r) => { setKeptCheckout(r && r.kept ? { ref: here, path: r.kept } : null)" in lists
    assert "keptCheckout.ref === here" in lists and "<code>${keptCheckout.path}</code>" in lists


def test_the_steward_panel_reloads_its_state_after_a_press():
    """A static check only (the JS isn't run): the compact SessionView gets the panel's reload as `after` (#34 review 6)."""
    script = _app_js()
    assert "const act = useAct(after);" in _component(script, "SessionView")
    assert "after=${reload}" in _component(script, "StewardSession")


def test_the_steward_panel_has_stop_behind_a_confirmation():
    """A static check only (the JS isn't run; 004 FR-011): the panel's head has Stop while the Steward runs, and the DELETE sits inside the confirm."""
    steward = _component(_app_js(), "Steward")
    stop = steward[steward.index("const stop = () => confirm("):]
    stop = stop[:stop.index("\n  );")]
    assert "danger: true" in stop and stop.index("confirm(") < stop.index('method: "DELETE"') and "shells/${encodeURIComponent(STEWARD)}" in stop
    assert steward.count('method: "DELETE"') == 1 and "discard" not in stop
    assert "${running && html`<button class=\"plain\" disabled=${stopping.busy} onClick=${stop}>Stop…</button>`}" in steward
    assert "${dialog}" in steward and "useAct(reload)" in steward


def test_the_sessions_list_polls_quickly():
    """A static check only (the JS isn't run): a session started elsewhere shows within seconds, not after the 15 s poll or a reload."""
    script = _app_js()
    assert re.search(r"^const SESSIONS_EVERY = (\d+);", script, re.M) and int(re.search(r"^const SESSIONS_EVERY = (\d+);", script, re.M).group(1)) <= 5000
    shells = _component(script, "Shells")
    assert 'useLoad(() => api("shells"), [], SESSIONS_EVERY)' in shells and "SESSIONS_EVERY)" in shells.split("const stopped")[1]


def test_the_terminal_keeps_your_place():
    """A static check (004 FR-005): tmux, not the page, keeps your place while output arrives."""
    term = _component(_app_js(), "TerminalView")
    # The place is kept by tmux copy mode (the wheel, with tmux's mouse on): the page leaves the scrolling to it.
    assert "scrollToBottom" not in term and "copy mode keeps your place" in term
    assert '"mouse", "on"' in (Path(__file__).resolve().parents[1] / "hubd" / "shells.py").read_text()


# --- results (005 R2): who sees submit_result, and sessions started before it ----------------------
def test_submit_result_is_listed_only_for_a_token_whose_action_has_it():
    from hubd.agents import Library
    library = Library(Path(__file__).parents[1] / "agents")
    review = library.actions["pr-review"]["hub_tools"]
    assert "submit_result" in listed_for({"session": "s", "tools": review, "persona": "reviewer"})
    assert "review_pr" not in listed_for({"session": "s", "tools": review, "persona": "reviewer"})
    implement_less = library.actions["pr-explain"]["hub_tools"]
    assert "submit_result" not in listed_for({"session": "s", "tools": implement_less, "persona": "x"})
    listed = {t.name: t for t in asyncio.run(tools.build(GitHub(Hubd("/nonexistent"), CONFIG), FakeDocs()).list_tools())}
    assert listed["submit_result"].annotations.read_only_hint is False and listed["submit_result"].annotations.destructive_hint is False


def test_a_session_started_with_the_old_review_tools_still_reaches_review_pr():
    """The running-session rule: its scope is its own frozen list, so it keeps review_pr and never sees submit_result."""
    old = ["get_pr", "get_pr_diff", "review_pr", "docs_search"]
    plain = Hubd("/nonexistent")

    async def call(**request):
        if request["op"] == "auth.check_agent":
            return {"ok": True, "scope": {"session": "pr-review-boot-5", "tools": old, "persona": "reviewer"}}
        if request["op"] == "gh":
            return {"ok": True, "code": 0, "stdout": "", "stderr": ""}
        return {"ok": True}
    plain.call = call
    assert "review_pr" in listed_for({"session": "s", "tools": old, "persona": "reviewer"})
    with TestClient(main.agent_app(plain, GitHub(plain, CONFIG), FakeDocs(), 9095), base_url="http://127.0.0.1:9095") as client:
        assert "doesn't have the tool" not in _tool_call(client, "review_pr", token="old").text
        assert "doesn't have the tool submit_result" in _tool_call(client, "submit_result", token="old").json()["error"]["message"]


def test_submit_result_goes_to_hubd_under_the_sessions_token(github, hubd):
    async def go():
        hubd_client.CALLER.set("session-token")
        return await github.submit_result("comment", {"summary": "s", "event": "comment"})
    original = hubd.call

    async def call(**request):
        assert request == {"op": "result.submit", "agent_token": "session-token", "type": "comment", "payload": {"summary": "s", "event": "comment"}}
        return {"ok": True, "id": "r-0123456789ab"}
    hubd.call = call
    assert asyncio.run(go())["handed_in"] == "r-0123456789ab"
    hubd.call = original


def test_results_and_the_background_go_through_to_hubd_for_a_login():
    seen = []

    class Recording(FakeHubd):
        async def call(self, **request):
            if request["op"].startswith(("result.", "work.")):
                seen.append(request)
                return {"ok": True, "results": [], "result": {"id": request.get("id")}, "work": {"id": request.get("id")}}
            return await super().call(**request)
    client = TestClient(web.build(Recording(), None, FakeDocs(), secure_cookie=False, allowed_hosts={"testserver"}))
    assert client.get("/api/results").status_code == 401
    signed_in(client)
    assert client.get("/api/results?type=comment&kept=1&session=s1").status_code == 200
    assert seen[-1] == {"op": "result.list", "token": "good", "type": "comment", "kept": True, "session": "s1", "after": None}
    assert client.post("/api/results/r-0123456789ab/apply", json={"indexes": [0]}, headers=ORIGIN).status_code == 200
    assert seen[-1] == {"op": "result.apply", "token": "good", "id": "r-0123456789ab", "indexes": [0]}
    assert client.post("/api/results/r-0123456789ab/post", json={}, headers=ORIGIN).status_code == 400
    assert client.post("/api/results/r-0123456789ab/dismiss", json={}).status_code == 403  # same origin only
    assert client.post("/api/new-work/0123456789ab/background", json={"on": True}, headers=ORIGIN).status_code == 200
    assert seen[-1] == {"op": "work.background", "token": "good", "id": "0123456789ab", "on": True}
    body = {"action": "issue-implement", "covers": [{"kind": "issue", "repo": "kernel", "number": 204}], "from": {"view": "Work"}, "background": False}
    assert client.post("/api/new-work", json=body, headers=ORIGIN).status_code == 200
    assert {k: seen[-1][k] for k in ("op", "covers", "from", "background")} == {"op": "work.start", **{k: body[k] for k in ("covers", "from", "background")}}


def test_a_result_card_shows_its_words_as_text_and_applies_through_the_answer():
    """A static check (005 R2, 003 FR-010): Needs you posts a review or applies labels a session handed in, through the answer."""
    script = _app_js()
    view = _component(script, "ResultView")
    assert "answerAt(r.id, { verdict, ...extra }, where)" in view and 'answer("dismiss")' in view
    assert re.search(r"const plainText = .*white-space: pre-wrap", script), "a session's text as text"
    assert "<${Md}" not in view
    assert 'item.kind === "result" && d.type' in _component(script, "InteractionCard")


def test_launch_is_one_modal_with_five_stages_opened_by_one_event():
    """A static check (005 T028): the page isn't run here. Launch replaces the old planner forms and the advanced page;
    every entry point dispatches hub-launch with where it was opened; the brief posts covers and from."""
    script = _app_js()
    for gone in ("hub-new-work", "hub-start-form", "function Spawn(", "function NewWork(", "function StartForm(", "function Launch(",
                 "advancedHandoff", "rowPlan", "const plans =", "planErrors", "const steering", "planWork(", "startForm(", 'hash("launch"'):
        assert gone not in script, gone
    stages = re.search(r"const LAUNCH_STAGES = \[(.*?)\];", script)[1]
    assert re.findall(r'\["(\w+)", "\w+"\]', stages) == ["brief", "planning", "plan", "run", "result"]
    hub = _component(script, "Hub")
    assert 'window.addEventListener("hub-launch", show)' in hub and "<${LaunchModal} " in hub
    assert "launch: Launch" not in re.search(r"const views = \{(.*?)\};", script)[1]
    brief = _component(script, "LaunchBrief")
    assert 'post("new-work", {' in brief and "covers: onItems ? covers : null" in brief and "from: seed.from || null" in brief
    assert "launchRefusal(action, covers)" in brief and "result_words" in brief and "action.ceiling" in brief
    assert "<${ItemPicker} " in brief and "<${RepoPicker} " in brief and "<${SteerFields} " in brief and "<${PlannerModel} " in brief
    modal = _component(script, "LaunchModal")
    assert "`new-work/${live.id}/background`, { on: true }" in modal and "/approve`" in modal
    # between Plan and the list having the new record, the brief must not come back with Plan enabled (a second click would plan twice)
    assert "setFresh(w.id); setId(w.id)" in modal and 'const starting = !live && id !== null && id === fresh;' in modal
    assert 'starting ? "planning" :' in modal
    assert 'mode="compact"' in _component(script, "LaunchRun")
    # Each entry point says where it was opened (005 FR-001), in the screens hubd knows.
    assert 'launch({ action: action.id, covers: [{ kind, repo: row.repo, number: row.number }], from: { view: "Work"' in _component(script, "WorkRow")
    assert 'from: { view: "Work", ref: here }' in _component(script, "LaunchRow")
    assert 'from: { view: "Roadmap" }' in _component(script, "Roadmap") and 'from: { view: "Overview" }' in _component(script, "RepoDetail")
    assert "from: { view: seen.screen" in _component(script, "Steward")
    assert "launch({ id: item.id" in _component(script, "SuggestedSession")
    # The old address lands on the item.
    assert 'route.path === "launch"' in _component(script, "movedRoute")


def test_every_result_type_has_its_view_in_launch_and_in_needs_you():
    """A static check (005 FR-015–FR-020, 003 FR-010): one ResultView, used by the Launch result stage and by the card."""
    script = _app_js()
    view = _component(script, "ResultView")
    for kind, press in (("comment", ">Post<"), ("labels", ">Apply<"), ("findings", ">Start a fix session<"), ("report", ">Save to Knowledge<"), ("pr", "Closes ")):
        assert f'r.type === "{kind}"' in view and press in view, kind
    assert 'answer("apply")' in view and 'answer("keep")' in view and 'answer("dismiss")' in view
    assert "<${ResultView} " in _component(script, "InteractionCard") and "<${ResultView} " in _component(script, "LaunchResult")
    drafts = _component(script, "DraftsResult")
    # an open edit isn't saved by File: both are off until it's saved or cancelled
    assert "Boolean(editing) || !chosen.length || unknown.length > 0} onClick=${file}" in drafts and "Boolean(editing) || !chosen.length} onClick=${hand}" in drafts
    assert "`new-work/${item.id}/file`" in drafts and "`new-work/${item.id}/hand`" in drafts and "`new-work/${item.id}/edit`" in drafts
    assert "dangerouslySetInnerHTML" not in view, "a session's text is shown, never rendered"
    # the findings are a session's words: the fix session's brief says whose they are, and shows them in full
    assert 'launch({ verb: "fix", notes, by: r.session, from: { view: where } })' in view
    brief = _component(script, "LaunchBrief")
    assert "rows=${suggester ? 8 : 2}" in brief and "reach the planner and the session as yours" in brief


def test_sessions_running_groups_badges_and_history_filters():
    """A static check (004 FR-012–FR-019, FR-022): the page isn't run here."""
    script = _app_js()
    groups = re.search(r"const RUN_GROUPS = \[(.*?)\];", script)[1]
    assert re.findall(r'\["(\w+)", "[^"]+"\]', groups) == ["embedded", "background", "finished", "plain"]
    shells = _component(script, "Shells")
    # A session started elsewhere shows without a reload: polled every SESSIONS_EVERY (test_the_sessions_list_polls_quickly).
    assert 'useLoad(() => api("shells"), [], SESSIONS_EVERY)' in shells
    assert "Badges only" in shells and "<${FamilyLegend} />" in shells and "waiting" in shells and "⇄ also on" in shells
    assert "originWords(a)" in shells and "Resume a past session" in shells and "<${NewShell} " in shells
    assert 'post("agents/worktrees", { repo })' in _component(script, "NewShell") and "<${RepoPicker} " in _component(script, "NewShell")
    # #36 review, 4: no Start in the last repository's folder while the next one's list loads.
    new_shell = _component(script, "NewShell")
    assert "setRepo(r); setCwd(\"\");" in new_shell and "!name.trim() || loadingPlaces}" in new_shell
    past = _component(script, "PastSessions")
    assert 'post("agents/past", { persona: persona || undefined, repo: repo || undefined, outcome:' in past
    assert "Running again" in past and "Resuming…" in past and "Restoring…" in past
    # #36 review, 3: by the conversation's id from hubd, and Transcript stays whatever the first button is.
    assert "[persona, repo, filter, running]" in past and "const runningAgain = (r) => r.running_again;" in past and "${r.transcript && html`<button disabled=${act.busy} onClick=${() => setReading(r)}>Transcript</button>`}" in past
    clean = _component(script, "Cleanup")
    assert "safe.filter((r) => r.pr_settled)" in clean and ">Select safe<" in clean and "r.commands.join" in clean and 'role="switch"' in clean


# --- Work (006/PR 2) --------------------------------------------------------------------------
WORKFLOW = """name: Release
on:
  push:
    branches: [main]
  workflow_dispatch:
    inputs:
      level:
        description: "How loud"
        required: true
        default: 'warning'
        type: choice
        options:
        - info
        - warning
      dry:
        type: boolean
        default: true
      target:
        type: environment
      note: # a plain one
        description: free text
jobs:
  a:
    runs-on: ubuntu-latest
"""


@pytest.mark.parametrize("text, dispatchable, names", [
    (WORKFLOW, True, ["level", "dry", "target", "note"]),
    ("on: workflow_dispatch\njobs: {}", True, []),
    ("on: [push, workflow_dispatch]", True, []),
    ('"on":\n  - pull_request\n  - workflow_dispatch', True, []),
    ("on:\n  workflow_dispatch:\n  push:", True, []),
    ("on:\n  push:\n    branches: [main]\njobs:\n  x:\n    steps: []", False, []),
    ("on: push", False, []),
    ("name: no trigger at all", False, []),
    ("on:\n  workflow_dispatch:\n    inputs:\n      who:\n        type: choice\n        options: [a, 'b c']", True, ["who"]),
])
def test_the_workflow_reader_finds_dispatch_and_its_inputs(text, dispatchable, names):
    from hub.workflowfile import dispatch_inputs
    found, inputs = dispatch_inputs(text)
    assert found is dispatchable and [i["name"] for i in inputs] == names


def test_the_workflow_reader_keeps_a_comma_inside_quotes():
    from hub.workflowfile import dispatch_inputs
    text = "on:\n  workflow_dispatch:\n    inputs:\n      w:\n        type: choice\n        options: ['a, b', c, \"d, e\", 'f[1]']"
    assert dispatch_inputs(text)[1][0]["options"] == ["a, b", "c", "d, e", "f[1]"]


def test_the_workflow_reader_types_each_input():
    from hub.workflowfile import dispatch_inputs
    inputs = {i["name"]: i for i in dispatch_inputs(WORKFLOW)[1]}
    assert inputs["level"] == {"name": "level", "type": "choice", "required": True, "description": "How loud", "default": "warning", "options": ["info", "warning"]}
    assert inputs["dry"]["type"] == "boolean" and inputs["dry"]["default"] is True
    assert inputs["target"]["type"] == "environment" and inputs["note"]["type"] == "string" and "default" not in inputs["note"]
    assert dispatch_inputs("on:\n  workflow_dispatch:\n    inputs:\n      w:\n        type: choice\n        options: [x, y]")[1][0]["options"] == ["x", "y"]


@pytest.mark.parametrize("text, words", [
    ("on:\n  workflow_dispatch:\n    inputs:\n      a: &anchor\n        type: string", "settings aren't a block"),
    ("on:\n  workflow_dispatch:\n    inputs:\n      a:\n        type: secret", "type secret"),
    ("on:\n  workflow_dispatch:\n    inputs:\n      a:\n        type: choice", "no options"),
    ("on: {workflow_dispatch: {}}", "braces"),
    ("on: [push,\n  workflow_dispatch]", "doesn't close on its line"),
    ("on:\n  workflow_dispatch:\n    inputs:\n      w:\n        type: choice\n        options: [dev,\n          prod]", "doesn't close on its line"),
    ("on: [push, 'workflow_dispatch]", "doesn't close"),
    ("on:\n  workflow_dispatch:\n    inputs:\n      w:\n        type: choice\n        options: [a, 'b]", "doesn't close"),
    ("on:\n  workflow_dispatch:\n    inputs:\n      w:\n        type: choice\n        options: [a, [b]]", "nested list"),
])
def test_the_workflow_reader_says_what_it_cant_read(text, words):
    from hub.workflowfile import Unreadable, dispatch_inputs
    with pytest.raises(Unreadable, match=re.escape(words)):
        dispatch_inputs(text)


def _contents(text):
    import base64
    return json.dumps({"encoding": "base64", "content": base64.b64encode(text.encode()).decode()})


def test_workflows_say_which_can_be_started_by_hand(client, hubd):
    signed_in(client)
    hubd.answers["workflow list"] = json.dumps([
        {"id": 1, "name": "Release", "path": ".github/workflows/release.yml", "state": "active"},
        {"id": 2, "name": "CI", "path": ".github/workflows/ci.yml", "state": "active"},
        {"id": 3, "name": "Old", "path": ".github/workflows/old.yml", "state": "disabled_manually"},
        {"id": 4, "name": "CodeQL", "path": "dynamic/github-code-scanning/codeql", "state": "active"},
        {"id": 5, "name": "Broken", "path": ".github/workflows/broken.yml", "state": "active"}])
    hubd.answers["api repos/GlassineOS/boot/contents/.github/workflows/release.yml"] = _contents(WORKFLOW)
    hubd.answers["api repos/GlassineOS/boot/contents/.github/workflows/ci.yml"] = _contents("on: push")
    hubd.answers["api repos/GlassineOS/boot/contents/.github/workflows/broken.yml"] = GhError("HTTP 404")
    rows = {w["name"]: w for w in client.get("/api/workflows/boot").json()}
    assert [rows[n]["dispatchable"] for n in ("Release", "CI", "Old", "CodeQL", "Broken")] == [True, False, False, False, None]
    assert "couldn't read broken.yml" in rows["Broken"]["inputs_error"]
    read = client.get("/api/workflows/boot?inputs=release.yml&ref=feature/x").json()
    assert read["dispatchable"] is True and [i["type"] for i in read["inputs"]] == ["choice", "boolean", "environment", "string"]
    assert ["api", "repos/GlassineOS/boot/contents/.github/workflows/release.yml?ref=feature%2Fx"] in [c for c, _ in hubd.commands]


def test_one_odd_workflow_file_name_doesnt_fail_the_list(client, hubd):
    signed_in(client)
    hubd.answers["workflow list"] = json.dumps([
        {"id": 1, "name": "CI", "path": ".github/workflows/ci.yml", "state": "active"},
        {"id": 2, "name": "Release Build", "path": ".github/workflows/Release Build.yml", "state": "active"}])
    hubd.answers["api repos/GlassineOS/boot/contents/.github/workflows/ci.yml"] = _contents(WORKFLOW)
    reply = client.get("/api/workflows/boot")
    assert reply.status_code == 200, reply.text
    rows = {w["name"]: w for w in reply.json()}
    assert rows["CI"]["dispatchable"] is True and "inputs_error" not in rows["CI"]
    assert rows["Release Build"]["dispatchable"] is None and "couldn't read Release Build.yml" in rows["Release Build"]["inputs_error"]
    assert not any("Release" in " ".join(c) for c, _ in hubd.commands if c[0] == "api")  # nothing was asked of GitHub for it


@pytest.mark.parametrize("query", ["inputs=../x.yml", "inputs=a/b.yml", "inputs=x.sh", "inputs=x.yml&ref=a..b", "inputs=x.yml&ref=-x", "inputs=x.yml&ref={x}"])
def test_a_workflows_inputs_are_read_only_by_a_plain_file_and_ref(client, hubd, query):
    signed_in(client)
    assert client.get(f"/api/workflows/boot?{query}").status_code == 400
    assert not [c for c, _ in hubd.commands if c and c[0] == "api"]


def test_a_new_issue_writes_part_of_as_its_first_line(client, hubd):
    signed_in(client)
    hubd.answers["issue create"] = "https://github.com/GlassineOS/boot/issues/7\n"
    r = client.post("/api/issues/boot", json={"title": "T", "body": "The text.", "labels": ["bug"], "part_of": "hub#40"}, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["number"] == 7
    argv, stdin = next((c, s) for c, s in hubd.commands if c[:2] == ["issue", "create"])
    assert stdin == "Part of GlassineOS/hub#40\n\nThe text.\n" and argv[argv.index("--label") + 1] == "bug"
    assert client.post("/api/issues/boot", json={"title": "T", "part_of": "hub 40"}, headers=ORIGIN).status_code == 400


def test_lists_ask_for_as_many_rows_as_the_page_wants(client, hubd):
    """001 FR-019: Work loads one page, and more on request."""
    signed_in(client)
    client.get("/api/prs?repo=boot&limit=100")
    client.get("/api/runs?repo=boot&limit=25")
    argv = [c for c, _ in hubd.commands]
    assert any(c[:2] == ["pr", "list"] and c[c.index("--limit") + 1] == "100" for c in argv)
    assert any(c[:2] == ["run", "list"] and c[c.index("--limit") + 1] == "25" for c in argv)
    assert client.get("/api/prs?limit=lots").status_code == 400


def _work_js(fn):
    """The Work rows' code, run in node with the bits of the app it needs."""
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node isn't installed")
    script = _app_js()
    src = script[script.index("const sizeWords"):script.index("function readWorkFilter")]
    best = script[script.index("function offeredFor"):script.index("const useKindActions")]
    stubs = "const count = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`; const pillState = () => null;\n"
    return subprocess.run(["node", "-e", stubs + src + best + fn], capture_output=True, text=True, check=True).stdout


def test_work_groups_rows_by_what_they_need():
    """006 FR-003–FR-005, FR-007 on store-shaped rows: each row's group and its one blue action."""
    pr = lambda **kw: {"repo": "boot", "number": 1, "title": "t", "state": "OPEN", "isDraft": False, "labels": [], "author": {"login": "a"},
                       "headRefName": "x", "baseRefName": "main", "checks": "passing", "reviewDecision": "", "updatedAt": "2026-11-01T00:00:00Z",
                       "additions": 3, "deletions": 1, "part_of": "hub#40", **kw}
    issue = lambda **kw: {"repo": "boot", "number": 2, "title": "t", "state": "OPEN", "labels": [{"name": "bug"}], "author": {"login": "a"},
                          "comments": 0, "updatedAt": "2026-11-01T00:00:00Z", **kw}
    run = lambda **kw: {"repo": "boot", "databaseId": 3, "workflowName": "CI", "displayTitle": "t", "status": "completed", "conclusion": "success",
                        "event": "push", "headBranch": "main", "headSha": "abc", "createdAt": "2026-11-01T00:00:00Z", "updatedAt": "2026-11-01T00:01:05Z", **kw}
    cases = [("prs", pr(checks="failing"), False, "Needs you", "fix"), ("prs", pr(reviewDecision="CHANGES_REQUESTED", checks="pending"), False, "Needs you", "address"),
             ("prs", pr(checks="pending", headRefName="agent/x"), False, "From agent sessions", "review"),
             ("prs", pr(checks="pending"), True, "From agent sessions", "review"), ("prs", pr(checks="none"), False, "Everything else", "review"),
             ("issues", issue(labels=[]), False, "Untriaged", "triage"), ("issues", issue(), True, "In sessions", "implement"),
             ("issues", issue(), False, "Backlog", "implement"),
             ("actions", run(conclusion="failure"), False, "Failed", "fix"), ("actions", run(status="in_progress", conclusion=None), False, "Running", None),
             ("actions", run(), False, "Recent", "investigate")]
    offered = {"prs": [{"id": "pr-review", "verb": "review"}, {"id": "pr-fix-checks", "verb": "fix", "when": "failing"},
                       {"id": "pr-address-review", "verb": "address", "needs": "review"}],
               "issues": [{"id": "issue-triage", "verb": "triage"}, {"id": "issue-implement", "verb": "implement"}],
               "actions": [{"id": "run-diagnose", "verb": "investigate"}, {"id": "run-fix", "verb": "fix", "when": "failing"}]}
    kinds = {"prs": "pr", "issues": "issue", "actions": "run"}
    code = "".join(f"""{{const r = ROWS[{json.dumps(tab)}]({json.dumps(row)}); const s = {"{agent: {waiting: false}}" if in_session else "undefined"};
      const a = r.startable ? bestAction({json.dumps(kinds[tab])}, r.facts, offeredFor({json.dumps(offered[tab])}, r.facts)) : null;
      console.log(JSON.stringify([groupOf({json.dumps(tab)}, r, s), a && a.verb, r.sub]));}}""" for tab, row, in_session, _g, _v in cases)
    out = [json.loads(line) for line in _work_js(code).splitlines()]
    assert [(g, v) for g, v, _ in out] == [(g, v) for *_, g, v in cases]
    assert out[0][2] == "Part of hub#40 · +3 −1 · a · x → main" and out[-1][2] == "push on main · abc · 1m 5s"


def test_work_shows_github_actions_for_work_and_the_queue():
    """006 FR-008, FR-034, FR-009: the black button offers the two forms; the queue stays a Work view."""
    script = _app_js()
    entries = _component(script, "ghEntries")
    assert '{ id: "new-issue", label: "New issue…", panel: "new"' in entries and '{ id: "dispatch", label: "Run workflow…", panel: "dispatch"' in entries
    lists = _component(script, "WorkLists")
    assert '<${GhActions} kind="work"' in lists and "allowAll onChange=${chooseRepo}" in lists and "writeWorkRepo(name)" in lists
    assert 'query.tab === "queue" ? html`<${WorkQueue} />`' in _component(script, "Work")
    assert 'launch({ action: "new-issue", repos: [repo], describe: text' in _component(script, "NewIssue")
    assert "No workflow of ${repo} can be started by hand" in _component(script, "Dispatch")


# --- Overview (007/PR 1) -----------------------------------------------------------------------------------


def _overview_row(name, failing=0, prs=0, last=None):
    return {"name": name, "attention": {"failing_runs": failing, "open_prs": prs, "last_activity": last}}


def test_attention_order_is_failing_then_waiting_then_prs_then_activity():
    """007 FR-004: failing workflows first, then sessions waiting for you, then open PRs, then the newest activity; none last."""
    from hub.github import attention_key
    rows = [_overview_row("quiet"), _overview_row("old", last="2026-01-01T00:00:00Z"), _overview_row("new", last="2026-11-01T00:00:00Z"),
            _overview_row("prs", prs=3), _overview_row("fails", failing=1), _overview_row("fails-more", failing=2, last="2025-01-01T00:00:00Z")]
    waiting = {"old": 1}
    order = [r["name"] for r in sorted(rows, key=lambda r: attention_key(r, waiting.get(r["name"], 0)))]
    assert order == ["fails-more", "fails", "old", "prs", "new", "quiet"]


def _overview_js(fn):
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node isn't installed")
    script = _app_js()
    src = script[script.index("function byAttention"):script.index("// 007 FR-007: one repository")]
    return subprocess.run(["node", "-e", src + fn], capture_output=True, text=True, check=True).stdout


def test_the_page_sorts_like_the_server_and_shows_five_then_the_rest():
    """byAttention in app.js orders as github.attention_key, with the page's waiting sessions; layerRows shows 5, then "Show N more"."""
    from hub.github import attention_key
    rows = [{**_overview_row(f"r{i}", failing=i % 3 == 0, prs=i % 4, last=f"2026-10-{i + 1:02d}T00:00:00Z"), "waiting": int(i == 7), "description": ""}
            for i in range(12)]
    rows.append({**_overview_row("never"), "waiting": 0, "description": "the boot loader"})
    out = json.loads(_overview_js(f"""const rows = {json.dumps(rows)};
      const a = layerRows(rows), all = layerRows(rows, {{ all: true }}), only = layerRows(rows, {{ attentionOnly: true }}), boot = layerRows(rows, {{ needle: "boot" }});
      console.log(JSON.stringify({{ shown: a.shown.map((r) => r.name), more: a.more, all: all.shown.length, allMore: all.more,
        order: all.rows.map((r) => r.name), only: only.rows.map((r) => r.name), boot: boot.shown.map((r) => r.name) }}));"""))
    expected = [r["name"] for r in sorted(rows, key=lambda r: attention_key(r, r["waiting"]))]
    assert out["order"] == expected and out["shown"] == expected[:5]
    assert out["more"] == 8 and (out["all"], out["allMore"]) == (13, 0)
    assert sorted(out["only"]) == sorted(r["name"] for r in rows if r["attention"]["failing_runs"] or r["waiting"])
    assert out["boot"] == ["never"], "the filter reads the description too"


def _store_with(repos, items):
    store = WorkStore(":memory:")
    author = {"login": "a"}
    for i in range(items):
        repo = repos[i % len(repos)]
        when = f"2026-10-{i % 28 + 1:02d}T00:00:00Z"
        if i % 2:
            store.upsert({"__typename": "PullRequest", "id": f"P{i}", "number": i + 1, "title": "t", "body": "", "state": "OPEN", "isDraft": False, "url": "u",
                          "createdAt": when, "updatedAt": when, "headRefName": "x", "baseRefName": "main", "headRefOid": "a" * 40, "reviewDecision": "",
                          "mergeable": "MERGEABLE", "author": author, "repository": {"name": repo}, "labels": {"nodes": []}, "assignees": {"nodes": []},
                          "comments": {"totalCount": 0, "nodes": []}, "additions": 1, "deletions": 0,
                          "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "FAILURE" if i % 3 == 0 else "SUCCESS"}}}]}})
        else:
            store.upsert({"__typename": "Issue", "id": f"I{i}", "number": i + 1, "title": "t", "body": "", "state": "OPEN", "url": "u", "createdAt": when,
                          "updatedAt": when, "author": author, "repository": {"name": repo}, "labels": {"nodes": []}, "assignees": {"nodes": []},
                          "comments": {"totalCount": 0, "nodes": []}})
    store.put("synced_at", "100.0")
    return store


def _run(repo, run_id, name, conclusion, created, branch="main", status="completed", workflow=None):
    from hub.workstore import run_row
    return run_row(repo, {"id": run_id, "name": name, "status": status, "conclusion": conclusion, "head_branch": branch, "head_sha": "a",
                          "created_at": created, "updated_at": created, "html_url": "u", "event": "push",
                          **({"workflow_id": workflow} if workflow is not None else {})})


def test_the_store_says_activity_failing_workflows_and_failing_prs():
    store = _store_with(["hub", "boot"], 6)
    for row in (_run("hub", 1, "CI", "failure", "2026-10-01T00:00:00Z"), _run("hub", 2, "CI", "success", "2026-10-02T00:00:00Z"),  # CI passes again
                _run("hub", 3, "Docs", "failure", "2026-10-03T00:00:00Z"), _run("hub", 4, "Lint", "failure", "2026-10-04T00:00:00Z", branch="topic"),
                _run("boot", 5, "CI", "timed_out", "2026-10-05T00:00:00Z"), _run("boot", 6, "CI", None, "2026-11-30T00:00:00Z", status="in_progress")):
        store.upsert_run(row)
    assert store.failing_workflows({"hub": "main", "boot": "main", "empty": "main"}) == {"hub": 1, "boot": 1, "empty": 0}, \
        "the newest finished run per workflow, on the default branch only"
    assert store.latest_activity()["boot"] == "2026-11-30T00:00:00Z"
    assert store.open_pr_checks() == {"boot": 1}, "item 3 (boot) is the one failing PR of the six"


def test_a_renamed_workflow_is_the_same_workflow():
    """#41 review: the key is the workflow's id, so the old name's failed run isn't its newest run forever."""
    store = WorkStore(":memory:")
    store.upsert_run(_run("hub", 1, "CI", "failure", "2026-10-01T00:00:00Z", workflow=10))
    store.upsert_run(_run("hub", 2, "Tests", "success", "2026-10-02T00:00:00Z", workflow=10))
    store.upsert_run(_run("hub", 3, "Docs", "failure", "2026-10-03T00:00:00Z", workflow=11))
    assert store.failing_workflows({"hub": "main"}) == {"hub": 1}


def test_a_run_kept_from_before_the_id_goes_by_its_names_id():
    """A row stored before `workflowId` was is the workflow its name has now, so it doesn't stay failing beside it."""
    store = WorkStore(":memory:")
    old = _run("hub", 1, "CI", "failure", "2026-10-01T00:00:00Z")
    old.pop("workflowId")
    store.upsert_run(old)
    store.upsert_run(_run("hub", 2, "CI", "success", "2026-10-02T00:00:00Z", workflow=10))
    assert store.failing_workflows({"hub": "main"}) == {"hub": 0}
    gone = _run("hub", 3, "Gone", "failure", "2026-10-03T00:00:00Z")
    gone.pop("workflowId")
    store.upsert_run(gone)
    assert store.failing_workflows({"hub": "main"}) == {"hub": 1}, "a name with no id-bearing run still counts by its name"


def test_a_cancelled_run_isnt_a_failure_and_a_repo_without_a_default_branch_has_none():
    """#41 review: `cancelled` is not failing, though it is the newest finished run; a null default branch matches no run,
    not the runs with no branch."""
    store = WorkStore(":memory:")
    store.upsert_run(_run("hub", 1, "CI", "failure", "2026-10-01T00:00:00Z", workflow=10))
    store.upsert_run(_run("hub", 2, "CI", "cancelled", "2026-10-02T00:00:00Z", workflow=10))
    store.upsert_run(_run("hub", 3, "Lint", "cancelled", "2026-10-02T00:00:00Z", workflow=12))
    store.upsert_run(_run("empty", 4, "CI", "failure", "2026-10-01T00:00:00Z", branch=None, workflow=20))
    assert store.failing_workflows({"hub": "main", "empty": None}) == {"hub": 0, "empty": 0}
    assert store.failing_workflows({"empty": None}) == {"empty": 0}, "no default branch at all: nothing to ask the store"


def test_overview_is_served_from_the_store_without_a_gh_call(github, hubd):
    """007 SC: 60 repositories and 500 items, all from the work store: no gh, no GraphQL."""
    names = [f"repo{i:02d}" for i in range(60)]
    hubd.nodes = [node(n, prs=i % 3, state="FAILURE" if i == 59 else "SUCCESS") for i, n in enumerate(names)]
    github.store = _store_with(names, 500)
    asyncio.run(github.overview())  # the first sync keeps the overview in the store
    for i, n in enumerate(names):
        github.store.upsert_run(_run(n, i + 1, "CI", "failure" if n == "repo07" else "success", "2026-10-01T00:00:00Z"))
    fresh = GitHub(hubd, CONFIG, store=github.store)
    fresh.sync = type("Sync", (), {"ready": lambda self: True, "status": lambda self: {"synced_at": 100.0}, "wake": lambda self: None})()
    hubd.commands.clear()
    view = asyncio.run(fresh.overview_page())
    assert hubd.commands == [], "nothing asked of gh"
    rows = [r for g in view["groups"] for r in g["repos"]]
    assert len(rows) == 60 and view["from_store"] is True
    by_name = {r["name"]: r for r in rows}
    assert by_name["repo07"]["attention"]["failing_runs"] == 1, "the store's runs"
    assert by_name["repo59"]["attention"]["failing_runs"] == 1, "a red head counts though the store's run of it passed"
    assert sum(r["attention"]["failing_runs"] for r in rows) == 2
    first = by_name["repo07"]
    assert view["totals"]["failing_prs"] == sum(1 for i in range(500) if i % 2 and i % 3 == 0)
    assert all(r["last_activity"] for r in rows) and first["last_commit"]["oid"] == "a"


def test_overview_before_a_sync_falls_back_to_the_heads_checks(github):
    view = asyncio.run(github.overview_page())
    rows = {r["name"]: r for g in view["groups"] for r in g["repos"]}
    assert rows["boot"]["attention"] == {"failing_runs": 1, "open_prs": 2, "last_activity": None}
    assert view["from_store"] is False and view["totals"]["failing_prs"] is None and rows["hub"]["failing_prs"] is None


def test_overview_page_static_parts():
    """007 FR-001, FR-002, FR-005–FR-008: the Needs you card opens the modal; the stats; filter, switch, collapse; each row's Launch…;
    no button inside a button."""
    script = _app_js()
    card = _component(script, "NeedsYouCard")
    assert "onClick=${() => needsYou()}" in card and "c.by_kind" in card and "c.longest_wait" in card
    overview = _component(script, "Overview")
    for text in ("Running sessions", "Open issues", "Open PRs", "<${KnowledgeStat} />", "Needs attention only", "Collapse all", "Expand all",
                 "Show ${g.more} more", "Unplaced"):
        assert text in overview, text
    card = _component(script, "RepoCard")
    assert 'launch({ repos: [r.name], from: { view: "Overview" } })' in card and "<${Strip}" in card and "SessionChip" in card
    assert card.count("<button") == 2 and '<div class="repo keycap"' in card, "the name and Launch… are two buttons side by side"
    assert "data.chunks" in _component(script, "KnowledgeStat")
