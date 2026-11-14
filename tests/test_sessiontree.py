# SPDX-License-Identifier: GPL-2.0-or-later
"""Sessions › Running as a tree (004 User Story 3, FR-012 to FR-015, FR-024; 001 FR-002): a real owner run through its
states with Agents, Machines and Managed as test_managed sets them up, and the pure arranging on hand-made nodes."""
import asyncio

import pytest

from hubd import interactions, sessiontree
from test_managed import kids, make_hub, op, settle, token

RUN = '''schema = 1
name = "issue-triage"
initial = "work"

[state.work]
initial = "implement"
[state.work.grant]
tools = ["AskUserQuestion"]
hub_tools = ["get_issue", "docs_search", "notes_find"]
checkout = false

[state.implement]
parent = "work"
[[state.implement.manages]]
name = "engineer"
persona = "triager"
workflow = "helper"
reuse = "resume"
[[state.implement.exit]]
to = "review"
decided_by = "hand"

[state.review]
parent = "work"
[[state.review.manages]]
name = "reviewer"
persona = "triager"
workflow = "helper"
reuse = "fresh"
returns = { verdict = ["pass", "fail"] }
[[state.review.exit]]
to = "fix"
decided_by = "hand"
[[state.review.exit]]
to = "done"
decided_by = "hand"

[state.fix]
parent = "work"
[[state.fix.manages]]
name = "engineer"
persona = "triager"
workflow = "helper"
reuse = "resume"
[[state.fix.exit]]
to = "review"
decided_by = "hand"

[state.done]
final = true
[state.done.grant]
tools = ["AskUserQuestion"]
hub_tools = ["get_issue", "docs_search", "notes_find"]
checkout = false
'''


@pytest.fixture
def run(tmp_path, monkeypatch):
    return make_hub(tmp_path, monkeypatch, RUN)


async def tree(h):
    return (await h.session_tree())["tree"]


def entry(t, owner, name):
    return next(e for e in t["nodes"][owner]["entries"] if e["name"] == name)


def test_an_implementor_run_keeps_one_engineer_row_and_folds_earlier_reviewers(run):
    """004 US3 scenarios 1 to 3: the engineer under its entry, resumed in one row naming its rounds; the round-1 reviewer
    stays while it is the latest return, then folds into "1 earlier reviewer" with its verdict once round 2 starts."""
    h, a, _judge = run

    async def go():
        name = (await a.start(a.defaults("issue-triage", "boot", 7)))["name"]
        await settle(h)
        [eng] = kids(h, a, name, "engineer")
        t = await tree(h)
        assert t["roots"] == [name] and t["nodes"][eng]["parent"] == name
        e = entry(t, name, "engineer")
        assert e["sessions"] == [eng] and e["in_force"] and e["reuse"] == "resume" and e["start"] == "auto" and e["max"] == 1
        assert e["states"] == ["implement", "fix"] and e["running"] == 1
        r = entry(t, name, "reviewer")
        assert not r["in_force"] and r["states"] == ["review"] and r["sessions"] == [] and r["reuse"] == "fresh"
        assert t["nodes"][eng]["served"] == [["implement", 1]] and not t["nodes"][eng]["resumed"]
        assert t["nodes"][eng]["live"] in ("working", "idle") and t["nodes"][name]["machine"]["path"] == ["work", "implement"]

        a.machines.move(name, "review", "hand")
        await settle(h)
        [rev1] = kids(h, a, name, "reviewer")
        t = await tree(h)
        # the engineer stopped on leaving (on_exit stop), and is the one its entry resumes: stopped, not ended, still shown
        assert t["nodes"][eng]["live"] == "stopped" and t["nodes"][eng]["kept"]
        assert entry(t, name, "reviewer")["sessions"] == [rev1] and entry(t, name, "reviewer")["in_force"]
        assert not entry(t, name, "engineer")["in_force"]
        assert (await op(h, "managed.return", token(a, rev1), fields={"verdict": "fail"}))["ok"]

        a.machines.move(name, "fix", "hand")
        await settle(h)
        t = await tree(h)
        node = t["nodes"][eng]
        assert entry(t, name, "engineer")["sessions"] == [eng]  # resumed: no second engineer
        assert node["resumed"] and [s for s, _r in node["served"]] == ["implement", "fix"] and node["live"] in ("working", "idle")
        # its one-state workflow's state is final by construction: the strip says what it waits for, not "a final state"
        assert "final" not in node["waits_for"]
        # the reviewer ended, and is still the latest return of its entry under a running owner: it stays, with its verdict
        assert t["nodes"][rev1]["live"] == "ended" and t["nodes"][rev1]["kept"] and t["nodes"][rev1]["returned"] == "fail"
        assert t["nodes"][rev1]["waits_for"] == "nothing: it has ended" and t["nodes"][rev1]["next"] == ""
        assert entry(t, name, "reviewer")["sessions"] == [rev1] and entry(t, name, "reviewer")["earlier"] == []

        a.machines.move(name, "review", "hand")
        await settle(h)
        rev2 = next(k for k in kids(h, a, name, "reviewer") if k != rev1)
        t = await tree(h)
        r = entry(t, name, "reviewer")
        assert r["sessions"] == [rev2] and [x["name"] for x in r["earlier"]] == [rev1]
        assert r["earlier"][0]["returned"] == "fail" and r["earlier"][0]["round"] == 1 and r["round"] == 2
        assert t["nodes"][rev2]["served"] == [["review", 2]]
        assert not t["nodes"][rev1]["kept"]  # folded: the fold shows it, not the tree
        return name
    asyncio.run(go())


