# SPDX-License-Identifier: GPL-2.0-or-later
"""Workflow instances: kept with the session, moved by hand, confirmed when they'd give something new, logged."""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_machine import IMPLEMENT, _with  # noqa: E402

from hubd import auth, instances, machine  # noqa: E402
from hubd.agents import ENDED_FILE, AgentError, Agents, Library  # noqa: E402
from hubd.instances import FILE, Instance, MachineError, confirm_move as confirm, definition_for, move, pause, rollback, version_of  # noqa: E402
from hubd.machine_log import Log, LogError  # noqa: E402
from hubd.server import Hubd  # noqa: E402

LIBRARY = Library(Path(__file__).resolve().parents[1] / "agents")


def new(text=IMPLEMENT, now=0.0):
    return Instance.new(text, now)


# --- the core ------------------------------------------------------------------------------------
def test_a_new_instance_enters_the_first_leaf_and_counts_its_first_round():
    inst = new()
    assert (inst.workflow, inst.state, inst.version) == ("implement", "implement", version_of(IMPLEMENT))
    assert inst.counters["rounds"] == {"implement": 1, "work": 1}
    assert inst.held["github"] == ["pr.read", "issues.comment", "push"] and inst.held["permission_mode"] == "acceptEdits"
    assert Instance.from_json(json.loads(json.dumps(inst.to_json()))) == inst


def test_moving_into_a_parent_enters_its_first_state_or_where_it_was():
    inst = new()
    assert move(inst, "review", "hand", now=1)["moved"]
    assert move(inst, "escalated", "hand", now=2)["to"] == "escalated"
    assert inst.history == {"work": "review"}
    assert move(inst, "work", "hand", enter="history", now=3)["to"] == "review"
    move(inst, "escalated", "hand", now=4)
    assert move(inst, "work", "hand", now=5)["to"] == "implement"


def test_history_falls_back_to_the_first_state_when_it_has_none():
    inst = new()
    move(inst, "escalated", "hand", now=1)
    inst.history.clear()
    assert move(inst, "work", "hand", enter="history", now=2)["to"] == "implement"


def test_rounds_count_the_state_and_its_parents_on_every_move():
    inst = new()
    for to in ("review", "fix", "review"):
        move(inst, to, "hand", now=1)
    assert inst.counters["rounds"] == {"work": 4, "implement": 1, "review": 2, "fix": 1}
    move(inst, "escalated", "hand", now=1)
    move(inst, "escalated", "hand", now=1)  # into itself is a round too
    assert inst.counters["rounds"]["escalated"] == 2 and inst.counters["rounds"]["work"] == 4


def test_time_is_counted_in_the_state_and_its_parents():
    inst = new(now=100)
    move(inst, "review", "hand", now=160)
    facts = inst.facts(now=200)
    assert facts["time.implement"] == 60 and facts["time.review"] == 40 and facts["time.work"] == 100
    instances.add_tokens(inst, 500)
    assert inst.facts(now=200)["tokens.work"] == 500 and inst.facts(now=200)["tokens.implement"] == 0


def test_a_move_to_a_capability_never_held_waits_for_a_confirm():
    inst = new()
    asked = move(inst, "merge-ready", "hand", who="me", now=1)
    assert asked["needs_confirm"] and not asked["moved"] and asked["adds"] == {"github": ["merge"]}
    assert asked["change"]["adds"] == {"github": ["merge"]} and "push" in asked["change"]["removes"]["github"]
    assert inst.state == "implement" and inst.pending["to"] == "merge-ready"
    with pytest.raises(MachineError, match="no move waits"):
        confirm(inst, "wrong", "me")
    done = confirm(inst, asked["pending"], "maintainer", now=2)
    assert done["moved"] and done["log"]["confirmed_by"] == "maintainer" and done["log"]["by"] == "hand"
    assert inst.state == "merge-ready" and "merge" in inst.held["github"] and inst.pending is None


def test_moving_back_into_a_confirmed_grant_doesnt_ask_again():
    inst = new()
    confirm(inst, move(inst, "merge-ready", "hand", now=1)["pending"], "m", now=2)
    move(inst, "escalated", "hand", now=3)
    again = move(inst, "merge-ready", "hand", now=4)
    assert again["moved"] and "needs_confirm" not in again


