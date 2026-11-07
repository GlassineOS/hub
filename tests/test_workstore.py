# SPDX-License-Identifier: GPL-2.0-or-later
"""The work store, its sync, and views served from it without asking gh."""
import asyncio
import datetime
import json
import sqlite3
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hub.github import BadRequest, GitHub  # noqa: E402
from hub.hubd_client import ALL_REPOS, GhError, Hubd, HubdError  # noqa: E402
from hub.workstore import WorkStore, chunks, normalize, part_of, run_row  # noqa: E402
from hub.worksync import WorkSync  # noqa: E402
from hubd.ghrun import Gh  # noqa: E402
from hubd.ghpolicy import Refused  # noqa: E402

CONFIG = Path(__file__).resolve().parents[1] / "config" / "repos.toml"


def issue(number=1, repo="boot", title="A title", body="Body", updated="2026-11-01T10:00:00Z", state="OPEN",
          labels=(), assignees=(), comments=()):
    return {"__typename": "Issue", "id": f"I{repo}{number}", "number": number, "title": title, "body": body, "state": state,
            "url": f"https://x/{repo}/{number}", "createdAt": "2026-10-01T00:00:00Z", "updatedAt": updated, "author": {"login": "a"},
            "repository": {"name": repo}, "labels": {"nodes": [{"name": n} for n in labels]},
            "assignees": {"nodes": [{"login": n} for n in assignees]},
            "comments": {"totalCount": len(comments), "nodes": list(comments)}}


def pr(number=2, repo="boot", checks="SUCCESS", updated="2026-11-01T10:00:00Z", state="OPEN", oid="abc"):
    return {"__typename": "PullRequest", "id": f"P{repo}{number}", "number": number, "title": "A PR", "body": "PR body", "state": state,
            "isDraft": False, "url": f"https://x/{repo}/pull/{number}", "createdAt": "2026-10-01T00:00:00Z", "updatedAt": updated,
            "headRefName": "agent/x", "baseRefName": "main", "headRefOid": oid, "author": {"login": "a"}, "repository": {"name": repo},
            "labels": {"nodes": []}, "assignees": {"nodes": []}, "comments": {"totalCount": 0, "nodes": []},
            "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": checks} if checks else None}}]}}


def comment(id="C1", body="A comment"):
    return {"id": id, "author": {"login": "b"}, "body": body, "createdAt": "2026-10-02T00:00:00Z", "url": "u"}


def rest_run(id=9, status="completed", conclusion="success", branch="main", updated="2026-11-01T10:00:00Z"):
    return {"id": id, "name": "ci", "display_title": "t", "status": status, "conclusion": conclusion, "event": "push", "head_branch": branch,
            "head_sha": "abc", "created_at": updated, "updated_at": updated, "html_url": "u"}


def overview_node(name):
    return {"name": name, "description": "", "isPrivate": False, "isArchived": False, "url": "u", "pushedAt": None,
            "issues": {"totalCount": 1}, "pullRequests": {"totalCount": 0}, "latestRelease": None,
            "defaultBranchRef": {"name": "main", "target": {"oid": "a", "committedDate": None, "messageHeadline": "m",
                                                            "statusCheckRollup": {"state": "SUCCESS"}, "history": {"totalCount": 3}}}}


class FakeHubd(Hubd):
    """Counts every question: a view served from the store must ask none."""

    def __init__(self):
        super().__init__("/nonexistent")
        self.nodes, self.runs, self.asked, self.pages = [], {}, [], None
        self.etag_seen = []
        self.fail = None
        self.private = set()
        self.rate = None

    async def graphql(self, name, **v):
        self.asked.append((name, v))
        if self.fail:
            raise self.fail
        if name == "org_overview":
            return {"organization": {"repositories": {"nodes": [{**overview_node(n), "isPrivate": n in self.private} for n in ("boot", *sorted(self.private))]}}}
        if name == "org_item":
            match = [n for n in self.nodes if n["number"] == v["number"]]
            return {"repository": {"issueOrPullRequest": match[0] if match else None}}
        assert name == "org_changes"
        nodes = [n for n in self.nodes if v["scope"] != "open-prs" or (n["__typename"] == "PullRequest" and n["state"] == "OPEN")]
        if v.get("since"):
            nodes = [n for n in nodes if n["updatedAt"] >= v["since"]]
        return {"viewer": {"login": "me"}, "rateLimit": {"cost": 1, "remaining": self.rate}, "search": {"issueCount": len(nodes), "nodes": nodes,
                                                      "pageInfo": {"hasNextPage": False, "endCursor": None}}}

    async def gh_conditional(self, path, etag=None):
        self.asked.append(("runs", path))
        self.etag_seen.append(etag)
        repo = path.split("/")[2]
        runs = self.runs.get(repo, [])
        tag = f"e{json.dumps(runs, sort_keys=True).__hash__()}"
        if etag == tag:
            return {"status": 304}
        return {"status": 200, "etag": tag, "body": {"workflow_runs": runs}}

    async def gh(self, *argv, stdin=None, timeout=None):
        self.asked.append(("gh", argv))
        if argv[:2] == ("issue", "view"):
            return json.dumps({"number": 1, "title": "live, all comments", "comments": []})
        if argv[:2] == ("pr", "view"):
            return json.dumps({"number": 2, "title": "live", "state": "OPEN", "statusCheckRollup": [], "updatedAt": "z"})
        if argv[:2] == ("pr", "diff"):
            return "a diff"
        if argv[:2] == ("run", "view") and "--json" in argv:
            return json.dumps({"databaseId": 9, "status": "completed", "conclusion": "success", "updatedAt": "2026-11-01T10:00:00Z", "jobs": [{"name": "j"}]})
        if argv[:2] == ("run", "view"):
            return "a log"
        if argv[:2] == ("workflow", "list"):
            return "[]"
        return "[]"


