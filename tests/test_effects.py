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

from starts_util import with_launch
from hubd import agents as agents_module
from hubd import decisions as decisions_module
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
    (root / "workflows" / f"{ACTION}.toml").write_text(with_launch(WORKFLOW, ACTION))
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
    """Its token's scope, with the grant's tools alone: every session whose workflow can move also has report_up, from where it
    stands in the chain of owners rather than from its state (tested once, below)."""
    token = (a.sessions / name / agents_module.TOKEN_FILE).read_text().strip()
    scope = a.scope(token)
    if scope.get("tools") is None or scope["tools"] == []:  # full, or locked down
        return scope
    assert "report_up" in scope["tools"]
    return {**scope, "tools": [t for t in scope["tools"] if t not in agents_module.CHAIN_TOOLS]}


def grant_of(a, name) -> dict:
    path = a.sessions / name / GRANT_FILE
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    return json.loads(path.read_text())


def hook(a, name, tool) -> str | None:
    """The installed command as Claude Code runs it, through the shell with the event on stdin: the reason it blocks with
    (exit 2, on stderr), or None when it lets the tool through (exit 0, nothing said)."""
    command = json.loads((a.sessions / name / "settings.json").read_text())["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert "grant_hook.py" in command
    out = subprocess.run(["sh", "-c", command], input=json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool}),
                         capture_output=True, text=True)
    assert out.returncode in (0, 2) and out.stdout == ""
    return out.stderr.strip() if out.returncode == 2 else None


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
    # report_up comes from its place in the chain of owners: a session whose workflow can move reports up (012 FR-051) and can take
    # back what it reported (withdraw_report)
    assert grant_of(a, name) == {"tools": ["AskUserQuestion", "Read"], "hub_tools": [*TOOLS, "report_up", "withdraw_report"], "server": agents_module.HUB_SERVER}
    assert hook(a, name, "mcp__glassine-hub__get_issue") is None
    assert "Bash" in hook(a, name, "Bash")


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
    assert "work_search isn't granted" in hook(a, name, "mcp__glassine-hub__work_search")
    assert hook(a, name, "Read") is not None
    assert hook(a, name, "mcp__glassine-hub__docs_search") is None
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
                         input=json.dumps({"tool_name": "Read"}), capture_output=True, text=True)
    assert out.returncode == 2 and out.stderr.strip()


def test_a_grant_hook_that_cant_run_blocks(world):
    """Any other exit status lets the tool through in Claude Code, so the installed command turns a failure to run into 2."""
    a, _d, _e = world
    name = run(start(a))
    path = a.sessions / name / "settings.json"
    settings = json.loads(path.read_text())
    entry = settings["hooks"]["PreToolUse"][0]["hooks"][0]
    entry["command"] = entry["command"].replace(sys.executable, "/nonexistent/python", 1)
    path.write_text(json.dumps(settings))
    assert hook(a, name, "mcp__glassine-hub__get_issue") is not None


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


def test_a_rolled_back_move_that_cant_take_effect_returns_to_where_it_was(world, monkeypatch):
    a, decisions, effects = world

    async def refuse(name, relaunch=False):
        raise AgentError(f"{name} can't resume: the network is down")

    async def go():
        name = await start(a)
        confirm(a, decisions, effects, name, "wide")
        (a.sessions / name / IDLE_FILE).touch()
        await effects.drain()
        a.machines.move(name, "write", "hand")
        await effects.drain()
        monkeypatch.setattr(a, "resume", refuse)
        (a.sessions / name / IDLE_FILE).touch()
        assert a.machines.rollback(name, "me")["state"] == "wide"
        await effects.drain()
        return name
    name = run(go())
    assert a.machines.load(name)[1].state == "write"  # not research, the move before
    assert scope_of(a, name)["tools"] == ["docs_search", "submit_result", "comment_issue"]


def test_a_narrowed_github_token_that_cant_be_made_leaves_none(world, monkeypatch):
    a, _d, effects = world

    async def fails(directory, config, action):
        raise AgentError("GitHub didn't answer")

    async def go():
        name = await start(a)
        folder = a.sessions / name / agents_module.GITHUB_FOLDER
        folder.mkdir()
        (folder / "token").write_text("wide")
        monkeypatch.setattr(a, "_github_token", fails)
        await effects._renew_token(name, {}, {})
        return folder
    assert not run(go()).exists()


def test_sensitive_marks_cover_what_asks_first_too():
    from hubd.effects import sensitive_of
    from hubd.machine import Grant
    assert sensitive_of({"asks_first": ["merge_pr"]}, Grant()) == {"merge_pr": "merging to the default branch"}
    assert "access" in sensitive_of({}, Grant(access="full"))


