# SPDX-License-Identifier: GPL-2.0-or-later
"""What wakes the Steward (012 FR-056 to FR-058): events about its own work, batched and marked as data; never a timer or a
count. The rest of the feed waits for changes_since, by item, by repository or as a digest; my_suggestions says what
still waits for the person."""
import asyncio
import itertools
import json
import types

import pytest

pytest.importorskip("starlette")
from hubd import results  # noqa: E402
from hubd.feed import Feed, FeedError  # noqa: E402
from hubd.managed import Managed  # noqa: E402
from hubd.newwork import NewWork  # noqa: E402
from hubd.server import Hubd  # noqa: E402
from hubd.stewardwake import MAX_PENDING, StewardEvents, feed_phrase, refs_in  # noqa: E402
from test_newwork import FakeAgents, FakeShells, approved, call  # noqa: E402

_ids = itertools.count(1)


def ev(**over):
    return {"id": f"{'d' * 16}-{next(_ids)}", "kind": "pr", "repo": "boot", "number": 2, "what": "state", "at": "2026-11-05T15:02:00Z",
            "old": "OPEN", "new": "MERGED", "old_head": "", "new_head": "", "actor": "alice", **over}


def comment(**over):
    return ev(what="comments", old="", new="", **over)


class StewardAgents(FakeAgents):
    """The new-work fakes, and what the Steward's events ask of the sessions."""

    def __init__(self):
        super().__init__()
        del self.started  # a list in the new-work fakes; here it is what Agents.started() answers
        self.configs = []
        self.sent, self.refuse, self.all_repos = [], None, True
        self.rows, self.by, self.owners = [], {}, {}
        self.running = True

    async def stewards(self):
        return [{"name": "steward", "all_repos": self.all_repos}] if self.running else []

    async def hub_events(self, name, text):
        if self.refuse:
            raise RuntimeError(self.refuse)
        self.sent.append((name, text))
        return {"sent": True, "queued": 0}

    async def started(self):
        return self.rows

    async def start(self, config, started_by=None, origin=None):
        self.configs.append((config, started_by))
        return {"name": "new-issue-boot"}

    def started_by(self, name):
        return self.by.get(name)

    def owner_record(self, name):
        return self.owners.get(name)

    async def spawn(self, action, repo, number, by):
        self.by[f"{action}-{repo}-{number}"] = by
        return {"name": f"{action}-{repo}-{number}"}

    def describe(self, name):
        return None


@pytest.fixture
def hub(tmp_path):
    h = Hubd(None, FakeShells(), None, "general", agents=StewardAgents(), work=NewWork(tmp_path / "w"), change_feed=Feed(":memory:"),
             result_store=results.Results(tmp_path / "r"), steward_file=tmp_path / "steward-events.json")
    h.sessions = type("S", (), {"check": staticmethod(lambda t: t == "login"), "own_user": staticmethod(lambda: "you")})()
    h.agents.scopes["steward-token"]["tools"] = (*h.agents.scopes["steward-token"]["tools"], "spawn_session", "list_sessions")
    h.steward_events.quiet = 3600  # the tests send a batch themselves
    return h


def run(coro):
    return asyncio.run(coro)


def suggest(hub, **kw):
    reply = call(hub, "work.suggest", agent_token="steward-token", **{"action": "issue-docs", "repo": "epd", "number": 9,
                                                                      "why": "Both reach the daemon.", **kw})
    assert reply["ok"], reply
    return reply["id"]


def batch(hub) -> list[str]:
    """Sends what waits, and gives the lines of the one turn it made, or [] when nothing went."""
    before = len(hub.agents.sent)
    run(hub.steward_events.flush())
    if len(hub.agents.sent) == before:
        return []
    (name, text), = hub.agents.sent[before:]
    assert name == "steward"
    return text.splitlines()


# --- what doesn't wake it ---------------------------------------------------------------------------
def test_churn_in_items_it_never_named_wakes_nothing(hub):
    suggest(hub)
    events = [ev(repo="boot", number=n) for n in range(10, 40)] + [comment(repo="kernel", number=n) for n in range(1, 20)]
    assert call(hub, "feed.record", events=events)["kept"] == 49
    assert hub.steward_events.pending == [] and batch(hub) == []


def test_nothing_wakes_it_on_a_timer(hub):
    hub.agents.rows = []
    for _ in range(20):
        run(hub.steward_events.look())
    assert hub.agents.sent == []


def test_what_it_did_itself_in_an_item_it_named_doesnt_wake_it(hub):
    suggest(hub)
    hub.feed.mark("steward", "epd", 9)
    call(hub, "feed.record", events=[comment(kind="issue", repo="epd", number=9)])
    assert batch(hub) == []