class FakeModel:
    key = "fake"

    def embed_many(self, texts):
        return np.stack([self.embed_query(t) for t in texts])

    def embed_query(self, text):
        # "meaning": whether the text is about power, whatever the words
        v = np.array([1.0, 0.0]) if any(w in text.lower() for w in ("battery", "drain", "power")) else np.array([0.0, 1.0])
        return v


@pytest.fixture
def hubd():
    return FakeHubd()


@pytest.fixture
def world(hubd):
    store = WorkStore(":memory:")
    github = GitHub(hubd, CONFIG, store=store)
    github.sync = WorkSync(hubd, github, store, clock=lambda: 1_000_000.0)
    return github, store, github.sync


def synced(world):
    asyncio.run(world[2].tick())
    return world


def test_normalize_looks_like_gh():
    kind, row, comments, total = normalize(issue(labels=["x"], assignees=["u"], comments=[comment()]))
    assert kind == "issue" and row["repo"] == "boot" and row["comments"] == 1 and total == 1
    assert row["labels"] == [{"name": "x"}] and row["assignees"] == [{"login": "u"}] and comments[0]["id"] == "C1"
    for state, word in (("SUCCESS", "passing"), ("FAILURE", "failing"), ("PENDING", "pending"), (None, "none")):
        assert normalize(pr(checks=state))[1]["checks"] == word
    assert run_row("boot", rest_run())["databaseId"] == 9


def test_an_item_seen_twice_is_one_row():
    store = WorkStore(":memory:")
    assert store.upsert(issue()) is True
    assert store.upsert(issue()) is False
    assert store.upsert(issue(title="Other", updated="2026-11-02T00:00:00Z")) is True
    assert store.counts()["issue"] == 1
    assert store.item("issue", "boot", 1)["title"] == "Other"


def test_deleted_comments_leave_and_old_ones_stay_past_the_window():
    store = WorkStore(":memory:")
    store.upsert(issue(comments=[comment("C1"), comment("C2")]))
    store.upsert(issue(comments=[comment("C2")]))
    assert [c["id"] for c in store.comments("issue", "boot", 1)] == ["C2"]
    window = issue(comments=[comment("C3")])
    window["comments"]["totalCount"] = 40  # older ones aren't in this answer, so nothing says they're gone
    store.upsert(window)
    assert {c["id"] for c in store.comments("issue", "boot", 1)} == {"C2", "C3"}


def test_views_are_served_from_the_store_without_asking(world, hubd):
    hubd.nodes = [issue(labels=["bug"], assignees=["me"], comments=[comment()]), pr()]
    hubd.runs = {"boot": [rest_run()]}
    github, _, _ = synced(world)
    hubd.asked.clear()

    async def views():
        assert [r["number"] for r in await github.issues()] == [1]
        assert [r["number"] for r in await github.issues("boot", label="bug", assignee="@me")] == [1]
        assert await github.issues(label="other") == []
        assert await github.issues(assignee="none") == []
        assert "body" not in (await github.issues())[0]
        detail = await github.issue("boot", 1)
        assert detail["body"] == "Body" and detail["comments"][0]["body"] == "A comment"
        assert [r["number"] for r in await github.prs()] == [2]
        assert (await github.prs())[0]["checks"] == "passing"
        assert [r["databaseId"] for r in await github.runs("boot", status="success")] == [9]
        assert (await github.run_strips())["boot"] == ["pass"]
        assert (await github.overview())["totals"]["repos"] == 1
    asyncio.run(views())
    assert hubd.asked == []


def test_a_search_with_qualifiers_is_githubs_to_answer(world, hubd):
    github, _, _ = synced(world)
    hubd.asked.clear()
    asyncio.run(github.issues("boot", search="author:someone"))
    assert hubd.asked[0][0] == "gh" and "--search" in hubd.asked[0][1]


def test_issue_with_comments_past_the_window_asks_gh(world, hubd):
    long = issue(comments=[comment()])
    long["comments"]["totalCount"] = 40
    hubd.nodes = [long]
    github, _, _ = synced(world)
    hubd.asked.clear()

    assert asyncio.run(github.issue("boot", 1))["title"] == "live, all comments"
    assert asyncio.run(github.issue("boot", 1))["title"] == "live, all comments"
    assert len(hubd.asked) == 1  # kept until the issue changes
    assert hubd.asked[0][0] == "gh"


