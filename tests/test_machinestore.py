# SPDX-License-Identifier: GPL-2.0-or-later
"""Saved workflow versions (012 FR-001, FR-008, FR-009, FR-060 to FR-063): which version a session runs, that a version never
changes, what a save refuses, sessions taking a new version at their next move, the ops behind a login, the workflow.change
card, and replay."""
import asyncio
import json
import os
import shutil
import stat
from pathlib import Path

import pytest

from hubd import agents as agents_module
from hubd import auth, machine, machinestore
from hubd.agents import Agents, Library
from hubd.decisions import CHANGE, Decisions
from hubd.instances import version_of
from hubd.machinestore import ORG, Store, StoreError, replay
from hubd.server import Hubd

REPO = Path(__file__).resolve().parents[1]
ONE = "run-explain"       # one state, about a run: no checkout


class FakeShells:
    def __init__(self):
        self.live = set()

    async def list(self):
        return [{"name": n, "cwd": ""} for n in self.live]

    async def new(self, name, cwd, command):
        self.live.add(name)

    async def kill(self, name):
        self.live.discard(name)


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(agents_module, "SANDBOX_TOOLS", ())
    claude = tmp_path / "claude"
    claude.write_text("#!/bin/sh\n")
    claude.chmod(0o755)
    a = Agents(Library(REPO / "agents"), FakeShells(), tmp_path / "state", claude=str(claude), mcp_url="u", agent_token="t",
               workspace=tmp_path / "ws")
    decisions = Decisions(tmp_path / "decisions")
    decisions.session_id_of = a.session_id_of
    sessions = auth.Sessions()
    hub = Hubd(None, None, sessions, "general-token", agents=a, decision_store=decisions)
    return a, decisions, hub, sessions.create()


def text_of(name: str) -> str:
    return (REPO / "agents" / "workflows" / f"{name}.toml").read_text()


def narrower(name: str = ONE) -> str:
    """run-explain without work_search."""
    return text_of(name).replace(', "work_search"]', "]")


def run(coroutine):
    return asyncio.run(coroutine)


# ---- the store ----

def test_resolution_goes_override_then_organisation_then_the_file(tmp_path):
    store = Store(tmp_path, {ONE: text_of(ONE)})
    assert store.resolve(ONE) == {"scope": ORG, "v": 0, "text": text_of(ONE)}
    assert store.resolve(ONE, "boot")["v"] == 0
    store.save(ONE, ORG, narrower(), 0, "me")
    assert store.resolve(ONE, "boot") == {"scope": ORG, "v": 1, "text": narrower()}
    override = narrower().replace('"docs_search", ', "")
    store.save(ONE, "GlassineOS__boot", override, 0, "me")
    assert store.resolve(ONE, "boot") == {"scope": "GlassineOS__boot", "v": 1, "text": override}
    assert store.resolve(ONE, "hub")["scope"] == ORG and store.resolve(ONE)["text"] == narrower()
    assert store.overrides("boot") == {ONE: override} and store.overrides("hub") == {}
    assert store.scopes(ONE) == [ORG, "GlassineOS__boot"]


def test_a_version_never_changes(tmp_path):
    store = Store(tmp_path, {ONE: text_of(ONE)})
    saved = store.save(ONE, ORG, narrower(), 0, "me", note="why")
    path = tmp_path / ORG / ONE / "v1.toml"
    assert saved == {"v": 1, "version": version_of(narrower()), "scope": ORG}
    assert stat.S_IMODE(path.stat().st_mode) == 0o400
    with pytest.raises(StoreError, match="v1 was saved since v0"):
        store.save(ONE, ORG, text_of(ONE), 0, "you")  # a stale base: no lost update
    with pytest.raises(StoreError, match="saved meanwhile"):
        Store._create(path, "anything")  # the name is taken: never overwritten
    assert path.read_text() == narrower()
    assert store.about(ONE, ORG, 1)["who"] == "me" and store.about(ONE, ORG, 1)["note"] == "why"
    assert [p.name for p in path.parent.iterdir() if p.name.startswith(".")] == []
    with pytest.raises(StoreError):
        store.text(ONE, ORG, -1)