# --- what the review found ------------------------------------------------------------------------
def test_a_move_while_a_resume_is_set_up_isnt_overwritten_by_the_old_state(world, monkeypatch):
    a, _d, effects = world
    real = a._github_for
    moved, names = [], []

    async def slow(config, action):
        if not moved:  # GitHub is asked while the session moves on
            moved.append(a.machines.move(names[0], "write", "hand"))
        return await real(config, action)

    async def go():
        name = await start(a)
        names.append(name)
        a.shells.live.clear()
        monkeypatch.setattr(a, "_github_for", slow)
        resumed = await a.resume(name)
        await effects.drain()
        return name, resumed
    name, resumed = run(go())
    assert moved[0]["moved"]
    want = ["docs_search", "submit_result", "comment_issue"]
    assert resumed["config"]["hub_tools"] == want and scope_of(a, name)["tools"] == want
    assert grant_of(a, name)["tools"] == ["AskUserQuestion"]
    assert json.loads((a.sessions / name / "session.json").read_text())["config"]["hub_tools"] == want


def test_a_lost_or_unreadable_machine_of_a_session_that_can_move_is_refused(world):
    from hubd.instances import FILE, UNREADABLE, MachineError
    a, _d, _e = world
    name = run(start(a))
    a.shells.live.clear()
    (a.sessions / name / FILE).unlink()
    with pytest.raises(MachineError, match="missing"):
        a.machines.load(name)
    with pytest.raises(AgentError, match="which state"):
        run(a.resume(name))
    (a.sessions / name / FILE).write_text("not json")
    record = {**json.loads((a.sessions / name / "session.json").read_text()), **a.machines.remembered(a.sessions / name)}
    assert record[UNREADABLE] is True
    with pytest.raises(MachineError):
        a.machines.restore(a.sessions / name, record)
    one = run(a.start(a.defaults("notes-sweep", None, None)))["name"]  # a one-state session still gets one made
    (a.sessions / one / FILE).unlink()
    assert a.machines.load(one)[1].state == "session"


def test_whether_a_session_can_move_is_its_machines_definition(world):
    from hubd.instances import FILE, Instance
    a, _d, _e = world
    name = run(start(a))
    action = a.library.action(ACTION)
    assert a.staged(action, name)
    one = (REPO / "agents" / "workflows" / f"{ACTION}.toml").read_text()  # its machine on a one-state version
    (a.sessions / name / FILE).write_text(json.dumps(Instance.new(one, 0).to_json()))
    assert not a.staged(action, name) and a.staged(action)
    (a.sessions / name / FILE).write_text("not json")
    assert a.staged(action, name)  # unreadable: refused, not taken from the action


def test_a_github_token_for_a_list_no_longer_in_force_isnt_written(tmp_path):
    class Apps:
        async def token(self, persona, repos, permissions):
            return "token-for-" + ",".join(sorted(permissions))
    a = Agents(Library(REPO / "agents"), FakeShells(), tmp_path / "state", apps=Apps())
    directory = a.sessions / "s"
    directory.mkdir(parents=True)
    config = {"persona": "reviewer", "repo": "boot", "github": ["pr.read"]}
    (directory / "session.json").write_text(json.dumps({"config": config}))
    action = {"grant": None}
    run(a._github_token(directory, {**config, "github": ["pr.read", "push"]}, action))  # a renewal that read the record before a narrowing
    assert not (directory / agents_module.GITHUB_FOLDER).exists()
    run(a._github_token(directory, config, action))
    assert (directory / agents_module.GITHUB_FOLDER / "token").exists()


def test_a_locked_down_session_stays_locked_after_a_restart_until_a_resume(world):
    a, _d, effects = world

    async def go():
        name = await start(a)
        a.lock_down(name)
        a.machines.move(name, "write", "hand")  # a narrowing doesn't unlock it
        await effects.drain()
        return name
    name = run(go())
    assert scope_of(a, name)["tools"] == [] and grant_of(a, name)["tools"] == []
    again = Agents(a.library, FakeShells(), a.state, claude=a.claude, mcp_url="u", agent_token="t", workspace=a.workspace)
    assert scope_of(again, name)["tools"] == []
    a.shells.live.clear()
    run(a.resume(name))
    assert scope_of(a, name)["tools"] == ["docs_search", "submit_result", "comment_issue"]
    assert not (a.sessions / name / agents_module.LOCKED_FILE).exists()