def test_kept_answers_go_stale_with_their_item_and_with_ci(world, hubd):
    hubd.nodes = [pr()]
    hubd.runs = {"boot": [rest_run()]}
    github, store, sync = synced(world)
    hubd.asked.clear()

    def live_views():
        return [a for a in hubd.asked if a[0] == "gh" and a[1][:2] == ("pr", "view") and "mergeable,mergeStateStatus,headRefOid" not in a[1]]

    asyncio.run(github.pr("boot", 2))
    asyncio.run(github.pr("boot", 2))
    assert len(live_views()) == 1
    # CI changed: the same pull request's checks have to be asked for again
    hubd.runs = {"boot": [rest_run(id=10), rest_run()]}
    sync._clock = lambda: 1_000_100.0
    asyncio.run(sync.tick())
    asyncio.run(github.pr("boot", 2))
    assert len(live_views()) == 2
    # and so does a change to the pull request
    hubd.nodes = [pr(updated="2026-11-01T11:00:00Z")]
    asyncio.run(sync.tick())
    asyncio.run(github.pr("boot", 2))
    assert len(live_views()) == 3


def test_diff_finished_run_and_log_are_kept(world, hubd):
    hubd.nodes = [pr()]
    hubd.runs = {"boot": [rest_run()]}
    github, _, _ = synced(world)
    hubd.asked.clear()

    async def twice():
        for _ in range(2):
            assert await github.pr_diff("boot", 2) == "a diff"
            assert (await github.run("boot", 9))["jobs"]
            assert await github.run_log("boot", 9) == "a log"
    asyncio.run(twice())
    assert len(hubd.asked) == 3


def test_unchanged_runs_cost_a_304_and_no_pr_refresh(world, hubd):
    hubd.runs = {"boot": [rest_run()]}
    _, _, sync = synced(world)
    hubd.asked.clear()
    assert asyncio.run(sync.tick())["runs"] == 0
    assert hubd.etag_seen[-1] is not None
    assert not [a for a in hubd.asked if a[0] == "org_changes" and a[1]["scope"] == "open-prs"]


def test_new_runs_refresh_open_prs(world, hubd):
    hubd.nodes = [pr(checks="PENDING")]
    github, store, sync = synced(world)
    hubd.nodes = [pr(checks="SUCCESS")]  # same updatedAt: only the check moved
    hubd.runs = {"boot": [rest_run()]}
    hubd.asked.clear()
    assert asyncio.run(sync.tick())["runs"] == 1
    assert [a for a in hubd.asked if a[0] == "org_changes" and a[1]["scope"] == "open-prs"]
    assert store.item("pr", "boot", 2)["checks"] == "passing"


def test_later_ticks_ask_from_the_cursor_with_an_overlap(world, hubd):
    hubd.nodes = [issue(updated="2026-11-01T10:00:00Z")]
    _, _, sync = synced(world)
    hubd.asked.clear()
    asyncio.run(sync.tick())
    since = [a[1]["since"] for a in hubd.asked if a[0] == "org_changes"][0]
    assert since == "2026-11-01T09:55:00Z"


def test_only_a_complete_pass_removes_what_is_gone(world, hubd):
    hubd.nodes = [issue(1), issue(3)]
    _, store, sync = synced(world)
    hubd.nodes = [issue(3)]
    asyncio.run(sync.tick())  # an incremental tick can't tell
    assert store.counts()["issue"] == 2
    sync._clock = lambda: 1_000_000.0 + 7 * 3600
    asyncio.run(sync.tick())
    assert store.counts()["issue"] == 1 and store.item("issue", "boot", 1) is None


def test_a_failed_tick_keeps_serving_and_says_so(world, hubd):
    hubd.nodes = [issue()]
    github, _, sync = synced(world)
    hubd.fail = GhError("rate limited")
    with pytest.raises(GhError):
        asyncio.run(sync.tick())
    assert sync.status()["error"] == "rate limited"
    assert sync.status()["ready"] is True
    assert [r["number"] for r in asyncio.run(github.issues())] == [1]
    hubd.fail = None
    asyncio.run(sync.tick())
    assert sync.status()["error"] is None


def test_before_the_first_sync_views_ask_gh(world, hubd):
    github, _, _ = world
    asyncio.run(github.issues("boot"))
    assert hubd.asked[0][0] == "gh"


def test_a_write_shows_at_once(world, hubd):
    hubd.nodes = [issue(state="OPEN")]
    github, store, sync = synced(world)
    hubd.nodes = [issue(state="CLOSED", updated="2026-11-01T12:00:00Z")]

    async def go():
        await github.close_issue("boot", 1)
        return await github.issues("boot", state="closed")
    assert [r["number"] for r in asyncio.run(go())] == [1]


def test_bad_repo_is_refused_on_the_store_path_too(world, hubd):
    github, _, _ = synced(world)
    for call in (github.issues("../x"), github.prs("a b"), github.runs("../x")):
        with pytest.raises(BadRequest):
            asyncio.run(call)