@pytest.mark.parametrize("scope", ["../x", "GlassineOS__..", "other__boot", "GlassineOS__a/b", ""])
def test_a_scope_names_the_organisation_or_one_of_its_repositories(tmp_path, scope):
    with pytest.raises(StoreError):
        Store(tmp_path, {ONE: text_of(ONE)}).save(ONE, scope, narrower(), 0, "me")


# ---- saving through the ops: what the checks refuse ----

def test_a_save_refuses_problems_a_wrong_name_and_what_the_library_would(world):
    a, _d, hub, _login = world
    ops = hub.workflows
    broken = text_of(ONE) + '\n[state.orphan]\nfinal = true\n'  # can't be reached
    for text, why in ((broken, "can't be reached"), (text_of(ONE).replace(f'name = "{ONE}"', 'name = "other"'), "this is"),
                      (text_of(ONE).replace('checkout = false', 'checkout = false\ngithub = ["read"]'), "locked action with Bash")):
        reply = ops.request("workflow.save", {"name": ONE, "scope": ORG, "text": text, "base_version": 0}, "me")
        assert not reply["ok"] and why in reply["error"], reply
        assert why in json.dumps(ops.request("workflow.check", {"name": ONE, "text": text}, "me")["findings"])
    assert a.workflow_store.numbers(ONE, ORG) == []
    reply = ops.request("workflow.save", {"name": ONE, "scope": ORG, "text": narrower(), "base_version": 0}, "me")
    assert reply["ok"] and reply["saved"]["v"] == 1
    stale = ops.request("workflow.save", {"name": ONE, "scope": ORG, "text": text_of(ONE), "base_version": 0}, "me")
    assert not stale["ok"] and "v1 was saved since v0" in stale["error"]


def test_an_organisation_save_is_what_every_launch_and_the_planner_get(world):
    a, _d, hub, _login = world
    assert "work_search" in a.defaults(ONE, "boot", 5)["hub_tools"]
    hub.workflows.request("workflow.save", {"name": ONE, "scope": ORG, "text": narrower(), "base_version": 0}, "me")
    assert "work_search" not in a.defaults(ONE, "boot", 5)["hub_tools"]
    assert a.library.actions[ONE]["definition"] == narrower()
    # hubd started again on the same state folder takes it too
    again = Agents(Library(REPO / "agents"), FakeShells(), a.state, claude="x", mcp_url="u", agent_token="t")
    assert again.library.actions[ONE]["definition"] == narrower()


def test_a_repository_override_is_that_repositorys_alone(world):
    a, _d, hub, _login = world
    reply = hub.workflows.request("workflow.save", {"name": ONE, "scope": "GlassineOS__boot", "text": narrower(), "base_version": 0}, "me")
    assert reply["ok"], reply
    assert "work_search" not in a.defaults(ONE, "boot", 5)["hub_tools"]
    assert "work_search" in a.defaults(ONE, "hub", 5)["hub_tools"]
    assert a.library.actions[ONE]["definition"] == text_of(ONE)  # the library itself stays the organisation's
    name = run(a.start(a.defaults(ONE, "boot", 5)))["name"]
    assert a.machines.peek(name).version == version_of(narrower())
    record = json.loads((a.sessions / name / "session.json").read_text())
    assert a.machines.latest(record) == narrower()
    assert "work_search" not in machine.effective(machine.parse(narrower()), "session").hub_tools
    assert a._state_action(name, a.library.actions[ONE])["definition"] == narrower()


def test_a_save_doesnt_widen_a_running_one_state_session(world):
    a, _d, hub, _login = world
    name = run(a.start(a.defaults(ONE, "boot", 5)))["name"]
    token = (a.sessions / name / agents_module.TOKEN_FILE).read_text().strip()
    before = a.scope(token)
    wider = text_of(ONE).replace('"work_search"]', '"work_search", "list_prs"]')
    assert hub.workflows.request("workflow.save", {"name": ONE, "scope": ORG, "text": wider, "base_version": 0}, "me")["ok"]
    assert a.scope(token) == before and "list_prs" not in before["tools"]
    assert "list_prs" not in json.loads((a.sessions / name / "session.json").read_text())["config"]["hub_tools"]