def test_a_checkout_held_before_doesnt_ask_again():
    text = IMPLEMENT.replace('[state.merge-ready.grant]\ngithub = ["merge"]', '[state.merge-ready.grant]\ncheckout = "new-branch"')
    inst = new(text)
    confirm(inst, move(inst, "merge-ready", "hand", now=1)["pending"], "m", now=2)
    assert move(inst, "work", "hand", now=3)["moved"]  # pr-branch again: held from the start
    assert move(inst, "merge-ready", "hand", now=4)["moved"]


def test_a_confirm_after_the_session_moved_is_refused():
    inst = new()
    asked = move(inst, "merge-ready", "hand", now=1)
    move(inst, "review", "hand", now=2)  # a move that gives nothing new goes on, and the old question no longer fits
    with pytest.raises(MachineError):
        confirm(inst, asked["pending"], "m")
    assert inst.state == "review"


def test_a_declined_confirm_doesnt_move():
    inst = new()
    asked = move(inst, "merge-ready", "hand", now=1)
    assert confirm(inst, asked["pending"], "m", accept=False)["declined"]
    assert inst.state == "implement" and inst.pending is None


def test_rollback_returns_to_the_state_before_and_keeps_the_counters():
    inst = new()
    with pytest.raises(MachineError, match="no move"):
        rollback(inst)
    move(inst, "review", "hand", now=1)
    move(inst, "fix", "hand", now=2)
    back = rollback(inst, "m", now=3)
    assert back["moved"] and back["to"] == "review" and back["log"]["by"] == "rollback"
    assert inst.counters["rounds"]["fix"] == 1 and inst.counters["rounds"]["review"] == 1
    assert rollback(inst, now=4)["to"] == "implement"
    with pytest.raises(MachineError):
        rollback(inst)


def test_rollback_follows_the_confirm_rule():
    inst = new()
    confirm(inst, move(inst, "merge-ready", "hand", now=1)["pending"], "m", now=2)
    inst.held = instances.held_of(machine.effective(inst.definition(), "merge-ready"))  # as if implement's push was never held
    asked = rollback(inst, "m", now=3)
    assert asked["needs_confirm"] and "push" in asked["adds"]["github"]
    done = confirm(inst, asked["pending"], "m", now=4)
    assert done["log"]["by"] == "rollback" and inst.state == "implement" and inst.trail == []


def test_pause_stops_the_machine_not_the_hand():
    inst = new()
    assert pause(inst, True, "m")["log"]["by"] == "pause"
    assert move(inst, "review", "machine") == {"moved": False, "paused": True}
    assert move(inst, "review", "hand", now=1)["moved"]
    assert pause(inst, True)["changed"] is False
    assert pause(inst, False, "m")["log"]["by"] == "resume"
    assert move(inst, "fix", "machine", now=2)["moved"]


def test_a_new_version_is_taken_at_the_next_move():
    inst = new()
    newer = _with(IMPLEMENT, 'instructions = "Implement the issue on your branch."', 'instructions = "Implement it."')
    move(inst, "review", "machine", latest=newer, now=1)
    assert inst.version == version_of(newer)
    assert rollback(inst, now=2)["to"] == "implement" and inst.version == version_of(IMPLEMENT)


def test_a_new_version_without_the_current_state_waits_for_a_move_by_hand():
    inst = new()
    move(inst, "fix", "hand", now=1)
    gone = _with(_with(IMPLEMENT, '[state.fix]\nparent = "work"\n[state.fix.grant]\npermission_mode = "acceptEdits"\ngithub = ["push"]\n'
                       '[[state.fix.exit]]\nto = "review"\ndecided_by = "judge"\nwhen = "Every finding has a fixup commit or a reply"\n'
                       'requires = ["pr.checks == pass"]\non = ["turn.end"]\n', ''),
                 'to = "fix"\ndecided_by = "facts"\nrequires = ["managed.reviewer.verdict == fail", "rounds.review < 3"]',
                 'to = "escalated"\ndecided_by = "facts"\nrequires = ["managed.reviewer.verdict == fail", "rounds.review < 3"]')
    assert "fix" not in machine.parse(gone).states
    move(inst, "review", "machine", latest=gone, now=2)
    assert inst.version == version_of(IMPLEMENT) and inst.kept
    move(inst, "escalated", "machine", latest=gone, now=2)  # review is in the newest text, but only a hand moves it there
    assert inst.version == version_of(IMPLEMENT)
    move(inst, "review", "hand", now=2)
    move(inst, "fix", "hand", latest=gone, now=3)  # only its own version has fix
    assert inst.state == "fix" and inst.version == version_of(IMPLEMENT)
    move(inst, "review", "hand", latest=gone, now=5)
    assert inst.version == version_of(gone) and not inst.kept and rollback(inst, now=6)["to"] == "fix"
    assert inst.version == version_of(IMPLEMENT)