def test_chunks_cover_the_text_and_overlap():
    assert chunks("") == []
    assert chunks("short") == ["short"]
    text = " ".join(f"word{i}" for i in range(1000))
    pieces = chunks(text)
    assert all(len(p) <= 1000 for p in pieces) and len(pieces) > 3
    for i in (0, 500, 999):
        assert any(f"word{i}" in p for p in pieces)


def test_search_by_meaning_finds_what_the_words_dont():
    store = WorkStore(":memory:")
    store.upsert(issue(1, title="Battery drain overnight", body="It loses charge."))
    store.upsert(issue(2, title="Typo in the docs", body="Spelling."))
    model = FakeModel()
    pending = store.unembedded(model.key)
    assert len(pending) == 2
    store.add_vectors(model.key, [d for d, _ in pending], model.embed_many([t for _, t in pending]))
    assert store.unembedded(model.key) == []
    hits = store.search("power use", model.embed_query("power use"), model.key)
    assert hits[0]["number"] == 1 and hits[0]["meaning"] == 1.0 and hits[0]["words"] == 0
    assert "body" not in hits[0]["row"]


def test_search_groups_by_item_filters_and_works_on_words_alone():
    store = WorkStore(":memory:")
    store.upsert(issue(1, title="Resume hangs", comments=[comment("C1", "resume again"), comment("C2", "resume once more")]))
    store.upsert(issue(2, title="Resume docs", state="CLOSED", repo="docs"))
    hits = store.search("resume")
    assert sorted((h["repo"], h["number"]) for h in hits) == [("boot", 1), ("docs", 2)]
    assert hits[0]["meaning"] is None
    assert [h["number"] for h in store.search("resume", repo="docs")] == [2]
    assert [h["number"] for h in store.search("resume", state="open")] == [1]
    assert store.search("resume", kind="pr") == []
    assert store.search("nothing matches this") == []


def test_only_changed_text_needs_embedding_again():
    store = WorkStore(":memory:")
    store.upsert(issue(1, body="Same"))
    model = FakeModel()
    pending = store.unembedded(model.key)
    store.add_vectors(model.key, [d for d, _ in pending], model.embed_many([t for _, t in pending]))
    store.upsert(issue(1, body="Same", updated="2026-11-02T00:00:00Z"))
    assert store.unembedded(model.key) == []
    store.upsert(issue(1, body="Different", updated="2026-11-03T00:00:00Z"))
    assert len(store.unembedded(model.key)) == 1


def test_sync_embeds_and_github_searches(hubd):
    hubd.nodes = [issue(1, title="Battery drain")]
    store = WorkStore(":memory:")
    github = GitHub(hubd, CONFIG, store=store)
    github.sync = WorkSync(hubd, github, store, load_embedder=FakeModel)

    async def go():
        with pytest.raises(BadRequest):
            await github.work_search("x")  # not ready yet
        await github.sync.tick()
        await github.sync._embedding
        with pytest.raises(BadRequest):
            await github.work_search("  ")
        with pytest.raises(BadRequest):
            await github.work_search("x", kind="run")
        return await github.work_search("power")
    result = asyncio.run(go())
    assert result["by_meaning"] is True and result["semantic"] == "ready" and result["results"][0]["number"] == 1


def test_no_model_means_words_and_says_so(hubd):
    hubd.nodes = [issue(1, title="Battery drain")]
    store = WorkStore(":memory:")
    github = GitHub(hubd, CONFIG, store=store)

    def broken():
        raise OSError("no network")
    github.sync = WorkSync(hubd, github, store, load_embedder=broken)

    async def go():
        await github.sync.tick()
        await github.sync._embedding
        return await github.work_search("battery")
    result = asyncio.run(go())
    assert result["by_meaning"] is False and result["semantic"].startswith("unavailable")
    assert result["results"][0]["number"] == 1


def test_store_survives_a_restart(tmp_path, hubd):
    path = tmp_path / "work" / "work.sqlite"
    hubd.nodes = [issue()]
    store = WorkStore(path)
    github = GitHub(hubd, CONFIG, store=store)
    github.sync = WorkSync(hubd, github, store)
    asyncio.run(github.sync.tick())
    hubd.asked.clear()
    store = WorkStore(path)
    github = GitHub(hubd, CONFIG, store=store)
    github.sync = WorkSync(hubd, github, store)
    assert [r["number"] for r in asyncio.run(github.issues())] == [1]
    assert asyncio.run(github.overview())["totals"]["repos"] == 1
    assert hubd.asked == []


