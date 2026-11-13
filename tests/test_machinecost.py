# SPDX-License-Identifier: GPL-2.0-or-later
"""What a piece of work cost (012 FR-090) and how fast a signal became a move (SC-003): sessions at once, judge calls,
tokens and cost banked per state from the status line, overrides by hand, and the latency the runner logs. A real Agents,
Machines and Runner; the terminal and the judge are fakes, and nothing waits longer than a debounce of zero."""
import asyncio
import json
import shutil
import time
from pathlib import Path

import pytest

from hubd import agents as agents_module
from hubd import judge as judgelib
from hubd import machinerun, summary
from hubd.agents import Agents, Library
from hubd.machinecost import Costs, overrides

REPO = Path(__file__).resolve().parents[1]
ACTION = "issue-triage"
WORKFLOW = '''schema = 1
name = "issue-triage"
initial = "look"

[state.look]
[state.look.grant]
tools = ["AskUserQuestion"]
hub_tools = ["get_issue", "notes_find"]
checkout = false
[[state.look.exit]]
to = "done"
decided_by = "judge"
when = "The issue is understood."
on = ["turn.end"]

[state.done]
[state.done.grant]
tools = ["AskUserQuestion"]
hub_tools = ["get_issue", "notes_find"]
checkout = false
[[state.done.exit]]
to = "look"
decided_by = "hand"
'''


class FakeShells:
    def __init__(self):
        self.live = set()

    async def list(self):
        return [{"name": n, "cwd": ""} for n in self.live]

    async def new(self, name, cwd, command):
        self.live.add(name)

    async def kill(self, name):
        self.live.discard(name)


class Judge(judgelib.Judge):
    provider, model = "fake", "fixed"

    async def complete(self, system, user, schema):
        if schema is summary.FOLD_SCHEMA:
            return {"summary": "s"}, 0.0
        return {"exit": 0, "evidence": "The issue is understood", "confidence": 0.9}, 0.002


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(agents_module, "SANDBOX_TOOLS", ())
    root = tmp_path / "agents"
    shutil.copytree(REPO / "agents", root)
    (root / "workflows" / f"{ACTION}.toml").write_text(WORKFLOW)
    claude = tmp_path / "claude"
    claude.write_text("#!/bin/sh\n")
    claude.chmod(0o755)
    a = Agents(Library(root), FakeShells(), tmp_path / "state", claude=str(claude), mcp_url="u", agent_token="t", workspace=tmp_path / "ws")
    clock = Clock()
    a.machines.clock = clock
    a.machines.log._clock = clock

    async def sleep(_s):
        clock.now += 0.25  # what the pass's own work takes, on the fake clock
    runner = machinerun.Runner(a.machines, judges=lambda: {"default": Judge()}, names=lambda: [p.name for p in a.sessions.iterdir()],
                               debounce=0.0, sleep=sleep)
    return a, runner, clock


def status(a, name, tokens_in, tokens_out, cost):
    sid = a.session_id_of(name)
    (a.sessions / name / "status.json").write_text(json.dumps({"session_id": sid, "cost": {"total_cost_usd": cost},
                                                               "context_window": {"total_input_tokens": tokens_in, "total_output_tokens": tokens_out}}))


def test_overrides_are_hand_moves_that_replace_or_undo_a_machines():
    m = lambda at, by, who=None: {"at": at, "by": by, "who": who}  # noqa: E731
    assert overrides([m(0, "machine"), m(30, "rollback", "me")]) == (1, 1)
    assert overrides([m(0, "machine"), m(30, "hand", "me")]) == (1, 1)
    assert overrides([m(0, "machine"), m(3600, "hand", "me")]) == (0, 1)  # long after: a move of its own
    assert overrides([m(0, "machine"), m(5, "rollback", "hub")]) == (0, 1)  # the hub's move back isn't an override
    assert overrides([m(0, "machine"), m(1, "pause", "me"), m(2, "hand", "me"), m(3, "hand", "me")]) == (1, 1)
    assert overrides([m(0, "hand", "me")]) == (0, 0)


def test_a_signal_becomes_a_move_well_inside_ten_seconds_and_the_costs_say_so(world):
    """SC-003 with fakes: the turn's end to the move logged, the judge's time included, on the runner's own clock."""
    a, runner, clock = world

    async def go():
        name = (await a.start(a.defaults(ACTION, "boot", 7)))["name"]
        status(a, name, 1000, 200, 0.5)
        (a.sessions / name / summary.SUMMARY_FILE).write_text("The issue is understood now.")
        assert runner.signal("turn.end", name) == [name]
        await runner.idle()
        return name
    name = asyncio.run(go())
    _r, inst = a.machines.load(name)
    assert inst.state == "done"
    [moved] = [e for e in a.machines.log.history(a.session_id_of(name))["evaluations"] if e["checks"].get("move", {}).get("moved")]
    assert 0 < moved["checks"]["latency_ms"] < 10000
    got = Costs(a, clock=clock).request({"session": name})
    assert got["ok"] and got["judge_calls"] == 1 and got["judge_cost"] > 0
    assert got["latency"]["count"] == 1 and got["latency"]["max_ms"] < 10000 and got["latency"]["debounce_s"] == 2.0
    assert got["latency"]["pr_lookup_every_s"] == 60
    # the turn's tokens and cost were spent in look, banked before the move
    assert got["sessions"][0]["tokens"] == 1200 and got["sessions"][0]["cost"] == 0.5
    look = next(s for s in got["sessions"][0]["states"] if s["state"] == "look")
    assert look["tokens"] == 1200 and look["cost"] == 0.5