def test_bad_moves_are_refused():
    inst = new()
    for to, enter in (("nowhere", "first"), (None, "first"), ("work", "last")):
        with pytest.raises(MachineError):
            move(inst, to, "hand", enter=enter)
    with pytest.raises(MachineError):
        move(inst, "review", "rollback")


@pytest.mark.parametrize("change", [
    lambda r: r.update(state="work"),                                       # a parent isn't a place to be
    lambda r: r.update(version="0" * 64),
    lambda r: r["definitions"].update({r["version"]: IMPLEMENT + "\n"}),   # text that isn't its hash
    lambda r: r["held"].update(access="root"),
    lambda r: r.update(extra=1),
])
def test_a_tampered_record_isnt_read(change):
    raw = json.loads(json.dumps(new().to_json()))
    change(raw)
    with pytest.raises(MachineError):
        Instance.from_json(raw)


def test_every_action_gives_a_one_state_definition_with_its_grant():
    for action in LIBRARY.actions.values():
        d = machine.parse(definition_for(action))
        g = machine.effective(d, "session")
        assert d.states["session"].final and g.tools == tuple(action["tools"]) and g.hub_tools == tuple(action["hub_tools"])
        assert g.checkout == action.get("checkout", False) and g.access == action.get("access", "locked")
        assert new(definition_for(action)).state == "session"


# --- the log --------------------------------------------------------------------------------------
def test_the_log_keeps_evaluations_and_moves_by_session(tmp_path):
    lg = Log(tmp_path / "m.sqlite", clock=lambda: 5.0)
    lg.evaluation("id-1", "s", "turn.end", "review", "v1", proposal="fix", evidence="it failed",
                  checks=[{"check": "rounds.review < 3", "value": 1, "holds": True}], judge="default", ms=120, cost=0.001)
    lg.evaluation("id-1", "s", "turn.end", "review", "v1", failed=True)
    lg.move("id-1", "s", "review", "fix", "machine", "v1", "v1", widening=True, change={"adds": {"tools": ["Edit"]}})
    lg.move("id-2", "s", "a", "b", "hand", who="m")
    h = lg.history("id-1")
    assert [e["failed"] for e in h["evaluations"]] == [False, True]
    assert h["evaluations"][0]["checks"][0]["value"] == 1 and h["evaluations"][0]["cost"] == 0.001
    assert [(m["from"], m["to"], m["by"], m["widening"]) for m in h["moves"]] == [("review", "fix", "machine", True)]
    assert h["moves"][0]["change"] == {"adds": {"tools": ["Edit"]}}
    with pytest.raises(LogError):
        lg.move("id-1", "s", "a", "b", "someone")
    with pytest.raises(LogError):
        lg.evaluation("id-1", "s", "turn.end", "review", "v1", checks={1j})


# --- with sessions ---------------------------------------------------------------------------------
class FakeShells:
    def __init__(self):
        self.live = set()

    async def list(self):
        return [{"name": n} for n in self.live]

    async def new(self, name, cwd, command):
        self.live.add(name)

    async def kill(self, name):
        self.live.discard(name)


def git(cwd, *a):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def world(tmp_path):
    remote = tmp_path / "remote" / "boot"
    remote.mkdir(parents=True)
    git(remote, "init", "-q", "-b", "main")
    (remote / "a").write_text("a")
    git(remote, "add", "a")
    git(remote, "commit", "-qm", "base")
    claude = tmp_path / "claude"
    claude.write_text("#!/bin/sh\n")
    claude.chmod(0o755)
    a = Agents(LIBRARY, FakeShells(), tmp_path / "state", claude=str(claude), mcp_url="u", agent_token="t",
               clone_base=str(tmp_path / "remote") + "/", workspace=tmp_path / "ws", environment={"CLAUDE_CONFIG_DIR": str(tmp_path / "cc")})
    return a, tmp_path


def _session(a):
    return asyncio.run(a.start({**a.defaults("issue-implement", "boot", 1), "name": "s"}))["name"]


def _as_implement(a, name):
    """The session's machine put on a workflow with steps, as a later version of its action would be."""
    path = a.sessions / name / FILE
    path.write_text(json.dumps(new().to_json()))


def test_a_session_starts_with_its_machine(world):
    a, _ = world
    name = _session(a)
    raw = json.loads((a.sessions / name / FILE).read_text())
    assert raw["workflow"] == "issue-implement" and raw["state"] == "session"
    assert raw["definitions"][raw["version"]] == definition_for(LIBRARY.actions["issue-implement"])