def test_gh_conditional_parses_both_answers():
    class Reply(Hubd):
        def __init__(self, reply):
            super().__init__("/nonexistent")
            self.reply = reply

        async def call(self, **request):
            self.request = request
            return self.reply
    done = Reply({"code": 1, "stdout": "HTTP/2.0 304 Not Modified\r\nX: y\r\n\r\n", "stderr": "gh: HTTP 304"})
    assert asyncio.run(done.gh_conditional("p", 'W/"a"')) == {"status": 304}
    assert done.request["argv"] == ["api", "--include", "-H", 'If-None-Match: W/"a"', "p"]
    fresh = Reply({"code": 0, "stdout": 'HTTP/2.0 200 OK\nEtag: W/"b"\n\n{"workflow_runs": []}', "stderr": ""})
    assert asyncio.run(fresh.gh_conditional("p")) == {"status": 200, "etag": 'W/"b"', "body": {"workflow_runs": []}}
    with pytest.raises(GhError):
        asyncio.run(Reply({"code": 1, "stdout": "HTTP/2.0 404 Not Found\n\n{}", "stderr": "nope"}).gh_conditional("p"))
    with pytest.raises(GhError):
        asyncio.run(Reply({"code": 1, "stdout": "", "stderr": "no network"}).gh_conditional("p"))


def test_hubd_builds_the_search_and_refuses_the_apps_own():
    gh = Gh(program="false")
    bodies = []

    async def capture(document, variables, token=None):
        bodies.append((document, variables))
        return {"code": 0, "stdout": "{}", "stderr": ""}
    gh._document = capture

    async def go():
        await gh.graphql("org_changes", {"scope": "changed", "since": "2026-11-01T10:00:00Z", "cursor": None})
        with pytest.raises(Refused):
            await gh.graphql("org_changes", {"scope": "changed", "query": "org:other"})
        with pytest.raises(Refused):
            await gh.graphql("org_overview", {"query": "x"})
        with pytest.raises(Refused):
            await gh.graphql("org_changes", {"scope": "changed", "since": "2026 org:other"})
    asyncio.run(go())
    document, variables = bodies[0]
    assert variables["query"] == "org:GlassineOS updated:>=2026-11-01T10:00:00Z archived:false sort:updated-asc"
    assert variables["org"] == "GlassineOS" and "scope" not in variables and "since" not in variables
    assert "fragment IssueFields" in document and "fragment PrFields" in document
    assert "fragment" not in gh.documents["org_overview"]


# --- what the review of this store found ----------------------------------------------------
def test_runs_by_file_name_ask_gh_and_by_name_the_store(world, hubd):
    hubd.runs = {"boot": [rest_run()]}
    github, _, _ = synced(world)
    hubd.asked.clear()
    assert [r["databaseId"] for r in asyncio.run(github.runs("boot", workflow="ci"))] == [9]
    assert hubd.asked == []
    asyncio.run(github.runs("boot", workflow="ci.yml"))
    assert any(a[0] == "gh" and "--workflow" in a[1] and "ci.yml" in a[1] for a in hubd.asked)


def test_docs_status_sees_a_build_with_the_store_serving(world, hubd):
    from hub.docsearch import WORKFLOW
    assert WORKFLOW.endswith((".yml", ".yaml"))  # or the store would answer, by a name it doesn't keep


def test_retargeting_a_pull_request_drops_its_kept_diff(world, hubd):
    hubd.nodes = [pr()]
    github, _, sync = synced(world)
    asyncio.run(github.pr_diff("boot", 2))
    hubd.nodes = [{**pr(updated="2026-11-01T11:00:00Z"), "baseRefName": "other"}]
    asyncio.run(sync.tick())
    hubd.asked.clear()
    asyncio.run(github.pr_diff("boot", 2))
    assert any(a[1][:2] == ("pr", "diff") for a in hubd.asked)


def test_a_kept_open_pull_request_gets_its_merge_state_fresh(world, hubd):
    hubd.nodes = [pr()]
    github, _, _ = synced(world)
    asyncio.run(github.pr("boot", 2))
    hubd.asked.clear()
    asyncio.run(github.pr("boot", 2))
    assert [a[1][-1] for a in hubd.asked] == ["mergeable,mergeStateStatus,headRefOid"]  # a merge has to name the head


def test_a_rerun_refreshes_past_the_kept_answer(world, hubd):
    hubd.runs = {"boot": [rest_run()]}
    github, _, _ = synced(world)
    asyncio.run(github.run("boot", 9))
    hubd.asked.clear()
    asyncio.run(github.rerun("boot", 9))
    assert any(a[0] == "gh" and a[1][:2] == ("run", "view") for a in hubd.asked)


def test_a_failed_refresh_of_open_prs_is_still_owed(world, hubd):
    hubd.nodes = [pr()]
    _, store, sync = synced(world)
    hubd.runs = {"boot": [rest_run()]}
    real = hubd.graphql

    async def fails_on_open_prs(name, **v):
        if v.get("scope") == "open-prs":
            raise HubdError("no")
        return await real(name, **v)
    hubd.graphql = fails_on_open_prs
    with pytest.raises(HubdError):
        asyncio.run(sync.tick())
    assert store.get("open_prs_owed")
    hubd.graphql = real
    hubd.asked.clear()
    asyncio.run(sync.tick())  # the runs answer 304 now
    assert any(a[0] == "org_changes" and a[1]["scope"] == "open-prs" for a in hubd.asked)
    assert not store.get("open_prs_owed")


