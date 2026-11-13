# SPDX-License-Identifier: GPL-2.0-or-later
"""What a workflow move does to the running session (012 FR-020 to FR-024): its next turn's instructions, a grant that narrows
at once, one that widens only through a resume after the maintainer's confirm, a move that can't take effect failing back,
and a compaction queued for when it is idle. A one-state session is never touched."""
import asyncio
import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from hubd import agents as agents_module
from hubd import grant_hook
from hubd.agents import GRANT_FILE, IDLE_FILE, OUTCOMES_FILE, AgentError, Agents, Library
from hubd.decisions import DecisionError, Decisions
from hubd.effects import FAILED_SIGNAL, LABEL, Effects

REPO = Path(__file__).resolve().parents[1]
ACTION = "knowledge-research"
TOOLS = ["docs_search", "work_search", "get_issue", "submit_result", "comment_issue"]

WORKFLOW = f'''schema = 1
name = "{ACTION}"
initial = "research"

[state.research]
instructions = "Find what the docs say."
[state.research.grant]
tools = ["AskUserQuestion", "Read"]
hub_tools = {json.dumps(TOOLS)}
checkout = false
all_repos = true
[[state.research.exit]]
to = "write"
decided_by = "hand"
[[state.research.exit]]
to = "wide"
decided_by = "hand"

[state.write]
instructions = "Write the report now."
context = "compact"
focus = "the findings so far"
[state.write.grant]
tools = ["AskUserQuestion"]
hub_tools = ["docs_search", "submit_result", "comment_issue"]
checkout = false
all_repos = true
[[state.write.exit]]
to = "wide"
decided_by = "hand"

[state.wide]
instructions = "Look at the pull requests too."
[state.wide.grant]
tools = ["AskUserQuestion", "Read"]
hub_tools = {json.dumps([*TOOLS, "list_prs", "merge_pr"])}
checkout = false
all_repos = true
[[state.wide.exit]]
to = "write"
decided_by = "hand"
[[state.wide.exit]]
to = "full"
decided_by = "hand"

[state.full]
final = true
[state.full.grant]
access = "full"
permission_mode = "auto"
checkout = false
'''


class FakeShells:
    def __init__(self):
        self.live, self.made, self.killed, self.pasted = set(), [], [], []

    async def list(self):
        return [{"name": n, "cwd": ""} for n in self.live]

    async def new(self, name, cwd, command):
        self.live.add(name)
        self.made.append((name, command))

    async def kill(self, name):
        self.live.discard(name)
        self.killed.append(name)

    async def prompt_empty(self, name):
        return True

    async def paste(self, name, text):
        self.pasted.append((name, text))


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(agents_module, "SANDBOX_TOOLS", ())
    root = tmp_path / "agents"
    shutil.copytree(REPO / "agents", root)
    (root / "workflows" / f"{ACTION}.toml").write_text(WORKFLOW)
    claude = tmp_path / "claude"
    claude.write_text("#!/bin/sh\n")
    claude.chmod(0o755)
    a = Agents(Library(root), FakeShells(), tmp_path / "state", claude=str(claude), mcp_url="u", agent_token="t",
               workspace=tmp_path / "ws")
    decisions = Decisions(tmp_path / "decisions")
    decisions.session_id_of = a.session_id_of
    effects = Effects(a, decisions, relaunch_wait=5, poll=0.01)
    return a, decisions, effects


def run(coroutine):
    return asyncio.run(coroutine)


async def start(a) -> str:
    return (await a.start(a.defaults(ACTION, None, None)))["name"]


def scope_of(a, name) -> dict:
    token = (a.sessions / name / agents_module.TOKEN_FILE).read_text().strip()
    return a.scope(token)


def grant_of(a, name) -> dict:
    path = a.sessions / name / GRANT_FILE
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    return json.loads(path.read_text())


def hook(a, name, tool) -> str:
    """grant_hook.py as Claude Code runs it: the event on stdin, what it prints back."""
    command = json.loads((a.sessions / name / "settings.json").read_text())["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert "grant_hook.py" in command
    out = subprocess.run([sys.executable, "-I", str(Path(grant_hook.__file__)), str(a.sessions / name / GRANT_FILE)],
                         input=json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool}), capture_output=True, text=True, check=True)
    return out.stdout