def test_the_machine_survives_a_resume_and_a_resume_after_the_folder_went(world):
    a, tmp = world
    name = _session(a)
    _as_implement(a, name)
    hub = a.machines
    assert hub.request("machine.move", {"name": name, "to": "review"}, "m")["state"] == "review"
    a.shells.live.discard(name)
    asyncio.run(a.resume(name))
    assert hub.request("machine.get", {"name": name}, "m")["instance"]["state"] == "review"
    session_id = a.session_id_of(name)
    folder = tmp / "cc" / "projects" / "x"
    folder.mkdir(parents=True)
    (folder / f"{session_id}.jsonl").write_text(json.dumps({"type": "user", "message": {"content": "x"}}) + "\n")
    a.shells.live.discard(name)
    asyncio.run(a.forget(name))
    assert not (a.sessions / name).exists()
    asyncio.run(a.resume_past(session_id))
    got = hub.request("machine.get", {"name": name}, "m")
    assert got["instance"]["state"] == "review" and got["instance"]["counters"]["rounds"]["review"] == 1
    assert "machine" not in json.loads((a.sessions / name / "session.json").read_text())
    assert hub.request("machine.rollback", {"name": name}, "m")["state"] == "implement"
    assert [m["by"] for m in hub.request("machine.history", {"name": name}, "m")["moves"]] == ["hand", "rollback"]


def test_a_session_from_before_instances_gets_one(world):
    a, _ = world
    name = _session(a)
    (a.sessions / name / FILE).unlink()
    got = a.machines.request("machine.get", {"name": name}, "m")
    assert got["ok"] and got["instance"]["state"] == "session" and (a.sessions / name / FILE).exists()
    assert got["exits"] == [] and got["grant"]["checkout"] == "new-branch" and got["newer"] is None


def test_the_ops_move_confirm_pause_and_log_as_the_maintainer(world):
    a, _ = world
    name = _session(a)
    _as_implement(a, name)
    m = a.machines
    got = m.request("machine.get", {"name": name}, "m")
    assert [e["to"] for e in got["exits"]] == ["review", "escalated"] and got["facts"]["rounds.work"] == 1
    assert got["newer"] == {"version": version_of(definition_for(LIBRARY.actions["issue-implement"])), "has_state": False, "kept": False}
    asked = m.request("machine.move", {"name": name, "to": "merge-ready"}, "maintainer")
    assert asked["ok"] and asked["needs_confirm"] and asked["state"] == "implement"
    assert m.request("machine.get", {"name": name}, "m")["instance"]["pending"]["to"] == "merge-ready"
    assert m.request("machine.confirm", {"name": name, "pending": asked["pending"]}, "maintainer")["state"] == "merge-ready"
    assert m.request("machine.pause", {"name": name, "paused": True}, "maintainer")["paused"]
    assert not m.request("machine.pause", {"name": name, "paused": "yes"}, "maintainer")["ok"]
    assert "isn't a state" in m.request("machine.move", {"name": name, "to": "nowhere"}, "m")["error"]
    assert m.request("machine.move", {"name": "../etc", "to": "x"}, "m")["error"] == "no such session"
    moves = m.request("machine.history", {"name": name}, "m")["moves"]
    assert [(r["by"], r["who"], r["confirmed_by"]) for r in moves] == [("hand", "maintainer", "maintainer"), ("pause", "maintainer", None)]
    assert moves[0]["widening"] and moves[0]["change"]["adds"] == {"github": ["merge"]}


def test_a_hand_move_takes_the_newest_version(world):
    a, _ = world
    name = _session(a)
    _as_implement(a, name)
    asked = a.machines.request("machine.move", {"name": name, "to": "session"}, "m")
    assert asked["needs_confirm"] and asked["adds"]["access"] == ["full"]
    got = a.machines.request("machine.confirm", {"name": name, "pending": asked["pending"]}, "m")
    assert got["moved"] and got["version"] == version_of(definition_for(LIBRARY.actions["issue-implement"]))


def test_the_log_is_per_conversation_not_per_name(world):
    a, _ = world
    name = _session(a)
    _as_implement(a, name)
    a.machines.request("machine.move", {"name": name, "to": "review"}, "m")
    a.shells.live.discard(name)
    asyncio.run(a.forget(name))
    again = _session(a)
    assert again == name and a.machines.request("machine.history", {"name": name}, "m")["moves"] == []