def test_an_ended_owner_stays_while_a_kept_child_runs():
    """004 edge case: the child of an ended owner shows under it, and the owner stays while anything under it runs."""
    nodes = {
        "boss": node("boss", live="ended", entries=[ent("helper", reuse="fresh", on_exit="keep", child="kid")]),
        "kid": node("kid", owner="boss", entry="helper", live="working"),
        "gone": node("gone", live="ended"),
    }
    t = sessiontree.arrange({"nodes": nodes, "events": {}})
    assert t["nodes"]["boss"]["kept"] and t["nodes"]["kid"]["parent"] == "boss"
    assert entry(t, "boss", "helper")["sessions"] == ["kid"]
    assert not t["nodes"]["gone"]["kept"] and t["ended_hidden"] == 1


def test_an_ended_session_stays_while_a_card_of_it_waits():
    nodes = {"done": node("done", live="ended", cards=1), "old": node("old", live="ended")}
    t = sessiontree.arrange({"nodes": nodes, "events": {}})
    assert t["nodes"]["done"]["kept"] and not t["nodes"]["old"]["kept"]


def test_several_sessions_of_one_entry_each_show_with_the_count_against_its_most():
    nodes = {"own": node("own", entries=[ent("asker", reuse="fresh", max=3)]),
             "a1": node("a1", owner="own", entry="asker", live="working", started=1),
             "a2": node("a2", owner="own", entry="asker", live="idle", started=2)}
    events = {"own": [ev("start", "a1", "work", 1), ev("start", "a2", "work", 1)]}
    e = entry(sessiontree.arrange({"nodes": nodes, "events": events}), "own", "asker")
    assert e["sessions"] == ["a1", "a2"] and e["running"] == 2 and e["max"] == 3 and e["earlier"] == []


def test_earlier_rounds_whose_folders_are_gone_fold_from_the_log():
    nodes = {"own": node("own", entries=[ent("triage", reuse="fresh")]),
             "t3": node("t3", owner="own", entry="triage", live="working", started=3)}
    events = {"own": [ev("start", "t1", "watch", 1), ev("return", "t1", "watch", fields={"verdict": "pass"}),
                      ev("start", "t3", "watch", 3)]}
    e = entry(sessiontree.arrange({"nodes": nodes, "events": events}), "own", "triage")
    assert e["sessions"] == ["t3"] and e["earlier"] == [{"name": "t1", "round": 1, "returned": "pass", "seconds": None, "cost": None,
                                                         "persona": None, "gone": True}]


def test_roots_go_steward_maintainers_item_workflows_quick_tasks_by_item_then_shells():
    """004 FR-012. A session another started without a managing entry stays a root, and says who started it."""
    nodes = {
        "shell": sessiontree.plain_node({"name": "shell", "cwd": "/tmp"}),
        "quick": node("quick", one_state=True, items=[{"kind": "pr", "repo": "ink", "number": 57, "role": "covers"}], started=1),
        "impl": node("impl", started=2, started_by="steward"),
        "maint": node("maint", maintainer=True, started=3, started_by="steward"),
        "steward": node("steward", steward=True, started=4),
        "quick2": node("quick2", one_state=True, items=[{"kind": "repo", "repo": "hub", "number": None, "role": "covers"}], started=5),
    }
    t = sessiontree.arrange({"nodes": nodes, "events": {}})
    assert t["roots"] == ["steward", "maint", "impl"]
    assert t["quick"] == [["ink#57", ["quick"]], ["hub", ["quick2"]]] and t["shells"] == ["shell"]
    assert t["nodes"]["impl"]["started_by"] == "steward" and t["nodes"]["impl"]["parent"] is None


def test_a_reviewers_verdict_reaches_the_pull_request_it_covers():
    nodes = {"own": node("own", entries=[ent("reviewer", reuse="fresh")]),
             "r1": node("r1", owner="own", entry="reviewer", live="ended", items=[{"kind": "pr", "repo": "epd", "number": 14, "role": "covers"}])}
    events = {"own": [ev("start", "r1", "review", 1), ev("return", "r1", "review", fields={"verdict": "fail"}, findings=3)]}
    t = sessiontree.arrange({"nodes": nodes, "events": events})
    assert t["verdicts"] == {"epd#14": "fail"} and t["nodes"]["r1"]["returned"] == "fail · 3 findings"