def test_a_much_smaller_complete_pass_removes_nothing(world, hubd):
    hubd.nodes = [issue(n) for n in range(1, 5)]
    _, store, sync = synced(world)
    hubd.nodes = []
    sync._clock = lambda: 1_000_000.0 + 7 * 3600
    asyncio.run(sync.tick())
    assert store.counts()["issue"] == 4 and "kept them" in sync.status()["warning"]


def test_removing_an_item_removes_its_kept_answers(world, hubd):
    hubd.nodes = [pr(), issue(3), issue(4)]
    github, store, sync = synced(world)
    asyncio.run(github.pr_diff("boot", 2))
    stamp = "abc/main"
    assert store.answer("diff/boot/2", stamp) == "a diff"
    hubd.nodes = [issue(3), issue(4)]
    sync._clock = lambda: 1_000_000.0 + 7 * 3600
    asyncio.run(sync.tick())
    assert store.answer("diff/boot/2", stamp) is None


def test_prune_drops_old_answers_and_runs():
    store = WorkStore(":memory:")
    store.upsert_run(run_row("boot", rest_run(id=1, updated="2020-01-01T00:00:00Z")))
    store.upsert_run(run_row("boot", rest_run(id=2, updated="2026-11-01T00:00:00Z")))
    store.keep("log/boot/1", "s", "text")
    now = datetime.datetime(2026, 11, 2, tzinfo=datetime.timezone.utc).timestamp()
    store.prune(now)
    assert [r["databaseId"] for r in store.runs("boot")] == [2]
    assert store.answer("log/boot/1", "s") == "text"  # kept just now, by the wall clock
    store.prune(time.time() + 31 * 86400)
    assert store.answer("log/boot/1", "s") is None


def test_an_older_file_is_dropped_not_misread(tmp_path):
    path = tmp_path / "work.sqlite"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE answers (key TEXT PRIMARY KEY, stamp TEXT, value TEXT NOT NULL)")
    db.execute("INSERT INTO answers VALUES ('a', 's', '1')")
    db.commit()
    db.close()
    store = WorkStore(path)
    assert store.answer("a", "s") is None
    store.keep("a", "s", 2)
    assert WorkStore(path).answer("a", "s") == 2


def test_agents_search_public_repositories_unless_they_name_one(hubd):
    hubd.private = {"secret"}
    hubd.nodes = [issue(1, title="Battery drain"), issue(2, repo="secret", title="Battery secret")]
    store = WorkStore(":memory:")
    github = GitHub(hubd, CONFIG, store=store)
    github.sync = WorkSync(hubd, github, store)

    async def go():
        await github.sync.tick()
        return [[r["repo"] for r in (await github.work_search("battery", **kw))["results"]]
                for kw in ({}, {"for_agent": True}, {"for_agent": True, "repo": "secret"})]
    you, agent, named = asyncio.run(go())
    assert sorted(you) == ["boot", "secret"] and agent == ["boot"] and named == ["secret"]


def test_short_words_count_as_whole_words():
    store = WorkStore(":memory:")
    store.upsert(issue(1, title="CI is red"))
    store.upsert(issue(2, title="Special case"))
    assert [r["number"] for r in store.search("CI")] == [1]


def test_a_long_thread_keeps_its_newest_comments():
    store = WorkStore(":memory:")
    said = [{**comment(f"C{n}", f"comment number {n}"), "createdAt": f"2026-10-{n % 28 + 1:02d}T{n % 24:02d}:{n % 60:02d}:00Z"}
            for n in range(100)]
    node = issue(1, body="the body", comments=said)
    store.upsert(node)
    newest = max(said, key=lambda c: c["createdAt"])
    assert store.search("the body")
    assert store.search(newest["body"])[0]["passage"].endswith(newest["body"])


def test_interval_is_checked():
    from hub.worksync import DEFAULT_INTERVAL, MIN_INTERVAL, interval_from
    assert interval_from(None) == DEFAULT_INTERVAL and interval_from("120") == 120
    for bad in ("soon", "nan", "inf"):
        assert interval_from(bad) == DEFAULT_INTERVAL
    for small in ("0", "-5", "1"):
        assert interval_from(small) == MIN_INTERVAL


def test_a_low_rate_budget_slows_the_ticks(world, hubd):
    from hub.worksync import INTERVAL, SLOW_FACTOR
    hubd.rate = 100
    _, _, sync = synced(world)
    assert sync.next_wait() == INTERVAL * SLOW_FACTOR
    hubd.rate = 4000
    asyncio.run(sync.tick())
    assert sync.next_wait() == INTERVAL


def test_sync_now_joins_instead_of_queueing(world, hubd):
    github, _, sync = synced(world)
    hubd.asked.clear()
    asyncio.run(github.work_sync_now())  # one just ran
    assert hubd.asked == []
    sync._clock = lambda: 1_000_100.0
    asyncio.run(github.work_sync_now())
    assert hubd.asked


def test_a_strange_answer_shows_as_an_error(world, hubd):
    _, _, sync = world
    async def odd(name, **v):
        return {"no": "shape"}
    hubd.graphql = odd
    with pytest.raises(KeyError):
        asyncio.run(sync.tick())
    assert "KeyError" in sync.status()["error"]