def test_a_running_session_takes_the_new_version_at_its_next_move(world, tmp_path):
    a, _d, hub, _login = world
    a.library.actions["knowledge-research"]  # a one-state action; its moves are by hand only, as for any session
    name = run(a.start(a.defaults(ONE, "boot", 5)))["name"]
    old = a.machines.peek(name).version
    saved = hub.workflows.request("workflow.save", {"name": ONE, "scope": ORG, "text": narrower(), "base_version": 0}, "me")["saved"]
    assert a.machines.peek(name).version == old  # until it moves
    view = a.machines.view(*a.machines.load(name))
    assert view["newer"] == {"version": saved["version"], "has_state": True, "kept": False}
    a.machines.move(name, "session", "hand", who="me")
    assert a.machines.peek(name).version == saved["version"]


def test_a_version_without_the_sessions_state_keeps_it_on_its_own(world):
    a, _d, hub, _login = world
    name = run(a.start(a.defaults(ONE, "boot", 5)))["name"]
    renamed = text_of(ONE).replace('initial = "session"', 'initial = "talk"').replace("[state.session", "[state.talk")
    assert hub.workflows.request("workflow.save", {"name": ONE, "scope": ORG, "text": renamed, "base_version": 0}, "me")["ok"]
    view = a.machines.view(*a.machines.load(name))
    assert view["newer"]["has_state"] is False and view["instance"]["state"] == "session"


# ---- the ops: a login, never a token ----

def test_the_ops_take_a_login_and_no_token(world):
    _a, _d, hub, login = world

    async def go():
        for op in machinestore.OPS:
            for field, token in (("agent_token", "general-token"), ("agent_token", "t"), ("token", "wrong"), ("token", None)):
                reply = await hub.request({"op": op, field: token, "name": ONE, "scope": ORG, "text": narrower(), "base_version": 0})
                assert reply["ok"] is False and reply["denied"], (op, field)
        assert (await hub.request({"op": "workflow.list", "token": login}))["ok"]
        got = await hub.request({"op": "workflow.get", "token": login, "name": ONE})
        assert got["ok"] and got["text"] == text_of(ONE) and got["versions"][0]["v"] == 0 and got["outline"]["states"][0]["id"] == "session"
    run(go())


def test_get_and_check_say_where_a_grant_comes_from_and_whether_an_exit_widens(world):
    _a, _d, hub, _login = world
    got = hub.workflows.request("workflow.get", {"name": "implement"}, "me")
    states = {s["id"]: s for s in got["outline"]["states"]}
    review = {(r["key"], r["item"]): r for r in states["review"]["grant"]}
    assert review[("tools", "Bash")]["from"] == "work"
    fix = {(r["key"], r["item"]): r for r in states["fix"]["grant"]}
    assert fix[("github", "push")]["from"] is None
    assert [e["widens"] for e in states["review"]["exits"]] == [False, False, True]  # → fix adds push
    assert [e["from"] for e in states["fix"]["inherited"]] == []
    assert any(f["kind"] == "mark" and "merge_pr" in f["text"] for f in got["findings"])


def test_diff_gives_the_outline_rows_and_the_text(world):
    _a, _d, hub, _login = world
    text = text_of("implement").replace('requires = ["rounds.fix >= 3", "pr.review == changes_requested or managed.reviewer.verdict == fail"]',
                                        'requires = ["rounds.fix >= 2", "pr.review == changes_requested or managed.reviewer.verdict == fail"]')
    got = hub.workflows.request("workflow.diff", {"name": "implement", "scope": ORG, "from": 0, "text": text}, "me")
    changed = [r for r in got["rows"] if r["kind"] != "same"]
    assert [(r["kind"], r["state"], r["exit"], r["fields"]) for r in changed] == [("changed", "review", 2, ["requires"])]
    assert changed[0]["before"]["requires"][0] == "rounds.fix >= 3" and changed[0]["after"]["requires"][0] == "rounds.fix >= 2"
    assert {"kind": "add", "text": 'requires = ["rounds.fix >= 2", "pr.review == changes_requested or managed.reviewer.verdict == fail"]'} in got["text"]
    assert got["stat"] == {"added": 1, "removed": 1}


def test_reorder_moves_an_exit_through_the_text(world):
    _a, _d, hub, _login = world
    got = hub.workflows.request("workflow.reorder", {"text": text_of("implement"), "state": "review", "place": 3, "by": -1}, "me")
    assert [e.to for e in machine.parse(got["text"]).states["review"].exits] == ["merge-ready", "fix", "escalated"]
    assert not hub.workflows.request("workflow.reorder", {"text": text_of("implement"), "state": "review", "place": 1, "by": -1}, "me")["ok"]