def test_tokens_bank_per_state_and_a_drop_counts_again(world):
    a, _runner, clock = world

    async def go():
        return (await a.start(a.defaults(ACTION, "boot", 7)))["name"]
    name = asyncio.run(go())
    status(a, name, 100, 0, 0.1)
    a.machines.move(name, "done", "hand", who="me")
    status(a, name, 300, 0, 0.3)
    a.machines.bank(name)
    status(a, name, 50, 0, 0.05)  # a /clear: the conversation counts from zero
    a.machines.bank(name)
    facts = a.machines.load(name)[1].facts(clock())
    assert facts["tokens.look"] == 100 and facts["tokens.done"] == 250
    (a.sessions / name / "status.json").write_text(json.dumps({"session_id": "another", "context_window": {"total_input_tokens": 9}}))
    a.machines.bank(name)  # another conversation's file isn't this one's
    assert a.machines.load(name)[1].facts(clock())["tokens.done"] == 250


def test_a_piece_of_work_counts_its_managed_sessions_and_the_most_at_once(world):
    a, _runner, clock = world
    clock.now = time.time()  # the sessions' start times are the wall clock's

    async def go():
        owner = (await a.start(a.defaults(ACTION, "boot", 7)))["name"]
        child = (await a.start(a.defaults(ACTION, "boot", 7), owner={"name": owner, "session_id": a.session_id_of(owner), "entry": "x"}))["name"]
        lone = (await a.start(a.defaults(ACTION, "boot", 8)))["name"]
        return owner, child, lone
    owner, child, lone = asyncio.run(go())
    a.machines.move(owner, "done", "hand", who="me")
    clock.now += 10
    a.machines.move(owner, "look", "hand", who="me")
    got = Costs(a, clock=clock).request({"session": owner})
    assert sorted(s["name"] for s in got["sessions"]) == sorted([owner, child]) and got["at_once"] == 2
    assert got["machine_moves"] == 0 and got["override_rate"] is None
    item = Costs(a, clock=clock).request({"repo": "boot", "number": 7})
    assert [p["session"] for p in item["pieces"]] == [owner]  # the child is in its owner's piece, not one of its own
    every = Costs(a, clock=clock).request({"workflows": True})["workflows"]
    assert every[0]["workflow"] == "issue-triage" and every[0]["sessions"] == 3
    assert Costs(a).request({})["ok"] is False and lone


def test_only_a_login_reads_the_costs(world, tmp_path):
    a, runner, _clock = world
    from hubd import auth
    from hubd.server import Hubd

    class Gh:
        def available(self):
            return True

    h = Hubd(Gh(), a.shells, auth.Sessions(), "shared", agents=a, machine_run=runner)
    got = asyncio.run(h.request({"op": "machine.costs", "workflows": True}))
    assert got["denied"]
    got = asyncio.run(h.request({"op": "machine.costs", "agent_token": "shared", "workflows": True}))
    assert got.get("denied")


def test_a_change_that_fails_keeps_what_it_would_have_banked_for_the_next_look(world):
    from hubd.instances import MachineError
    a, _runner, clock = world

    async def go():
        return (await a.start(a.defaults(ACTION, "boot", 7)))["name"]
    name = asyncio.run(go())
    status(a, name, 100, 0, 0.1)
    with pytest.raises(MachineError):
        a.machines.move(name, "nowhere", "hand", who="me")
    a.machines.bank(name)
    assert a.machines.load(name)[1].facts(clock())["tokens.look"] == 100


def test_a_resumed_process_counts_its_status_line_from_zero(world):
    """The totals restart with each process (unverified against real claude): 150 after a resume is 150 more, not 50."""
    a, _runner, clock = world

    async def go():
        name = (await a.start(a.defaults(ACTION, "boot", 7)))["name"]
        status(a, name, 100, 0, 0.1)
        a.machines.bank(name)
        a.shells.live.discard(name)
        (a.sessions / name / agents_module.ENDED_FILE).touch()
        await a.resume(name)
        status(a, name, 150, 0, 0.2)
        a.machines.bank(name)
        return name
    name = asyncio.run(go())
    assert a.machines.load(name)[1].facts(clock())["tokens.look"] == 250