def test_changes_that_wait_for_changes_since(hub):
    suggest(hub)
    quiet = [ev(kind="issue", repo="epd", number=9, what="labels", old="1", new="2"),
             ev(kind="issue", repo="epd", number=9, what="state", old="CLOSED", new="OPEN"),
             ev(repo="epd", number=9, what="review", old="APPROVED", new="REVIEW_REQUIRED"),
             ev(repo="epd", number=9, what="checks", old="failing", new="passing")]
    assert all(feed_phrase(e) is None for e in quiet)
    call(hub, "feed.record", events=quiet)
    assert batch(hub) == []


# --- its suggestions ----------------------------------------------------------------------------------
def test_its_suggestion_set_aside_wakes_it_naming_the_suggestion(hub):
    work = suggest(hub)
    assert call(hub, "work.dismiss", token="login", id=work)["ok"]
    assert batch(hub) == [f"- Your suggestion {work} (Draft docs for it, epd#9): the person set it aside."]


def test_its_suggestion_started_wakes_it_and_a_merge_in_what_it_named_comes_in_the_same_turn(hub):
    work = suggest(hub, covers=["kernel#204"])
    assert call(hub, "work.plan", token="login", id=work)["ok"]
    approved(hub, work)
    call(hub, "feed.record", events=[ev(repo="kernel", number=204), comment(repo="ops", number=1)])
    lines = batch(hub)
    body = [line for line in lines if line.startswith("- ")]
    assert len(body) == 2 and len(lines) == 2
    assert f"Your suggestion {work} (" in body[0] and "the person started it as new-issue-boot." in body[0]
    assert body[1].startswith(f"- kernel#204 (pull request, which you named in suggestion {work}): merged.")
    assert "https://github.com/GlassineOS/kernel/pull/204" in body[1]
    assert batch(hub) == []  # sent once


def test_its_suggestions_result_applied_wakes_it(hub):
    work = suggest(hub)
    record = hub.work.get(work)
    hub.work.move(record, "done", result="r-0123456789ab")
    hub._settle_launch({"id": "r-0123456789ab", "launch": work}, "filed")
    hub._settle_launch({"id": "r-0123456789ab", "launch": work}, "dismissed")
    body = batch(hub)
    # Two moves of one suggestion that come together: the latest stands.
    assert len(body) == 1 and "the person set its result aside (r-0123456789ab)." in body[0]
    hub.work.move(record, "done", result="r-0123456789ab")
    hub._settle_launch({"id": "r-0123456789ab", "launch": work}, "filed")
    assert "the person applied its result (r-0123456789ab)." in batch(hub)[0]


def test_someone_elses_suggestion_doesnt_wake_it(hub):
    reply = call(hub, "work.suggest", agent_token="full-token", action="issue-docs", repo="epd", number=9, why="x")
    if reply.get("ok"):
        assert call(hub, "work.dismiss", token="login", id=reply["id"])["ok"]
    assert batch(hub) == []


# --- sessions it started ------------------------------------------------------------------------------
def test_a_session_it_started_finishing_its_turn_and_ending_wakes_it(hub):
    reply = call(hub, "started.spawn", agent_token="steward-token", action="pr-review", repo="boot", number=5)
    assert reply["ok"], reply
    name = reply["name"]
    row = {"name": name, "repo": "boot", "number": 5, "state": "Working"}
    hub.agents.rows = [row, {"name": "someone-elses", "repo": "boot", "number": 6, "state": "Idle"}]
    run(hub.steward_events.look())
    assert batch(hub) == []
    row["state"] = "Idle"
    run(hub.steward_events.look())
    assert batch(hub)[0] == f"- {name}, a session you started on boot#5, finished its turn: session_summary reads what it said."
    row["state"] = "Stopped"
    run(hub.steward_events.look())
    assert batch(hub)[0] == f"- {name}, a session you started on boot#5, ended."
    # And the item it was started on is one it named.
    call(hub, "feed.record", events=[ev(number=5, what="review", old="REVIEW_REQUIRED", new="CHANGES_REQUESTED")])
    assert batch(hub)[0].startswith(f"- boot#5 (pull request, which you named in session {name}): reviewed: changes requested.")


def test_a_session_under_its_workflow_wakes_it_through_its_owners_route(hub):
    """managed.py wakes an owner for a hand-back, a report, an end and an answer: for the Steward that is an event."""
    managed = types.SimpleNamespace(steward_events=hub.steward_events)
    Managed.wake_owner(managed, "steward", "repo-maintainer-boot, your repo-maintainer, handed back.")
    Managed.wake_owner(managed, "steward", "Report 12 is answered: approve.")
    body = batch(hub)
    assert body == ["- repo-maintainer-boot, your repo-maintainer, handed back.", "- Report 12 is answered: approve."]