# ---- starts in the editor (FR-105) ----

def test_the_list_has_every_workflow_with_its_starts_by_kind(world):
    _a, _d, hub, _login = world
    rows = {r["name"]: r for r in hub.workflows.request("workflow.list", {}, "me")["workflows"]}
    assert set(rows) == {p.stem for p in (REPO / "agents" / "workflows").glob("*.toml")}  # one-state ones too
    assert rows["implementor"]["kinds"] == ["issue", "pr"] and not rows["implementor"]["managed_only"]
    assert [(s["id"], s["on"], s["label"], s["lead"]) for s in rows["implementor"]["starts"]] == [
        ("implementor", "issue", "Work on this", True), ("implementor-pr", "pr", "Take this on", True)]
    assert rows["implement"]["managed_only"] and rows["implement"]["starts"] == [] and rows["engineer"]["managed_only"]
    assert rows[ONE]["states"] == 1 and rows[ONE]["kinds"] == ["run"]


def test_the_outline_has_the_starts_with_where_they_start_and_what_a_session_receives(world):
    _a, _d, hub, _login = world
    got = hub.workflows.request("workflow.get", {"name": "implementor"}, "me")["outline"]
    issue, pr = got["starts"]
    assert (issue["id"], issue["starts_in"], issue["path"], issue["persona"]) == ("implementor", "implement", ["work", "implement"], "implementor")
    assert (pr["id"], pr["starts_in"], pr["when_held"], pr["lead"]) == ("implementor-pr", "review", "hide", True)
    assert pr["receives"].startswith("Carry pull request #<number> of GlassineOS/<repo>")
    assert "kind: pull request" in pr["receives"] and "read from GitHub when the session starts" in pr["receives"]
    assert got["launch"]["personas"] == ["implementor"] and got["starts_named"]
    beside = hub.workflows.request("workflow.get", {"name": "pr-review"}, "me")["outline"]["starts"][0]
    assert beside["when_held"] == "beside" and beside["writes"] == []


def test_a_start_is_edited_through_the_text_and_its_prompt_shows_in_the_diff_and_the_replay(world):
    _a, _d, hub, _login = world
    text = text_of("pr-explain")
    start = machine.start_json(machine.parse(text).starts[0])
    got = hub.workflows.request("workflow.start", {"name": "pr-explain", "text": text, "place": 1,
                                                    "start": {**start, "prompt": "Explain #{number} of {repo} in three lines.\n"}}, "me")
    assert got["ok"] and machine.parse(got["text"]).starts[0].prompt == "Explain #{number} of {repo} in three lines.\n"
    assert [f for f in got["findings"] if f["kind"] == "problem"] == []
    diffed = hub.workflows.request("workflow.diff", {"name": "pr-explain", "scope": ORG, "from": 0, "text": got["text"]}, "me")
    [row] = [r for r in diffed["starts"] if r["kind"] != "same"]
    assert row["fields"] == ["prompt"] and row["prompt"]["after"].startswith("Explain #{number} of {repo} in three")
    # a prompt that fills in more than the item's fields is refused before anything is saved
    bad = hub.workflows.request("workflow.start", {"name": "pr-explain", "text": text, "place": 1,
                                                    "start": {**start, "prompt": "{repo.__class__}"}}, "me")
    assert bad["ok"] and any("isn't one of" in f["text"] for f in bad["findings"] if f["kind"] == "problem")
    refused = hub.workflows.request("workflow.save", {"name": "pr-explain", "scope": ORG, "text": bad["text"], "base_version": 0}, "me")
    assert not refused["ok"]
    added = hub.workflows.request("workflow.start", {"name": "pr-explain", "text": text, "start": {"on": "pr", "label": "Explain again", "id": "pr-explain-2"}}, "me")
    assert [st.label for st in machine.parse(added["text"]).starts] == ["Explain the diff", "Explain again"]
    gone = hub.workflows.request("workflow.start", {"name": "pr-explain", "text": text, "place": 1}, "me")
    assert machine.parse(gone["text"]).starts == ()
    assert not hub.workflows.request("workflow.start", {"name": "pr-explain", "text": text, "place": 1, "start": {"on": "pr", "colour": "red"}}, "me")["ok"]
    beside = hub.workflows.request("workflow.start", {"name": "pr-explain", "text": text.replace('result = "none"', 'result = "none"'), "place": 1,
                                                       "start": {**start, "when_held": "beside"}}, "me")
    assert beside["ok"]


