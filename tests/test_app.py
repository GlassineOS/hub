# SPDX-License-Identifier: GPL-2.0-or-later
"""The app against a stand-in for hubd that records what it is asked."""
import asyncio
import json
import re
import socket
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
            return {"ok": True, "user": "u", "gh": True, "tmux": False}
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
    "id": "PRRT_1", "isResolved": False, "isOutdated": True, "path": "a.c", "line": 88,
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
    assert rows == [{"id": "PRRT_1", "resolved": False, "outdated": True, "path": "a.c", "line": 88,
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


def test_the_page_says_only_a_button_and_an_item_to_a_session():
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
    assert client.post("/api/agents/send", json=body, headers=ORIGIN).status_code == 400


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


def test_the_merge_button_sends_the_head_it_showed():
    script = (Path(__file__).resolve().parents[1] / "app" / "hub" / "static" / "app.js").read_text()
    assert "/merge`, { method, head: data.headRefOid })" in script


def _app_js():
    return (Path(__file__).resolve().parents[1] / "app" / "hub" / "static" / "app.js").read_text()


def test_decisions_wait_under_needs_you_and_stand_under_active_without_a_nav_entry():
    """A static check: the page isn't run here. What waits and what stands are both in Sessions, and the Decisions page,
    which keeps the ended ones, is still routed."""
    script = _app_js()
    nav = re.search(r"const NAV = \[(.*?)\];", script)[1]
    assert '"decisions"' not in nav and '"shells", "Sessions"' in nav
    assert "decisions: DecisionsPage" in script, "its links and the ended ones still work"
    assert "decisionsAsked(asks).filter(showsDecision)" in script and "Decisions asked for" in script
    assert 'tab === "active"' in script and "decisionsActive(asks)" in script
    assert script.count("<${DecisionRow} ") >= 3, "the same row, so approving and ending go through the one login-checked path"
    assert "decisionsAsked(asks).length" in script, "a request counts toward the badge"
    for kind in ('["go", "Goes"', '["merge", "Merges"', '["suggest", "Suggestions"', '["perm", "Permissions"', '["ask", "Questions"'):
        assert kind in script


def test_queue_and_notes_are_tabs_and_the_go_is_in_needs_you():
    """A static check: the page isn't run here. Six entries are left, and the old addresses still land somewhere."""
    script = _app_js()
    nav = re.search(r"const NAV = \[(.*?)\];", script)[1]
    assert re.findall(r'\["(\w+)", "', nav) == ["overview", "roadmap", "work", "docs", "shells", "device"]
    assert "queue: QueuePage" not in script and "notes: NotesPage" not in script
    assert '["queue", "Queue"]' in script and 'query.tab === "queue" ? html`<${WorkQueue} />`' in script
    assert 'query.tab === "notes" ? html`<${NotesPage} />`' in script
    assert 'queue: "queue" }[route.path]' in script and 'const notes = route.path === "notes"' in script, "old addresses go to the tabs"
    assert 'queue: "work", notes: "docs"' in script, "the Steward is told Work and Docs for them"
    assert "<${DeviceGoes}" not in script and "<${GoPanel} asks=${asks} />" in script
    device = script[script.index("function DeviceView()"):script.index("const GO_ACTIONS")]
    assert "GoPanel" not in device and "Needs you" in device
    assert 'post("device/holding"' in script and 'post("decisions", { kind: "go"' in script, "the same login-checked routes"


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