def test_the_answer_to_its_card_wakes_it(hub):
    hub._tell_and_wake("steward", "Card d-1 is answered: the maintainer allowed your call.", "Card d-1 is answered: allowed.")
    assert ("steward", "Card d-1 is answered: the maintainer allowed your call.") in hub.agents.told
    assert batch(hub)[0] == "- Card d-1 is answered: allowed."


def test_items_a_report_of_its_names_are_watched():
    assert refs_in("boot#12 and https://github.com/GlassineOS/kernel/pull/7, not x/boot#3 or #4") == [("boot", 12), ("kernel", 7)]
    events = StewardEvents(None)
    events.named_in("Blocked on epd#3.", "report 41")
    assert events.watching("EPD", 3)["why"] == ["report 41"]


# --- how it is sent -----------------------------------------------------------------------------------
def test_events_wait_while_it_is_busy_or_stopped_and_go_in_one_turn(hub):
    work = suggest(hub)
    hub.agents.refuse = "steward is busy"
    assert call(hub, "work.dismiss", token="login", id=work)["ok"]
    assert batch(hub) == []
    hub.agents.running = False
    hub._tell_and_wake("steward", "x", "Card d-2 is answered: no.")
    assert batch(hub) == [] and len(hub.steward_events.pending) == 2
    hub.agents.running, hub.agents.refuse = True, None
    assert len(batch(hub)) == 2 and hub.steward_events.pending == []


def test_what_waits_and_what_it_named_survive_a_restart(tmp_path):
    path = tmp_path / "events.json"
    events = StewardEvents(path)
    events.watch("boot", 7, "suggestion abc", "pr")
    events.add("Card d-1 is answered: no.")
    again = StewardEvents(path)
    assert again.watching("boot", 7)["why"] == ["suggestion abc"] and [e["text"] for e in again.pending] == ["Card d-1 is answered: no."]
    assert again.from_feed([{"kind": "pr", "repo": "boot", "number": 7, "what": "state", "new": "CLOSED", "own": False, "link": ""}]) == 1


def test_what_came_together_goes_once_the_quiet_has_passed():
    agents = StewardAgents()
    events = StewardEvents(None, agents, quiet=0.05)

    async def go():
        events.add("one")
        await asyncio.sleep(0.01)
        events.add("two")  # within the quiet: the same batch
        await asyncio.wait_for(events._soon, 5)
    run(go())
    assert agents.sent == [("steward", "- one\n- two")]


def test_too_many_waiting_give_way_and_the_batch_says_so():
    agents = StewardAgents()
    events = StewardEvents(None, agents)
    for n in range(MAX_PENDING + 5):
        events.add(f"event {n}")
    run(events.flush())
    text = agents.sent[0][1]
    assert "- event 4\n" not in text and "- event 5\n" in text and "5 earlier events gave way" in text


def test_a_steward_that_cant_read_private_repositories_hears_nothing_of_them():
    agents = StewardAgents()
    agents.all_repos = False

    async def public_of(repos):
        return {r for r in repos if r == "boot"}
    events = StewardEvents(None, agents, public_of=public_of)
    for repo in ("boot", "secret"):
        events.watch(repo, 1, "suggestion abc")
    events.from_feed([{"kind": "pr", "repo": r, "number": 1, "what": "state", "new": "MERGED", "own": False, "link": ""} for r in ("boot", "secret")])
    run(events.flush())
    (_, text), = agents.sent
    assert "boot#1" in text and "secret" not in text and events.pending == []


# --- the rest of the feed, when it asks (FR-057) -----------------------------------------------------------
def test_changes_since_by_item_or_repository_leaves_its_cursor(hub):
    hub.feed.begin("steward")
    call(hub, "feed.record", events=[ev(number=1), ev(number=2), ev(repo="kernel", number=1), comment(repo="kernel", number=3)])
    one = hub.feed.changes("steward", None, 10, None, "boot", 2)
    assert [(c["repo"], c["number"]) for c in one["changes"]] == [("boot", 2)] and one["narrowed"]["repo"] == "boot"
    repo = hub.feed.changes("steward", None, 10, None, "KERNEL")
    assert sorted(c["number"] for c in repo["changes"]) == [1, 3]
    assert len(hub.feed.changes("steward", None, 10, None)["changes"]) == 4  # the narrowed reads moved nothing
    with pytest.raises(FeedError):
        hub.feed.changes("steward", None, 10, None, None, 2)