def test_a_text_naming_no_starts_inherits_the_files_and_an_edit_keeps_them(world):
    _a, _d, hub, _login = world
    text = text_of("implementor")
    d = machine.parse(text)
    bare = machine.emit(machine.Definition(**{**{f: getattr(d, f) for f in d.__dataclass_fields__}, "starts": None}))
    got = hub.workflows.request("workflow.check", {"name": "implementor", "text": bare}, "me")
    assert [s["id"] for s in got["outline"]["starts"]] == ["implementor", "implementor-pr"] and got["outline"]["starts"][0]["inherited"]
    edited = hub.workflows.request("workflow.start", {"name": "implementor", "text": bare, "place": 2,
                                                       "start": {**machine.start_json(d.starts[1]), "label": "Take it on"}}, "me")
    assert [st.label for st in machine.parse(edited["text"]).starts] == ["Work on this", "Take it on"]


# ---- the workflow.change card ----

def test_a_proposal_is_a_card_and_approving_it_saves(world):
    a, decisions, hub, login = world
    reply = hub.workflows.request("workflow.propose", {"name": ONE, "scope": ORG, "text": narrower(), "note": "it never searches"}, "me")
    assert reply["ok"], reply
    card = reply["decision"]
    assert card["kind"] == CHANGE and card["state"] == "requested" and "a new version of run-explain" in card["says"]
    assert card["scope"]["rows"] and card["scope"]["text_diff"] and card["scope"]["base_version"] == 0
    assert a.workflow_store.numbers(ONE, ORG) == []  # a proposal saves nothing

    async def answer(verdict, **more):
        return await hub.request({"op": f"decision.{verdict}", "token": login, "id": card["id"], **more})
    got = run(answer("approve"))
    assert got["ok"] and got["decision"]["state"] == "ended" and "saved as v1" in got["decision"]["why_ended"]
    assert a.workflow_store.about(ONE, ORG, 1)["who"] == hub.sessions.own_user()
    assert a.workflow_store.about(ONE, ORG, 1)["decision"] == card["id"]
    assert not run(answer("approve"))["ok"]  # answered once


def test_approve_is_refused_while_a_problem_stands_and_sending_back_ends_it(world):
    a, decisions, hub, login = world
    broken = text_of(ONE) + '\n[state.orphan]\nfinal = true\n'
    card = hub.workflows.request("workflow.propose", {"name": ONE, "scope": ORG, "text": broken, "note": "x"}, "me")["decision"]
    assert any(f["kind"] == "problem" for f in card["scope"]["findings"])
    got = run(hub.request({"op": "decision.approve", "token": login, "id": card["id"]}))
    assert not got["ok"] and "can't be reached" in got["error"]
    assert decisions._get(card["id"])["state"] == "requested" and a.workflow_store.numbers(ONE, ORG) == []
    got = run(hub.request({"op": "decision.deny", "token": login, "id": card["id"], "why": "make it reachable", "changes": True}))
    assert got["decision"]["why_ended"] == "you asked for changes: make it reachable"


def test_the_card_answers_through_the_interaction_op_the_app_calls(world):
    a, _d, hub, login = world
    cards = [hub.workflows.request("workflow.propose", {"name": ONE, "scope": ORG, "text": narrower(), "note": "x"}, "me")["decision"] for _ in range(3)]

    def answer(card, verdict, **more):
        return run(hub.request({"op": "interaction.answer", "token": login, "id": card["id"], "verdict": verdict, **more}))
    assert answer(cards[0], "deny", why="split it", changes=True)["ok"]
    assert answer(cards[1], "deny", why="not now")["ok"]
    assert answer(cards[2], "end")["ok"] is False  # a change ends by an answer, not by decision.end
    ends = [hub.decisions._get(c["id"]).get("why_ended") or "" for c in cards[:2]]
    assert ends[0] == "you asked for changes: split it" and ends[1].startswith("discarded")
    assert a.workflow_store.numbers(ONE, ORG) == []
    assert answer(cards[2], "approve")["ok"] and a.workflow_store.numbers(ONE, ORG) == [1]