def test_needs_you_counts_every_workflow_card_per_session_and_in_the_header():
    """001 FR-002: the header's count is every pending row, workflow decisions included (a move's confirm, a start approval, a
    design to look at, a proposed change, a merge); the tree counts them per session, a change with the session that proposed it."""
    now = 1000.0
    decisions = [dec("d-1", "machine.widen", "impl"), dec("d-2", "machine.approve", "impl", type_="managed"),
                 dec("d-3", "machine.approve", "design-1", type_="design"), dec("d-4", "workflow.change", None, proposed_by="author"),
                 dec("d-5", "merge", "impl", state="ended")]
    asks = {"open": [{"id": "x1", "kind": "permission", "state": "pending", "session": "impl", "made": now - 5, "tool": "mcp__glassine-hub__merge_pr",
                      "input": {}, "agent": None}], "answered": []}
    listed = interactions.project(asks, decisions, [], {}, {}, now=now)
    assert listed["counts"]["pending"] == 5 and listed["counts"]["by_kind"]["decision"] == 4
    assert sessiontree.cards_by_session(listed["items"]) == {"impl": 3, "design-1": 1, "author": 1}


def test_the_tree_is_behind_the_login(run):
    h, _a, _judge = run
    assert asyncio.run(h.request({"op": "shell.tree"})).get("denied")


def test_a_session_folder_reads_without_making_or_saving_anything(run):
    """The tree is polled: reading it makes no machine and banks no usage."""
    h, a, _judge = run

    async def go():
        name = (await a.start(a.defaults("issue-triage", "boot", 7)))["name"]
        await settle(h)
        before = {p: p.stat().st_mtime_ns for p in a.sessions.rglob("*") if p.is_file()}
        await tree(h)
        after = {p: p.stat().st_mtime_ns for p in a.sessions.rglob("*") if p.is_file()}
        assert before == after
    asyncio.run(go())


# --- hand-made nodes -------------------------------------------------------------------------------------------------------

def node(name, owner=None, entry=None, live="idle", cards=0, entries=None, started=0, one_state=False, steward=False,
         maintainer=False, started_by=None, items=None):
    return {"name": name, "plain": False, "persona": {"id": "p"}, "owner": owner, "owner_sid": None, "entry": entry, "live": live,
            "cards": cards, "items": items or [], "machine": {"workflow": "w", "state": "s", "one_state": one_state}, "started": started,
            "steward": steward, "maintainer": maintainer, "started_by": started_by, "conversations": [], "child_round": None,
            "seconds": None, "cost": None, "_inst": None, "_entries": entries or []}


def ent(name, reuse="resume", max=1, on_exit="stop", child=None):
    return {"name": name, "persona": "p", "workflow": "w", "start": "auto", "when": "", "max": max, "reuse": reuse, "on_exit": on_exit,
            "states": ["s"], "in_force": True, "round": 1, "returns": [], "child": child}


def ev(kind, child, state, rnd=None, fields=None, **counts):
    if kind == "start":
        return {"signal": "hub:managed.start", "state": state, "proposal": "start " + ("triage" if child.startswith("t") else "asker" if child.startswith("a") else "reviewer"),
                "checks": {"started": child, "resumed": False, "round": rnd}, "at": 0}
    return {"signal": "hub:managed.return", "state": state, "proposal": ("triage" if child.startswith("t") else "reviewer") + " returned",
            "checks": {"from": child, "returns": fields or {}, **counts}, "at": 1}


def dec(id_, kind, asked_by, type_=None, proposed_by=None, state="requested"):
    scope = {"type": type_} if type_ else {}
    if proposed_by:
        scope["proposed_by"] = proposed_by
    if kind == "merge":
        scope = {"repo": "epd", "number": 14}
    return {"id": id_, "kind": kind, "scope": scope, "state": state, "asked_by": asked_by, "made": 900.0, "ends": {}, "approved": None}


def test_an_entrys_note_names_the_owner_for_the_maintainer():
    """managed_status tells the owner what an entry waits for; the tree shows it to the maintainer, so "you" is the owner."""
    assert sessiontree.owner_note("reviewer starts when you call start_managed.", "impl") == "reviewer starts when impl asks for it."
    assert sessiontree.owner_note("engineer's session for this round has ended. Don't start it or do its work.", "impl") == \
        "engineer's session for this round has ended."
    assert sessiontree.owner_note("fixer's start waits for an approval above you; it starts once that is given.", "impl") == \
        "fixer's start waits for an approval above impl; it starts once that is given."