def confirm(a, decisions, effects, name, to) -> dict:
    """A move that waits for the maintainer, and their yes on its card."""
    assert a.machines.move(name, to, "hand")["needs_confirm"]
    card, = decisions.open_widenings(name)
    return effects.answer(card["id"], True, "me")


def told(a, name) -> str:
    try:
        return (a.sessions / name / OUTCOMES_FILE).read_text()
    except FileNotFoundError:
        return ""


def test_a_session_that_can_move_starts_with_its_first_states_grant_and_the_hook(world):
    a, _d, _e = world
    name = run(start(a))
    assert grant_of(a, name) == {"tools": ["AskUserQuestion", "Read"], "hub_tools": TOOLS, "server": agents_module.HUB_SERVER}
    assert hook(a, name, "mcp__glassine-hub__get_issue") == ""
    assert json.loads(hook(a, name, "Bash"))["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_a_one_state_session_has_no_grant_file_and_no_hook(world):
    a, _d, _e = world
    name = run(a.start(a.defaults("notes-sweep", None, None)))["name"]
    assert not (a.sessions / name / GRANT_FILE).exists()
    settings = (a.sessions / name / "settings.json").read_text()
    assert "grant_hook.py" not in settings


def test_a_narrowing_move_tells_the_session_and_takes_its_tools_at_once(world):
    a, _d, effects = world

    async def go():
        name = await start(a)
        result = a.machines.move(name, "write", "hand", who="me")
        assert result["moved"] and not result["widening"]
        await effects.drain()
        return name
    name = run(go())
    assert told(a, name) == f"{LABEL} Workflow: now in write. Write the report now.\n"
    assert scope_of(a, name)["tools"] == ["docs_search", "submit_result", "comment_issue"]
    assert grant_of(a, name)["tools"] == ["AskUserQuestion"]
    denied = json.loads(hook(a, name, "mcp__glassine-hub__work_search"))["hookSpecificOutput"]
    assert denied["permissionDecision"] == "deny" and "work_search" in denied["permissionDecisionReason"]
    assert json.loads(hook(a, name, "Read"))["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert hook(a, name, "mcp__glassine-hub__docs_search") == ""
    record = json.loads((a.sessions / name / "session.json").read_text())
    assert record["config"]["hub_tools"] == ["docs_search", "submit_result", "comment_issue"]
    assert record["launched"]["hub_tools"] == TOOLS
    assert a.shells.killed == []  # no new launch for a narrowing


def test_a_narrowing_holds_after_hubd_starts_again(world):
    a, _d, effects = world

    async def go():
        name = await start(a)
        a.machines.move(name, "write", "hand")
        await effects.drain()
        return name
    name = run(go())
    again = Agents(a.library, FakeShells(), a.state, claude=a.claude, mcp_url="u", agent_token="t", workspace=a.workspace)
    assert scope_of(again, name)["tools"] == ["docs_search", "submit_result", "comment_issue"]


def test_compact_is_queued_for_when_the_session_is_idle(world):
    a, _d, effects = world

    async def go():
        name = await start(a)
        a.machines.move(name, "write", "hand")
        await effects.drain()
        assert a._sends[name] == ["/compact the findings so far"]  # it's working: the compaction waits
        (a.sessions / name / IDLE_FILE).touch()
        await a._send_next(name)
        return name
    name = run(go())
    assert a.shells.pasted == [(name, "/compact the findings so far")]


def test_a_widening_move_waits_for_a_confirm_in_needs_you_and_resumes_under_the_new_grant(world):
    a, decisions, effects = world

    async def go():
        name = await start(a)
        result = a.machines.move(name, "wide", "hand", who="me")
        assert result["needs_confirm"] and not result["moved"]
        await effects.drain()
        card, = decisions.open_widenings(name)
        assert card["kind"] == "machine.widen" and card["asked_by"] == name
        assert card["scope"]["from"] == "research" and card["scope"]["to"] == "wide"
        assert card["scope"]["adds"] == {"hub_tools": ["list_prs", "merge_pr"]}
        assert card["scope"]["sensitive"] == {"merge_pr": "merging to the default branch"}
        assert "Workflow move" in decisions.view(card)["says"]
        assert scope_of(a, name)["tools"] == TOOLS and told(a, name) == ""  # nothing changes before the confirm
        ended = effects.answer(card["id"], True, "me", "fine")
        assert ended["state"] == "ended" and ended["approved"] and ended["words"] == "fine"
        assert a.machines.load(name)[1].state == "wide"
        await asyncio.sleep(0.05)
        assert a.shells.killed == []  # mid-turn: it waits for the prompt
        (a.sessions / name / IDLE_FILE).touch()
        await effects.drain()
        return name
    name = run(go())
    assert a.shells.killed == [name] and len(a.shells.made) == 2 and "--resume" in (a.sessions / name / "resume.sh").read_text()
    assert scope_of(a, name)["tools"] == [*TOOLS, "list_prs", "merge_pr"]
    assert "list_prs" in grant_of(a, name)["hub_tools"]
    assert "mcp__glassine-hub__list_prs" in (a.sessions / name / "resume.sh").read_text()
    assert told(a, name) == f"{LABEL} Workflow: now in wide. Look at the pull requests too.\n"


def test_saying_no_keeps_the_session_where_it_was(world):
    a, decisions, effects = world

    async def go():
        name = await start(a)
        a.machines.move(name, "wide", "hand")
        card, = decisions.open_widenings(name)
        ended = effects.answer(card["id"], False, "me", "not now")
        await effects.drain()
        assert ended["why_ended"] == "you said no: not now" and "approved" not in ended
        with pytest.raises(DecisionError, match="isn't waiting"):
            effects.answer(card["id"], True, "me")
        return name
    name = run(go())
    assert a.machines.load(name)[1].state == "research" and a.shells.killed == [] and scope_of(a, name)["tools"] == TOOLS


def test_a_card_is_answered_through_the_machine_not_as_a_decision(world):
    a, decisions, _effects = world

    async def go():
        name = await start(a)
        a.machines.move(name, "wide", "hand")
        return name, decisions.open_widenings(name)[0]
    name, card = run(go())
    for move in (lambda: decisions.approve(card["id"]), lambda: decisions.deny(card["id"]), lambda: decisions.end(card["id"], None)):
        with pytest.raises(DecisionError):
            move()
    with pytest.raises(DecisionError):
        decisions.request("machine.widen", {"session": name}, "let me", name)


def test_a_confirm_in_the_machine_panel_ends_the_card(world):
    a, decisions, effects = world

    async def go():
        name = await start(a)
        pending = a.machines.move(name, "wide", "hand")["pending"]
        card, = decisions.open_widenings(name)
        a.machines.confirm_move(name, pending, "me", accept=False)
        await effects.drain()
        return decisions.view(decisions._get(card["id"]))
    assert run(go())["why_ended"] == "you said no"


def test_moving_back_into_a_grant_already_confirmed_resumes_without_asking(world):
    a, decisions, effects = world

    async def go():
        name = await start(a)
        confirm(a, decisions, effects, name, "wide")
        (a.sessions / name / IDLE_FILE).touch()
        await effects.drain()
        a.machines.move(name, "write", "hand")
        await effects.drain()
        assert scope_of(a, name)["tools"] == ["docs_search", "submit_result", "comment_issue"]
        (a.sessions / name / IDLE_FILE).touch()
        result = a.machines.move(name, "wide", "hand")
        assert result["moved"] and result["widening"]
        await effects.drain()
        return name
    name = run(go())
    assert decisions.open_widenings(name) == []
    assert a.shells.killed == [name, name] and scope_of(a, name)["tools"] == [*TOOLS, "list_prs", "merge_pr"]


def test_a_move_that_would_change_the_access_fails_back_and_is_logged(world):
    a, decisions, effects = world

    async def go():
        name = await start(a)
        confirm(a, decisions, effects, name, "wide")
        (a.sessions / name / IDLE_FILE).touch()
        await effects.drain()
        (a.sessions / name / OUTCOMES_FILE).unlink()
        result = a.machines.move(name, "full", "hand")
        assert result["needs_confirm"]
        await effects.drain()
        return name
    name = run(go())
    inst = a.machines.load(name)[1]
    assert inst.state == "wide" and inst.pending is None and decisions.open_widenings(name) == []
    assert "didn't happen: its action's access has changed. Still in wide." in told(a, name)
    failed, = [e for e in a.machines.log.history(a.session_id_of(name))["evaluations"] if e["signal"] == FAILED_SIGNAL]
    assert failed["failed"] and failed["state"] == "full" and "access" in failed["checks"][0]["value"]


def test_a_relaunch_the_resume_refuses_moves_the_session_back(world, monkeypatch):
    a, decisions, effects = world

    async def refuse(name, relaunch=False):
        raise AgentError(f"{name} can't resume: its checkout is gone")

    async def go():
        name = await start(a)
        monkeypatch.setattr(a, "resume", refuse)
        confirm(a, decisions, effects, name, "wide")
        (a.sessions / name / IDLE_FILE).touch()
        await effects.drain()
        return name
    name = run(go())
    assert a.machines.load(name)[1].state == "research"
    moves = a.machines.log.history(a.session_id_of(name))["moves"]
    assert [(m["from"], m["to"], m["by"], m["who"]) for m in moves][-1] == ("wide", "research", "rollback", "hub")
    assert "Look at the pull requests" not in told(a, name) and "its checkout is gone" in told(a, name)
    assert scope_of(a, name)["tools"] == TOOLS


def test_a_stopped_session_isnt_started_by_a_widening(world):
    a, decisions, effects = world

    async def go():
        name = await start(a)
        a.shells.live.clear()
        confirm(a, decisions, effects, name, "wide")
        await effects.drain()
        return name
    name = run(go())
    assert a.shells.made[1:] == [] and "now in wide" in told(a, name)
    resumed = run(a.resume(name))  # its next resume has the new grant
    assert "list_prs" in resumed["config"]["hub_tools"]


def test_without_decisions_the_confirm_waits_in_the_machine_alone(world):
    a, _d, _e = world
    effects = Effects.__new__(Effects)
    a.machines._watchers.clear()
    Effects.__init__(effects, a, None)

    async def go():
        name = await start(a)
        return a.machines.move(name, "wide", "hand"), a.machines.view(*a.machines.load(name))
    result, view = run(go())
    assert view["instance"]["pending"]["id"] == result["pending"]


@pytest.mark.parametrize("grant, tool, refused", [
    ({"tools": ["Read"], "hub_tools": ["a"], "server": "s"}, "Read", False),
    ({"tools": ["Read"], "hub_tools": ["a"], "server": "s"}, "Write", True),
    ({"tools": ["Read"], "hub_tools": ["a"], "server": "s"}, "mcp__s__a", False),
    ({"tools": ["Read"], "hub_tools": ["a"], "server": "s"}, "mcp__s__b", True),
    ({"tools": ["Read"], "hub_tools": ["a"], "server": "s"}, "mcp__other__a", True),
    ({"tools": None, "hub_tools": None, "server": "s"}, "Anything", False),
])
def test_the_grant_hook_refuses_only_what_isnt_granted(grant, tool, refused):
    assert (grant_hook.decide(grant, tool) is not None) == refused


@pytest.mark.parametrize("content", [None, "not json", json.dumps({"tools": "Read", "hub_tools": [], "server": "s"}), json.dumps([])])
def test_the_grant_hook_refuses_when_it_cant_read_the_grant(tmp_path, content):
    path = tmp_path / GRANT_FILE
    if content is not None:
        path.write_text(content)
    out = subprocess.run([sys.executable, "-I", str(Path(grant_hook.__file__)), str(path)],
                         input=json.dumps({"tool_name": "Read"}), capture_output=True, text=True, check=True)
    assert json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_needs_you_answers_a_card_through_the_machine(world):
    from hubd import auth
    from hubd.server import Hubd
    a, decisions, _effects = world
    a.machines._watchers.clear()
    hubd = Hubd(None, a.shells, auth.Sessions(), "tok", agents=a, decision_store=decisions)

    async def go():
        name = await start(a)
        a.machines.move(name, "wide", "hand")
        card, = decisions.open_widenings(name)
        refused = await hubd.decision_request("decision.end", {"id": card["id"]})
        added = await hubd.decision_request("decision.add", {"kind": "machine.widen", "words": "yes", "scope": {"session": name}})
        answered = await hubd.interaction_request("interaction.answer", {"id": card["id"], "verdict": "deny", "why": "later"})
        await hubd.effects.drain()
        return name, refused, added, answered
    name, refused, added, answered = run(go())
    assert not refused["ok"] and not added["ok"]
    assert answered["ok"] and answered["item"]["status"] == "denied" and answered["item"]["detail"]["why_ended"] == "you said no: later"
    assert a.machines.load(name)[1].pending is None