def test_approving_after_a_newer_save_is_refused(world):
    a, _d, hub, login = world
    card = hub.workflows.request("workflow.propose", {"name": ONE, "scope": ORG, "text": narrower(), "note": "x"}, "me")["decision"]
    hub.workflows.request("workflow.save", {"name": ONE, "scope": ORG, "text": narrower().replace('"docs_search", ', ""), "base_version": 0}, "me")
    got = run(hub.request({"op": "decision.approve", "token": login, "id": card["id"]}))
    assert not got["ok"] and "was saved since" in got["error"]


def test_a_change_card_survives_a_restart(world, tmp_path):
    _a, _d, hub, _login = world
    card = hub.workflows.request("workflow.propose", {"name": ONE, "scope": ORG, "text": narrower(), "note": "x"}, "me")["decision"]
    assert Decisions(tmp_path / "decisions")._get(card["id"])["kind"] == CHANGE


# ---- replay ----

def _ev(seq, at, state, signal, rows, moved_to=None, proposal=None, judge=None, version="v"):
    checks = {"exits": rows}
    if moved_to:
        checks["move"] = {"moved": True, "to": moved_to}
    return {"seq": seq, "at": at, "state": state, "signal": signal, "version": version, "proposal": proposal, "evidence": "an outsider's words",
            "checks": checks, "judge": judge, "failed": False}


def _terms(**facts):
    return [{"requires": k, "terms": [{"fact": k, "op": "==", "want": v, "value": v, "holds": True}], "holds": True} for k, v in facts.items()]


IMPL = text_of("implement")
HISTORY = {"moves": [], "evaluations": [
    _ev(1, 10, "implement", "turn.end", [{"exit": 0, "to": "review", "decided_by": "judge", "picked": True,
                                         "checks": [{"requires": "pr.open", "terms": [{"fact": "pr.open", "op": "==", "want": True, "value": True, "holds": True}], "holds": True},
                                                    {"requires": "pr.checks == pass", "terms": [{"fact": "pr.checks", "op": "==", "want": "pass", "value": "pass", "holds": True}], "holds": True}],
                                         "holds": True}], "review", "exit 0 to review", "small"),
    _ev(2, 20, "review", "feed:pr.review", [{"exit": 0, "to": "merge-ready", "decided_by": "facts",
                                            "checks": [{"requires": "pr.review == approved or managed.reviewer.verdict == pass", "terms": [{"fact": "pr.review", "op": "==", "want": "approved", "value": "changes_requested", "holds": False},
                                                                                                                       {"fact": "managed.reviewer.verdict", "op": "==", "want": "pass", "value": None, "holds": None}], "holds": False}], "holds": False},
                                           {"exit": 1, "to": "escalated", "decided_by": "counter",
                                            "checks": [{"requires": "rounds.fix >= 3", "terms": [{"fact": "rounds.fix", "op": ">=", "want": 3, "value": 0, "holds": False}], "holds": False}], "holds": False},
                                           {"exit": 2, "to": "fix", "decided_by": "facts", "checks": [], "holds": True}], "fix"),
]}


def test_replay_of_the_same_definition_finds_no_difference_and_is_deterministic():
    d = machine.parse(IMPL)
    first = replay(d, HISTORY, {"v": d})
    assert first == replay(d, json.loads(json.dumps(HISTORY)), {"v": d})
    assert first["differs"] == 0 and first["end"] == "fix" and [s["replay"]["to"] for s in first["steps"]] == ["review", "fix"]
    assert "an outsider's words" not in json.dumps(first)


def test_replay_says_where_a_changed_definition_moves_differently():
    sooner = IMPL.replace('requires = ["rounds.fix >= 3", "pr.review == changes_requested or managed.reviewer.verdict == fail"]', 'requires = ["rounds.fix >= 0", "pr.review == changes_requested or managed.reviewer.verdict == fail"]')
    d = machine.parse(sooner)
    got = replay(d, HISTORY, {"v": machine.parse(IMPL)})
    second = got["steps"][1]
    assert got["differs"] == 1 and second["replay"]["to"] == "escalated" and second["logged"]["to"] == "fix" and second["differs"]
    assert got["first_difference"] == 20