def test_failed_runs_of_a_repository_are_reported(world, hubd):
    _, _, sync = world
    async def refused(path, etag=None):
        raise HubdError("nope")
    hubd.gh_conditional = refused
    asyncio.run(sync.tick())
    assert sync.status()["run_errors"] == {"boot": "nope"}


def _semantic(hubd, load):
    hubd.nodes = [issue(1, title="Battery drain")]
    store = WorkStore(":memory:")
    github = GitHub(hubd, CONFIG, store=store)
    github.sync = WorkSync(hubd, github, store, load_embedder=load)
    return github, store


def test_search_doesnt_wait_for_the_model_and_says_words(hubd):
    release = threading.Event()

    def slow():
        release.wait(5)
        return FakeModel()
    github, _ = _semantic(hubd, slow)

    async def go():
        await github.sync.tick()
        result = await asyncio.wait_for(github.work_search("battery"), 1)
        release.set()
        await github.sync._embedding
        return result, await github.work_search("battery")
    during, after = asyncio.run(go())
    assert during["by_meaning"] is False and during["results"][0]["number"] == 1
    assert after["by_meaning"] is True and after["semantic"] == "ready"


def test_a_failed_load_waits_before_it_tries_again(hubd):
    tries = []

    def broken():
        tries.append(1)
        raise OSError("no network")
    github, _ = _semantic(hubd, broken)
    now = [1_000_000.0]
    github.sync._clock = lambda: now[0]

    async def go():
        await github.sync.embed_pending()
        await github.sync.embed_pending()
        assert len(tries) == 1
        now[0] += 601
        await github.sync.embed_pending()
    asyncio.run(go())
    assert len(tries) == 2


def test_a_load_that_exits_leaves_the_app_serving(hubd):
    """The docs client raises SystemExit if onnxruntime is missing."""
    hubd.nodes = [issue(1, title="Battery drain")]
    store = WorkStore(":memory:")
    github = GitHub(hubd, CONFIG, store=store)

    def exits():
        raise SystemExit("the transformer profile needs onnxruntime")
    github.sync = WorkSync(hubd, github, store, load_embedder=exits)

    async def go():
        await github.sync.tick()
        await github.sync._embedding
        return await github.work_search("battery")
    result = asyncio.run(go())
    assert result["semantic"].startswith("unavailable") and "onnxruntime" in result["semantic"]
    assert result["results"][0]["number"] == 1


def test_embedding_failure_is_reported_not_ready(hubd):
    class Fails(FakeModel):
        def embed_many(self, texts):
            raise RuntimeError("out of memory")
    github, _ = _semantic(hubd, Fails)

    async def go():
        await github.sync.tick()
        await github.sync._embedding
        return await github.work_search("battery")
    result = asyncio.run(go())
    assert result["semantic"].startswith("failed") and result["by_meaning"] is False
    assert result["results"][0]["number"] == 1


def test_partial_embedding_isnt_called_by_meaning(hubd):
    github, store = _semantic(hubd, FakeModel)

    async def go():
        await github.sync.tick()
        await github.sync._embedding
        store.upsert(issue(5, title="Something new"))
        github.sync._embed_soon = lambda: None  # or it can catch up while the query is embedded
        return await github.work_search("battery")
    assert asyncio.run(go())["by_meaning"] is False


def _listing(hubd, rows):
    hubd.private = {"secret"}
    hubd.nodes = rows
    store = WorkStore(":memory:")
    github = GitHub(hubd, CONFIG, store=store)
    github.sync = WorkSync(hubd, github, store)
    asyncio.run(github.sync.tick())
    return github


def test_agents_list_issues_of_public_repositories_unless_they_name_one(hubd):
    github = _listing(hubd, [issue(1), issue(2, repo="secret")])

    async def go():
        return await github.issues(), await github.agent_issues(), await github.agent_issues("secret")
    you, agent, named = asyncio.run(go())
    assert {r["repo"] for r in you} == {"boot", "secret"}
    assert {r["repo"] for r in agent} == {"boot"} and {r["repo"] for r in named} == {"secret"}


def test_agents_list_prs_of_public_repositories_unless_they_name_one(hubd):
    github = _listing(hubd, [pr(1), pr(2, repo="secret")])

    async def go():
        return await github.prs(), await github.agent_prs(), await github.agent_prs("secret")
    you, agent, named = asyncio.run(go())
    assert {r["repo"] for r in you} == {"boot", "secret"}
    assert {r["repo"] for r in agent} == {"boot"} and {r["repo"] for r in named} == {"secret"}


def test_private_rows_dont_use_up_an_agents_limit(hubd):
    github = _listing(hubd, [issue(1, updated="2026-01-01T00:00:00Z"),
                             issue(2, repo="secret", updated="2026-06-01T00:00:00Z"),
                             issue(3, updated="2026-02-01T00:00:00Z")])
    agent = asyncio.run(github.agent_issues(limit=1))
    assert [(r["repo"], r["number"]) for r in agent] == [("boot", 3)]