def test_the_hubs_confirms_dont_use_up_a_sessions_room_to_ask(world):
    a, decisions, _e = world
    name = run(start(a))
    for _ in range(decisions_module.MAX_REQUESTS):
        decisions.widen_request({"session": name, "session_id": a.session_id_of(name), "pending": "p", "from": "a", "to": "b",
                                 "change": {}, "adds": {"hub_tools": ["x"]}, "sensitive": {}, "resumes": ""}, "the hub's")
    assert decisions.request("merge", {"repo": "boot", "number": 1, "head": "a" * 40, "session": name}, "please", name)["state"] == "requested"


# ---- approvals: an exit whose `approve` asks the maintainer (012 FR-025, FR-052) --------------------

def approvals(a, effects):
    from hubd.machinerun import Runner
    runner = Runner(a.machines)
    runner.on_blocked = effects.ask_approval
    effects.approve_move = runner.approved
    return runner


def wait_of(a, name, exit_=0, to="write", approve="me"):
    inst = a.machines.load(name)[1]
    return {"session_id": a.session_id_of(name), "state": inst.state, "version": inst.version, "exit": exit_, "to": to,
            "approve": approve, "checks": []}


def test_an_exit_waiting_for_approval_is_one_card_whose_yes_moves_the_session(world):
    a, decisions, effects = world
    approvals(a, effects)

    async def go():
        name = await start(a)
        effects.ask_approval(name, wait_of(a, name))
        effects.ask_approval(name, wait_of(a, name))  # the next signal finds it again: still one card
        card, = decisions.open_approvals(name)
        wait = wait_of(a, name)
        assert effects.approval_open(name, wait["session_id"], "research", wait["version"])
        assert not effects.approval_open(name, wait["session_id"], "write", wait["version"])
        assert decisions.open_widenings(name) == []
        assert card["kind"] == "machine.approve" and card["scope"]["level"] == "you" and card["scope"]["to"] == "write"
        assert decisions.view(card)["says"] == f"Workflow approval for {name}: research to write, which its workflow leaves to you"
        for refused in (lambda: decisions.approve(card["id"]), lambda: decisions.deny(card["id"]),
                        lambda: effects.answer(card["id"], True, "me")):
            with pytest.raises(DecisionError):
                refused()
        ended = await effects.answer_approval(card["id"], True, "me", "go on")
        await effects.drain()
        return name, ended
    name, ended = run(go())
    assert ended["state"] == "ended" and ended["approved"] and ended["why_ended"] == "approved: the session moved"
    assert a.machines.load(name)[1].state == "write" and told(a, name).startswith(f"{LABEL} Workflow: now in write.")
    assert [(m["to"], m["who"]) for m in a.machines.log.history(a.session_id_of(name))["moves"]] == [("write", "me")]


def test_a_level_above_the_session_asks_you_for_now_and_a_no_keeps_it_there(world):
    a, decisions, effects = world
    approvals(a, effects)

    async def go():
        name = await start(a)
        effects.ask_approval(name, wait_of(a, name, approve="steward"))
        card, = decisions.open_approvals(name)
        assert card["scope"]["level"] == "the Steward" and "no the Steward session that can answer, so it asks you" in card["why"]
        return name, await effects.answer_approval(card["id"], False, "me", "not yet")
    name, ended = run(go())
    assert ended["why_ended"] == "you said no: not yet" and a.machines.load(name)[1].state == "research"


def test_an_approval_card_ends_when_the_session_moves_another_way(world):
    a, decisions, effects = world
    approvals(a, effects)

    async def go():
        name = await start(a)
        effects.ask_approval(name, wait_of(a, name))
        card, = decisions.open_approvals(name)
        a.machines.move(name, "write", "hand")
        await effects.drain()
        assert decisions.open_approvals(name) == []
        with pytest.raises(DecisionError, match="isn't waiting"):
            await effects.answer_approval(card["id"], True, "me")
        return decisions._get(card["id"])
    assert run(go())["why_ended"] == "the session moved before it was answered"


def test_an_approval_for_a_session_that_moved_since_isnt_applied(world):
    a, decisions, effects = world
    approvals(a, effects)

    async def go():
        name = await start(a)
        wait = wait_of(a, name)
        effects.ask_approval(name, wait)
        card, = decisions.open_approvals(name)
        a.machines._watchers.clear()  # a move nothing watched, so its card stayed up
        a.machines.move(name, "wide", "hand")
        a.machines.confirm_move(name, a.machines.load(name)[1].pending["id"], "me")
        with pytest.raises(DecisionError, match="has moved"):
            await effects.answer_approval(card["id"], True, "me")
        return name, decisions._get(card["id"])
    name, card = run(go())
    assert card["why_ended"] == "not applied: the session has moved since that was asked"
    assert a.machines.load(name)[1].state == "wide"