def test_replay_cant_tell_a_fact_the_log_didnt_keep_or_a_question_not_asked():
    asks_more = IMPL.replace('requires = ["pr.review == approved or managed.reviewer.verdict == pass", "pr.checks == pass"]', 'requires = ["pr.review == changes_requested", "issue.linked"]')
    got = replay(machine.parse(asks_more), HISTORY, {"v": machine.parse(IMPL)})
    assert got["steps"][1]["replay"]["result"] == "cant_tell" and got["steps"][1]["differs"] is None
    assert "issue.linked" in got["unknown_facts"]
    reworded = IMPL.replace("The change is complete: it is committed", "The change is done: it is committed")
    got = replay(machine.parse(reworded), HISTORY, {"v": machine.parse(IMPL)})
    assert got["steps"][0]["replay"]["result"] == "cant_tell"


def test_replay_through_the_op_reads_the_sessions_log(world):
    a, _d, hub, _login = world
    version = version_of(IMPL)
    for ev in HISTORY["evaluations"]:
        a.machines.log.evaluation("conv-1", "impl-1", ev["signal"], ev["state"], version, proposal=ev["proposal"],
                                  evidence=ev["evidence"], checks=ev["checks"], judge=ev["judge"])
    listed = hub.workflows.request("workflow.get", {"name": "implement"}, "me")["sessions"]
    assert [s["session_id"] for s in listed] == ["conv-1"] and listed[0]["name"] == "impl-1"
    got = hub.workflows.request("workflow.replay", {"name": "implement", "text": IMPL, "session": "conv-1"}, "me")
    assert got["ok"] and got["differs"] == 0 and got["end"] == "fix"
    assert got["starts"] == [] and "after the save" in got["starts_note"]  # IMPL names the same starts as the file


MARKED = '''schema = 1
name = "w"
initial = "a"

[launch]
personas = ["triager"]
result = "comment"

[[start]]
on = "issue"
label = "Go"
ceiling = "Reads the issue."
[[start]]
id = "w-b"
on = "issue"
label = "Later"
state = "b"
ceiling = "Reads the issue."

[state.a]
[state.a.grant]
hub_tools = ["get_issue"]
[[state.a.exit]]
to = "b"
decided_by = "hand"

[state.b]
[state.b.grant]
hub_tools = ["get_issue"]
[[state.b.exit]]
to = "c"
decided_by = "hand"

[state.c]
final = true
'''


def test_a_change_to_the_starts_marks_what_it_grants_or_moves():
    """A start whose session begins holding more, one on another kind of item, a lead taken, and a starting grant that writes
    on the item differently under the same ceiling words are each marked; a change that only edits a summary isn't."""
    marks = lambda b: [m["text"] for m in machinestore.start_marks(MARKED, b)]  # noqa: E731
    assert marks(MARKED.replace('label = "Go"', 'label = "Go"\nsummary = "Begins."')) == []
    wider = MARKED.replace('[state.b.grant]\nhub_tools = ["get_issue"]', '[state.b.grant]\nhub_tools = ["get_issue", "comment_issue"]')
    got = marks(wider)
    assert any(t.startswith("wider start: Later begins in b") and "comment_issue" in t for t in got), got
    assert any(t.startswith("ceiling unchanged: Later writes on its item (comment_issue)") for t in got), got
    assert not any("Go" in t for t in got)
    assert marks(MARKED.replace('on = "issue"\nlabel = "Go"', 'on = "pr"\nlabel = "Go"')) == ["another item: Go now starts on a pr, not an issue"]
    assert marks(MARKED.replace('label = "Go"', 'label = "Go"\nlead = true')) == ["lead: Go now leads the starts of an issue"]
    # a start moved to a state that holds more is marked against where it began
    moved = wider.replace('label = "Go"', 'label = "Go"\nstate = "b"')
    got = marks(moved)
    assert any(t.startswith("wider start: Go begins in b") for t in got), got
    # every mark reaches the proposal card's list as new
    full = machinestore.sensitive_marks(MARKED, [], wider)
    assert {m["where"] for m in full} == {"start.w-b"} and all(m["new"] for m in full)
