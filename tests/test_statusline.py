# SPDX-License-Identifier: GPL-2.0-or-later
"""The status line (012 FR-025): a workflow with `status = true` posts each move to its session's pull request or issue, as
the persona's App, as one comment it edits after; never a judge's evidence. A real Agents and Machines; GitHub and the Apps
are fakes."""
import asyncio
import json
import shutil
from pathlib import Path

import pytest

from hubd import agents as agents_module
from hubd import machine, machinerun
from hubd.agents import Agents, Library
from hubd.apps import AppError
from hubd.statusline import StatusLines, line

REPO = Path(__file__).resolve().parents[1]
ACTION = "issue-triage"
WORKFLOW = '''schema = 1
name = "issue-triage"
initial = "look"
{status}
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
[[state.look.exit]]
to = "done"
decided_by = "hand"

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


class FakeGh:
    """Comments as GitHub keeps them: on an item, by the App whose token posted them."""
    def __init__(self):
        self.runs, self.edits, self.edit_fails, self.next_id, self.comments = [], [], False, 100, {}

    async def run(self, argv, stdin=None, timeout=None, token=None):
        self.runs.append((list(argv), stdin, token))
        if argv[0] == "api":
            cid = argv[1].rsplit("/", 1)[1]
            repo, number, by = self.comments.get(cid, ("gone", 0, None))
            return {"code": 0, "stdout": json.dumps({"node_id": f"IC_{cid}", "issue_url": f"https://api.github.com/repos/GlassineOS/{repo}/issues/{number}",
                                                     "user": {"login": by}}), "stderr": ""}
        self.next_id += 1
        self.comments[str(self.next_id)] = (argv[4].split("/")[1], int(argv[2]), f"{token.removeprefix('token-of-')}[bot]" if token else "the-login")
        kind = "pull" if argv[0] == "pr" else "issues"
        return {"code": 0, "stdout": f"https://github.com/GlassineOS/{argv[4].split('/')[1]}/{kind}/{argv[2]}#issuecomment-{self.next_id}\n", "stderr": ""}

    async def graphql(self, name, variables=None, token=None):
        self.edits.append((name, dict(variables), token))
        if self.edit_fails:
            return {"code": 1, "stdout": '{"errors": [{"message": "gone"}]}', "stderr": ""}
        return {"code": 0, "stdout": '{"data": {"updateIssueComment": {"issueComment": {"url": "u"}}}}', "stderr": ""}


class FakeApps:
    def __init__(self):
        self.broken, self.none = False, False

    async def token(self, persona, repositories=None, permissions=None):
        if self.broken:
            raise AppError("no installation")
        return None if self.none else f"token-of-{persona}"

    def posts_as(self, persona):
        return None if self.none else f"{persona}[bot]"


@pytest.fixture
def world(tmp_path, monkeypatch, request):
    monkeypatch.setattr(agents_module, "SANDBOX_TOOLS", ())
    root = tmp_path / "agents"
    shutil.copytree(REPO / "agents", root)
    status = getattr(request, "param", "status = true")
    (root / "workflows" / f"{ACTION}.toml").write_text(WORKFLOW.format(status=status))
    claude = tmp_path / "claude"
    claude.write_text("#!/bin/sh\n")
    claude.chmod(0o755)
    a = Agents(Library(root), FakeShells(), tmp_path / "state", claude=str(claude), mcp_url="u", agent_token="t", workspace=tmp_path / "ws")
    gh, apps = FakeGh(), FakeApps()
    slept = []

    async def sleep(seconds):
        slept.append(seconds)
    lines = StatusLines(a, gh, apps, sleep=sleep)
    return a, gh, apps, lines, slept


def comments(gh):
    return [(argv[:3], stdin, token) for argv, stdin, token in gh.runs if argv[1] == "comment"]


def test_a_move_posts_one_line_as_the_persona_and_later_moves_edit_it(world):
    a, gh, _apps, lines, _slept = world

    async def go():
        name = (await a.start(a.defaults(ACTION, "boot", 7)))["name"]
        a.machines.move(name, "done", "hand", who="me")
        await lines.drain()
        a.machines.move(name, "look", "hand", who="me")
        await lines.drain()
        return name
    name = asyncio.run(go())
    persona = json.loads((a.sessions / name / "session.json").read_text())["config"]["persona"]
    assert comments(gh) == [(["issue", "comment", "7"], "Workflow: now in done (moved by hand)", f"token-of-{persona}")]
    assert gh.edits == [("comment_edit", {"commentId": "IC_101", "body": "Workflow: now in look (moved by hand)"}, f"token-of-{persona}")]


def test_it_goes_to_the_pull_request_once_there_is_one_and_a_failed_edit_posts_again(world):
    a, gh, _apps, lines, slept = world

    async def go():
        name = (await a.start(a.defaults(ACTION, "boot", 7)))["name"]
        a.machines.move(name, "done", "hand")
        await lines.drain()
        a._prs[name] = (0.0, [{"repo": "boot", "number": 9, "state": "OPEN"}], a.session_id_of(name))
        a.machines.move(name, "look", "hand")
        await lines.drain()
        gh.edit_fails = True
        a.machines.move(name, "done", "hand")
        await lines.drain()
    asyncio.run(go())
    assert [c[0] for c in comments(gh)] == [["issue", "comment", "7"], ["pr", "comment", "9"], ["pr", "comment", "9"]]
    assert len(slept) == 2 and all(0 < s <= 60 for s in slept)  # new comments of one session at most one a minute


def test_a_persona_whose_app_fails_posts_nothing_rather_than_as_the_login(world):
    a, gh, apps, lines, _slept = world
    apps.broken = True

    async def go():
        name = (await a.start(a.defaults(ACTION, "boot", 7)))["name"]
        a.machines.move(name, "done", "hand")
        await lines.drain()
    asyncio.run(go())
    assert gh.runs == []


def test_a_persona_without_an_app_posts_nothing_rather_than_as_the_login(world):
    a, gh, apps, lines, _slept = world
    apps.none = True

    async def go():
        name = (await a.start(a.defaults(ACTION, "boot", 7)))["name"]
        a.machines.move(name, "done", "hand")
        await lines.drain()
    asyncio.run(go())
    assert gh.runs == []


def test_a_kept_comment_is_edited_only_while_it_is_the_apps_own_on_that_item(world):
    """The kept id is read back before an edit: a comment by another author, or one on another item, is left alone, and a
    new one is posted."""
    a, gh, _apps, lines, _slept = world

    async def go():
        name = (await a.start(a.defaults(ACTION, "boot", 7)))["name"]
        a.machines.move(name, "done", "hand")
        await lines.drain()
        [cid] = list(gh.comments)
        gh.comments[cid] = ("boot", 7, "someone[bot]")  # not the App's own any more
        a.machines.move(name, "look", "hand")
        await lines.drain()
        kept = json.loads((a.sessions / name / "status-line.json").read_text())
        gh.comments[str(kept["id"])] = ("boot", 8, gh.comments[str(kept["id"])][2])  # on another item
        lines._posted.clear()
        a.machines.move(name, "done", "hand")
        await lines.drain()
        return name
    asyncio.run(go())
    assert gh.edits == []
    assert [c[0] for c in comments(gh)] == [["issue", "comment", "7"]] * 3


@pytest.mark.parametrize("world", [""], indirect=True)
def test_without_status_a_workflow_posts_nothing(world):
    a, gh, _apps, lines, _slept = world

    async def go():
        name = (await a.start(a.defaults(ACTION, "boot", 7)))["name"]
        a.machines.move(name, "done", "hand")
        await lines.drain()
    asyncio.run(go())
    assert gh.runs == []


def test_the_machines_line_says_the_exits_words_never_the_judges_evidence(world):
    a, gh, _apps, lines, _slept = world

    async def go():
        name = (await a.start(a.defaults(ACTION, "boot", 7)))["name"]
        d = a.machines.load(name)[1].definition()
        exit_ = d.states["look"].exits[0]
        runner = machinerun.Runner(a.machines)
        runner._move(name, "look", a.machines.load(name)[1].version, exit_)
        await lines.drain()
    asyncio.run(go())
    assert comments(gh)[0][1] == "Workflow: now in done (The issue is understood.)"


def test_the_line_and_its_reasons():
    d = machine.parse(WORKFLOW.format(status="status = true"))
    assert line(d, "done", {"by": "rollback"}) == "Workflow: now in done (rolled back by hand)"
    assert line(d, "done", {"by": "rollback", "who": "hub"}).endswith("(moved back by the hub: the move didn't take effect)")
    assert line(d, "done", {"by": "machine", "why": "x\ny  " + "z" * 300}).count("\n") == 0
    facts = machine.Exit(to="done", decided_by="facts", requires=("pr.open", "pr.checks == pass"))
    assert machinerun.reason_of(facts) == "pr.open, pr.checks == pass"


def test_no_shipped_workflow_posts_a_status_line():
    library = Library(REPO / "agents")
    assert [n for n, d in library.workflows.items() if d.status] == []