def test_a_digest_is_a_short_line_per_repository_and_moves_the_cursor(hub):
    hub.feed.begin("steward")
    hub.feed.mark("steward", "kernel", 9)
    call(hub, "feed.record", events=[ev(number=1), ev(number=2, what="checks", old="passing", new="failing"), comment(number=2),
                                     comment(repo="kernel", number=4), ev(repo="kernel", number=9)])
    got = hub.feed.digest("steward", None, None)
    assert [d["repo"] for d in got["digest"]] == ["boot", "kernel"]
    boot, kernel = got["digest"]
    assert (boot["changes"], boot["important"], boot["items"], boot["own"]) == (3, 2, 2, 0)
    assert boot["what"] == {"check changes": 1, "commented items": 1, "merged": 1}
    assert (kernel["changes"], kernel["own"], kernel["what"]) == (2, 1, {"commented items": 1})
    assert hub.feed.changes("steward", None, 10, None)["changes"] == []  # past it all
    rows = hub.feed.changes("steward", int(got["from"]), 10, None, "boot")["changes"]
    assert len(rows) == 3
    assert "title" not in json.dumps(got) and "alice" not in json.dumps(got)


def test_the_hub_serves_narrowed_reads_and_the_digest(hub):
    hub.agents.scopes["steward-token"]["all_repos"] = True
    call(hub, "feed.record", events=[ev(number=1), ev(repo="kernel", number=1)])
    for kw, check in (({"item": "boot#1"}, lambda r: [c["repo"] for c in r["changes"]] == ["boot"]),
                      ({"repo": "GlassineOS/kernel"}, lambda r: [c["repo"] for c in r["changes"]] == ["kernel"]),
                      ({"digest": True}, lambda r: [d["repo"] for d in r["digest"]] == ["boot", "kernel"])):
        reply = call(hub, "feed.changes", token="login", **kw)
        assert reply["ok"] and check(reply), (kw, reply)
    for kw, word in (({"item": "boot"}, "repo#N"), ({"repo": "../x"}, "repositories"), ({"repo": "boot", "item": "kernel#1"}, "another"),
                     ({"digest": True, "repo": "boot"}, "every repository")):
        reply = call(hub, "feed.changes", token="login", **kw)
        assert not reply["ok"] and word in reply["error"], (kw, reply)


# --- what it reads before it says something waits (FR-058) ----------------------------------------------------
def test_my_suggestions_says_what_waits_and_never_what_was_started_set_aside_or_applied(hub):
    waiting = suggest(hub)
    gone = suggest(hub, number=10)
    assert call(hub, "work.dismiss", token="login", id=gone)["ok"]
    running = suggest(hub, number=11)
    assert call(hub, "work.plan", token="login", id=running)["ok"]
    approved(hub, running)
    applied = suggest(hub, number=12)
    hub.work.move(hub.work.get(applied), "filed", result=None)
    reply = call(hub, "work.mine", agent_token="steward-token")
    assert reply["ok"]
    by_id = {s["id"]: s for s in reply["suggestions"]}
    assert by_id[waiting]["waiting_for_the_person"] == "to start it, or set it aside" and by_id[waiting]["state"] == "offered"
    for work in (gone, running, applied):
        assert by_id[work]["waiting_for_the_person"] is None, by_id[work]
    assert by_id[running]["session"] == "new-issue-boot"
    # A started suggestion whose session handed in a result waits only until that result is applied.
    record = hub.work.get(running)
    made = hub.results.submit("comment", {"summary": "Fine.", "event": "comment", "notes": []}, session="new-issue-boot", session_id="first",
                              launch=running, items=[{"kind": "pr", "repo": "epd", "number": 11}], action="pr-review", persona="reviewer")
    hub.work.move(record, "done", result=made["id"])
    mine = {s["id"]: s for s in call(hub, "work.mine", agent_token="steward-token")["suggestions"]}
    assert mine[running]["waiting_for_the_person"] == "to apply its result, or set it aside"
    hub.results.settle(made["id"], True, "you")
    mine = {s["id"]: s for s in call(hub, "work.mine", agent_token="steward-token")["suggestions"]}
    assert mine[running]["waiting_for_the_person"] is None and mine[running]["result"]["state"] == "applied"


def test_my_suggestions_is_only_its_own_and_needs_the_tool(hub):
    suggest(hub)
    assert call(hub, "work.mine", agent_token="review-token").get("refused")
    hub.agents.scopes["other-token"] = {"session": "other", "tools": ["my_suggestions"]}
    assert call(hub, "work.mine", agent_token="other-token")["suggestions"] == []