def test_a_whole_project_listing_keeps_its_limit_and_says_whats_private(hubd):
    github = _listing(hubd, [issue(1, updated="2026-01-01T00:00:00Z"),
                             issue(2, repo="secret", updated="2026-06-01T00:00:00Z"),
                             issue(3, updated="2026-02-01T00:00:00Z")])

    async def go():
        ALL_REPOS.set(True)
        return await github.agent_issues(limit=2)
    rows = asyncio.run(go())
    assert [(r["repo"], r["number"], r["private"]) for r in rows] == [("secret", 2, True), ("boot", 3, False)]


def test_whole_project_runs_keep_their_limit_and_say_whats_private(hubd):
    hubd.private = {"secret"}
    hubd.runs = {"boot": [rest_run(id=1)], "secret": [rest_run(id=2)]}
    store = WorkStore(":memory:")
    github = GitHub(hubd, CONFIG, store=store)
    github.sync = WorkSync(hubd, github, store)

    async def go():
        await github.sync.tick()
        ALL_REPOS.set(True)
        return await github.agent_runs(), await github.agent_runs(limit=1)
    every, one = asyncio.run(go())
    assert {(r["repo"], r["private"]) for r in every} == {("boot", False), ("secret", True)} and len(one) == 1


def test_a_whole_project_search_finds_private_repositories_and_says_so(hubd):
    hubd.private = {"secret"}
    hubd.nodes = [issue(1, title="Battery drain"), issue(2, repo="secret", title="Battery secret")]
    store = WorkStore(":memory:")
    github = GitHub(hubd, CONFIG, store=store)
    github.sync = WorkSync(hubd, github, store)

    async def go():
        await github.sync.tick()
        ALL_REPOS.set(True)
        return (await github.work_search("battery", for_agent=True))["results"]
    assert sorted((r["repo"], r["private"]) for r in asyncio.run(go())) == [("boot", False), ("secret", True)]


def test_agents_list_runs_of_public_repositories_unless_they_name_one(hubd):
    hubd.private = {"secret"}
    hubd.runs = {"boot": [rest_run(id=1)], "secret": [rest_run(id=2)]}
    store = WorkStore(":memory:")
    github = GitHub(hubd, CONFIG, store=store)
    github.sync = WorkSync(hubd, github, store)

    async def go():
        await github.sync.tick()
        return await github.runs(), await github.agent_runs(), await github.agent_runs("secret")
    you, agent, named = asyncio.run(go())
    assert {r["repo"] for r in you} == {"boot", "secret"}
    assert {r["repo"] for r in agent} == {"boot"} and {r["repo"] for r in named} == {"secret"}



@pytest.mark.parametrize("body, repo, found", [
    ("Part of GlassineOS/hub#40\n\nText", "boot", "hub#40"),
    ("Some text first.\n\nPart of hub#40 and more", "boot", "hub#40"),
    ("Part of #12", "boot", "boot#12"),
    ("Part of https://github.com/GlassineOS/kernel/issues/7", "boot", "kernel#7"),
    ("> Part of hub#40", "boot", None),
    ("This is part of hub#40", "boot", None),
    ("Part of the roadmap", "boot", None),
    (None, "boot", None),
])
def test_part_of_reads_the_line_the_filing_writes(body, repo, found):
    """006 FR-006: the row's "Part of"; 007 counts the same line."""
    assert part_of(body, repo) == found


def test_a_listed_row_has_its_part_of_but_not_its_body(tmp_path):
    store = WorkStore(tmp_path / "w.sqlite")
    store.upsert(issue(number=1, body="Part of GlassineOS/hub#40\n\nThe rest."))
    store.upsert(issue(number=2, body="Nothing"))
    rows = {r["number"]: r for r in store.issues("boot")}
    assert rows[1]["part_of"] == "hub#40" and rows[2]["part_of"] is None and "body" not in rows[1]


def test_the_workflow_list_isnt_kept_while_a_file_couldnt_be_read(world, hubd, monkeypatch):
    """A read GitHub failed just now is tried again at the next look; a settled list is kept for the hour."""
    import base64
    github, _, _ = synced(world)
    good = base64.b64encode(b"on: workflow_dispatch").decode()
    answers = {"fail": True}
    reads = []

    async def gh(*argv, stdin=None, timeout=None):
        if argv[:2] == ("workflow", "list"):
            return json.dumps([{"id": 1, "name": "CI", "path": ".github/workflows/ci.yml", "state": "active"}])
        reads.append(argv)
        if answers["fail"]:
            raise GhError("HTTP 502")
        return json.dumps({"encoding": "base64", "content": good})
    monkeypatch.setattr(hubd, "gh", gh)
    first = asyncio.run(github.workflows("boot"))
    assert first[0]["dispatchable"] is None and "couldn't read ci.yml" in first[0]["inputs_error"]
    answers["fail"] = False
    assert asyncio.run(github.workflows("boot"))[0]["dispatchable"] is True  # not the failed read, kept
    count = len(reads)
    answers["fail"] = True
    assert asyncio.run(github.workflows("boot"))[0]["dispatchable"] is True and len(reads) == count  # the good one is kept