def test_the_ops_need_the_maintainers_login(world):
    a, _ = world
    name = _session(a)
    sessions = auth.Sessions()
    hub = Hubd(None, None, sessions, "general", agents=a)
    token = (a.sessions / name / "tool-token").read_text().strip()
    for op in instances.OPS:
        for req in ({}, {"agent_token": token}, {"agent_token": "general"}, {"token": "wrong"}):
            reply = asyncio.run(hub.request({"op": op, "name": name, "to": "session", "paused": True, **req}))
            assert reply["denied"] and not reply["ok"], (op, req)
    reply = asyncio.run(hub.request({"op": "machine.get", "name": name, "token": sessions.create()}))
    assert reply["ok"] and reply["instance"]["state"] == "session"
    assert asyncio.run(hub.request({"op": "machine.nope", "name": name, "token": sessions.create()}))["error"].startswith("unknown")


def test_a_machine_move_through_the_service_is_saved_and_logged(world):
    a, _ = world
    name = _session(a)
    _as_implement(a, name)
    assert a.machines.move(name, "review")["state"] == "review"
    assert json.loads((a.sessions / name / FILE).read_text())["state"] == "review"
    assert [(m["by"], m["who"]) for m in a.machines.request("machine.history", {"name": name}, "m")["moves"]] == [("machine", None)]
    a.machines.pause(name, True, "m")
    assert a.machines.move(name, "fix")["paused"] and a.machines.load(name)[1].state == "review"


def test_time_spent_ended_isnt_time_in_the_state(world):
    a, tmp = world
    clock = [1000.0]
    a.machines.clock = lambda: clock[0]
    name = _session(a)
    session_id = a.session_id_of(name)
    folder = tmp / "cc" / "projects" / "x"
    folder.mkdir(parents=True)
    (folder / f"{session_id}.jsonl").write_text(json.dumps({"type": "user", "message": {"content": "x"}}) + "\n")
    clock[0] = 1100.0
    a.shells.live.discard(name)
    asyncio.run(a.forget(name))
    clock[0] = 90000.0
    asyncio.run(a.resume_past(session_id))
    clock[0] = 90010.0
    assert a.machines.request("machine.get", {"name": name}, "m")["facts"]["time.session"] == 110


def test_the_clock_stops_while_paused():
    inst = new(now=0)
    pause(inst, True, now=10)
    assert inst.facts(now=100)["time.implement"] == 10
    pause(inst, False, now=100)
    move(inst, "review", "hand", now=105)
    assert inst.facts(now=105)["time.implement"] == 15


def test_the_clock_stops_when_the_session_ends_and_runs_again_on_resume(world):
    a, _ = world
    clock = [1000.0]
    a.machines.clock = lambda: clock[0]
    name = _session(a)
    ended = a.sessions / name / "ended"
    ended.touch()
    os.utime(ended, (1030, 1030))
    clock[0] = 5000.0
    assert a.machines.request("machine.get", {"name": name}, "m")["facts"]["time.session"] == 30
    a.shells.live.discard(name)
    asyncio.run(a.resume(name))
    clock[0] = 5020.0
    assert a.machines.request("machine.get", {"name": name}, "m")["facts"]["time.session"] == 50


def test_a_session_found_stopped_stops_its_clock(world):
    a, _ = world
    clock = [1000.0]
    a.machines.clock = lambda: clock[0]
    name = _session(a)
    a.shells.live.discard(name)  # its terminal went, with no marker: after a reboot
    clock[0] = 1040.0
    assert [s["name"] for s in asyncio.run(a.stopped())] == [name]
    clock[0] = 9000.0
    assert a.machines.request("machine.get", {"name": name}, "m")["facts"]["time.session"] == 40


def test_a_start_on_a_bad_workflow_is_an_agent_error(world, monkeypatch):
    a, _ = world
    monkeypatch.setattr(instances, "definition_for", lambda action: 'schema = 1\nname = "x"\ninitial = "nowhere"\n[state.a]\nfinal = true\n')
    with pytest.raises(AgentError, match="can't start: its workflow the definition has problems: .*nowhere"):
        _session(a)
    assert not (a.sessions / "s").exists()


def test_the_ended_marker_is_the_agents_own():
    assert instances.ENDED == ENDED_FILE


def test_token_only_capability_names_stay_out_of_the_grant():
    action = {**LIBRARY.actions["pr-review"], "github": ["read", "pr.read", "runs.read"]}
    assert machine.effective(machine.parse(definition_for(action)), "session").github == ("pr.read",)
