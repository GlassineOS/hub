# SPDX-License-Identifier: GPL-2.0-or-later
"""The personas' workflows (012 FR-062, FR-070 to FR-074, User Story 6): the library's own checks and caps, the implementor
coordinating an engineer, a code reviewer and a QA engineer as managed sessions, the design spike and its accepted design,
the repository maintainer under the Steward, and the Workflow author's drafts.

The hub is real (Agents, Machines, Runner, Effects, Managed behind hubd's ops); the terminal, GitHub and the judge are
faked as in test_implement_flow. GitHub finds a pull request only on the branch that opened it, as it does."""
import asyncio
import json
import subprocess
import time
from pathlib import Path

import pytest

from starts_util import start_again
from hubd import agents as agents_module
from hubd import judge as judgelib
from hubd import machine, machinestore, summary
from hubd.agents import IDLE_FILE, OUTCOMES_FILE, Library
from hubd.decisions import APPROVE

import test_implement_flow as base
from test_implement_flow import hub  # noqa: F401  (the fixture)
from test_implement_flow import HEAD, PR, ev, feed, history, settle, state_of, token_of, told, turn_ends

REPO = Path(__file__).resolve().parents[1]
LIBRARY = Library(REPO / "agents")
NEW = ("implementor", "engineer", "qa-audit", "design-check", "repo-maintainer", "workflow-change", "workflow-review")


# --- the files ------------------------------------------------------------------------------------------------------

def _first(d: machine.Definition) -> machine.Grant:
    s = d.initial
    while d.states[s].initial is not None:
        s = d.states[s].initial
    return machine.effective(d, s)


def test_every_new_workflow_passes_the_checks_and_the_librarys_rules():
    for name in NEW:
        text = (REPO / "agents" / "workflows" / f"{name}.toml").read_text()
        found = machinestore.examine(text, name, LIBRARY)
        assert not machinestore.problems_of(found["findings"]), (name, found["findings"])
        assert LIBRARY.actions[name]["workflow"] == name
    for persona in ("implementor", "qa-engineer", "repo-maintainer", "workflow-author"):
        assert LIBRARY.family(persona) and LIBRARY.text("personas", persona).strip()


def test_each_owner_holds_what_its_managed_sessions_need_so_they_start_without_an_approval():
    """FR-043: computed from the files for every entry in every state. Two entries are expected to ask, and say why."""
    asks = {}
    for name, d in LIBRARY.workflows.items():
        for sid, st in d.states.items():
            if st.initial is not None:
                continue
            for _s, m in machine.managed_of(d, sid):
                extra = machine.beyond(_first(LIBRARY.workflows[m.workflow]), machine.effective(d, sid))
                if extra:
                    asks.setdefault((name, m.name), set()).update(extra)
    # the design spike is a full design session (011), which no locked owner holds; an implementor holds a shell, a new
    # branch and push, which neither the maintainer nor the Steward above it holds
    assert asks == {("implementor", "design-spike"): {"access", "permission_mode"},
                    ("repo-maintainer", "implementor"): {"tools", "hub_tools", "asks_first", "github", "checkout"}}
    steward = LIBRARY.workflows["project-steward"]
    assert not machine.beyond(_first(LIBRARY.workflows["repo-maintainer"]), machine.effective(steward, "session"))


def test_the_implementor_pushes_only_where_its_engineer_runs():
    d = LIBRARY.workflows["implementor"]
    pushing = {sid for sid, st in d.states.items() if st.initial is None and "push" in machine.effective(d, sid).github}
    assert pushing == {"implement", "fix"}
    engineers = {sid for sid, st in d.states.items() for m in st.manages if m.workflow == "engineer"}
    assert engineers == pushing
    assert all("merge" not in machine.effective(d, sid).github for sid in d.states)


def test_the_author_has_no_tool_that_saves_or_proposes():
    """FR-062: no state of workflow-change, nor its reviewer's, holds a tool that saves a version or makes a decision."""
    saving = {"workflow_save", "workflow_propose", "decision_request", "spawn_session", "merge_pr"}
    for name in ("workflow-change", "workflow-review"):
        d = LIBRARY.workflows[name]
        for sid in d.states:
            g = machine.effective(d, sid)
            assert not (set(g.hub_tools) | set(g.asks_first)) & saving and "Bash" not in g.tools and g.checkout is False, (name, sid)
    from app.hub import tools  # noqa: PLC0415
    from app.hub.github import GitHub  # noqa: PLC0415
    names = {t.name for t in asyncio.run(tools.build(GitHub.__new__(GitHub), None).every_tool())}
    assert {"draft_workflow", "read_draft", "read_workflow"} <= names
    assert not {n for n in names if "save" in n or ("propose" in n)}


def test_started_and_draft_facts_are_checked_like_the_others():
    bad = '''schema = 1
name = "x"
initial = "a"
[state.a]
[[state.a.exit]]
to = "b"
decided_by = "facts"
requires = ["started.nobody"]
on = ["turn.end"]
[state.b]
final = true
'''
    found = [f.text for f in machine.check(machine.parse(bad)) if f.kind == "problem"]
    assert any("no managed entry here is named nobody" in t for t in found)
    with pytest.raises(machine.DefinitionError):
        machine.parse_requires("drafts.failed == yes")
    assert machine.parse_requires("drafts.failed >= 3").terms[0].value == 3


# --- the implementor, end to end ---------------------------------------------------------------------------------------

class BranchGh(base.FakeGh):
    """A pull request is found only on its own branch: prs is {branch: [pull request]}."""
    def __init__(self):
        super().__init__()
        self.branches = {}

    async def run(self, argv, stdin=None, timeout=None, token=None):
        if argv[0] == "api" and "/pulls?" in argv[1]:
            self.ran.append(argv)
            found = [pr for branch, prs in self.branches.items() if f"agent/{branch}&" in argv[1].replace("%2F", "/") for pr in prs]
            return {"code": 0, "stdout": json.dumps(found), "stderr": ""}
        return await super().run(argv, stdin, timeout, token)


class AskedJudge(judgelib.Judge):
    """Answers each question by what it asks: `yes` holds the questions (by a word in them) it says yes to."""
    provider, model = "fake", "fixed"

    def __init__(self):
        self.yes, self.asked = set(), []

    async def complete(self, system, user, schema):
        if schema is summary.FOLD_SCHEMA:
            return {"summary": "Coordinating the work."}, 0.0
        self.asked.append(user)
        for line in user.splitlines():
            number, _, question = line.partition(": ")
            if number.isdigit() and any(word in question for word in self.yes):
                return {"exit": int(number), "evidence": "Pushed and opened the draft pull request", "confidence": 0.9}, 0.001
        return {"exit": None, "evidence": "", "confidence": 0.8}, 0.001


@pytest.fixture
def team(request, monkeypatch):
    """test_implement_flow's hub, with GitHub and the judge above in place of its own."""
    monkeypatch.setattr(base, "FakeGh", BranchGh)
    monkeypatch.setattr(base, "Judge", AskedJudge)
    return request.getfixturevalue("hub")


def children(h, a, name, entry):
    return [n for n, _r in h.managed.children(name, a.session_id_of(name), entry)]


async def give(h, child, **fields):
    got = await h.request({"op": "managed.return", "agent_token": token_of(h.agents, child), "fields": fields})
    await settle(h)
    return got


def pr(number=PR, state="open", merged=None, sha=HEAD):
    return {"number": number, "state": state, "merged_at": merged, "head": {"sha": sha}}


async def through_implement(h, a, gh, judge):
    name = (await a.start(a.defaults("implementor", "boot", 7)))["name"]
    await settle(h)
    assert state_of(a, name) == "implement"
    [engineer] = children(h, a, name, "engineer")
    record = json.loads((a.sessions / engineer / "session.json").read_text())
    # the engineer started with no approval: the implementor holds what it needs, push included, in implement
    assert record["config"]["action"] == "engineer" and record["owner"]["name"] == name and "push" in record["config"]["github"]
    assert h.decisions.open_approvals(name) == []
    # the engineer starts by itself: the implementor hears so, and asking for it starts nothing but says how it stands
    assert f"engineer started under you as {engineer}." in told(a, name)
    asked = await h.request({"op": "managed.start", "agent_token": token_of(a, name), "entry": "engineer"})
    assert asked["ok"] and asked["by_itself"] and [r["name"] for r in asked["sessions"]] == [engineer]
    assert children(h, a, name, "engineer") == [engineer]
    # its turn ends: no design question, so no design spike; the engineer hasn't handed back, so it stays
    await turn_ends(h, a, name)
    assert state_of(a, name) == "implement" and children(h, a, name, "design-spike") == []
    # the engineer opens the pull request on its own branch, which the implementor carries as its own
    gh.branches[engineer] = [pr()]
    await feed(h, ev("opened", "OPEN"), ev("checks", "passing"))
    assert (await give(h, engineer, status="done", summary=["Opened the draft pull request."]))["ok"]
    await turn_ends(h, a, name)
    assert [p["number"] for p in a.known_prs(name)] == [PR]
    assert state_of(a, name) == "review"
    return name, engineer


def test_the_implementor_coordinates_engineer_reviewer_and_qa_to_merge_ready(team):
    h, a, gh, _apps, judge = team

    async def go():
        name, engineer = await through_implement(h, a, gh, judge)
        [reviewer] = children(h, a, name, "reviewer")
        rec = json.loads((a.sessions / reviewer / "session.json").read_text())
        assert rec["config"]["action"] == "pr-review" and rec["config"]["number"] == PR  # the carried pull request
        # the reviewer passes: on to qa. The change is user-facing, so on the implementor's turn end a QA engineer starts
        assert (await give(h, reviewer, verdict="pass", findings=[]))["ok"]
        assert state_of(a, name) == "qa"
        judge.yes = {"is user-facing: a person"}
        await turn_ends(h, a, name)
        [qa] = children(h, a, name, "qa")
        rec = json.loads((a.sessions / qa / "session.json").read_text())
        assert rec["config"]["action"] == "qa-audit" and rec["config"]["persona"] == "qa-engineer" and "Bash" in rec["config"]["tools"]
        assert h.decisions.open_approvals(name) == []  # no start in the whole run needed an approval
        assert state_of(a, name) == "qa"  # the judge's other question, that it isn't user-facing, can't move it: started.qa
        assert a.machines.load(name)[1].facts(time.time()) is not None
        assert (await give(h, qa, verdict="pass", findings=["Ran make check: 120 passed."]))["ok"]
        assert state_of(a, name) == "merge-ready"
        assert "- Ran make check: 120 passed." in (a.sessions / name / OUTCOMES_FILE).read_text()
        return name
    name = asyncio.run(go())
    moves = [(m["from"], m["to"]) for m in history(a, name)["moves"]]
    assert moves == [("implement", "review"), ("review", "qa"), ("qa", "merge-ready")]


def test_a_change_that_isnt_user_facing_skips_qa_and_a_failing_review_resumes_the_same_engineer(team):
    h, a, gh, _apps, judge = team

    async def go():
        name, engineer = await through_implement(h, a, gh, judge)
        [reviewer] = children(h, a, name, "reviewer")
        (a.sessions / name / IDLE_FILE).touch()
        assert (await give(h, reviewer, verdict="fail", findings=["The loop never ends."]))["ok"]
        await base.at_prompt(h, a, name)
        assert state_of(a, name) == "fix"
        # fix resumes the same engineer, with the implementor's summary: one engineer for the whole piece of work
        assert children(h, a, name, "engineer") == [engineer]
        assert "A new round." in (a.sessions / engineer / OUTCOMES_FILE).read_text()
        gh.head = "b" * 40
        gh.branches[engineer] = [pr(sha=gh.head)]
        await feed(h, ev("head", old_head=HEAD, new_head=gh.head), ev("checks", "passing"))
        assert (await give(h, engineer, status="done", summary=["Bounded the loop."]))["ok"]
        assert state_of(a, name) == "review"
        [_old, reviewer2] = children(h, a, name, "reviewer")
        assert (await give(h, reviewer2, verdict="pass", findings=[]))["ok"]
        assert state_of(a, name) == "qa"
        judge.yes = {"isn't user-facing"}
        await turn_ends(h, a, name)
        assert children(h, a, name, "qa") == [] and state_of(a, name) == "merge-ready"
        return name
    name = asyncio.run(go())
    assert [(m["from"], m["to"]) for m in history(a, name)["moves"]] == [
        ("implement", "review"), ("review", "fix"), ("fix", "review"), ("review", "qa"), ("qa", "merge-ready")]


async def into_qa_with_a_designer(h, a, gh, judge):
    """Through review to qa, woken there for the QA entry's `when`; then the designer started on request (FR-074)."""
    name, _engineer = await through_implement(h, a, gh, judge)
    [reviewer] = children(h, a, name, "reviewer")
    sent = []
    real = a._send

    async def send(who, words, by=None):
        sent.append((who, words))
        return await real(who, words, by=by)
    a._send = send
    (a.sessions / name / IDLE_FILE).touch()
    assert (await give(h, reviewer, verdict="pass", findings=[]))["ok"]
    await base.at_prompt(h, a, name)
    assert state_of(a, name) == "qa"
    # idle at its prompt, it is woken with the hub's fixed words, so its `when` gets a turn to be judged on
    assert (name, "Your workflow moved: what it says is in this turn, from the hub.") in sent
    assert all(words.startswith(("Your workflow moved", "[From the hub]")) or who != name for who, words in sent)
    judge.yes = {"accepted design board covers", "is user-facing: a person"}
    got = await h.request({"op": "managed.start", "agent_token": token_of(a, name), "entry": "designer"})
    await settle(h)
    assert got["ok"] and got["started"], got
    await turn_ends(h, a, name)
    [designer] = children(h, a, name, "designer")
    [qa] = children(h, a, name, "qa")
    rec = json.loads((a.sessions / designer / "session.json").read_text())
    assert rec["config"]["action"] == "design-check" and rec["config"]["persona"] == "designer" and not rec["full"]
    assert h.decisions.open_approvals(name) == []  # within the implementor's grant: no card
    return name, qa, designer


def test_a_designer_started_in_qa_is_waited_for_and_its_pass_with_qas_reaches_merge_ready(team):
    h, a, gh, _apps, judge = team

    async def go():
        name, qa, designer = await into_qa_with_a_designer(h, a, gh, judge)
        assert (await give(h, qa, verdict="pass", findings=["Ran it."]))["ok"]
        assert state_of(a, name) == "qa"  # the designer hasn't said yet
        assert (await give(h, designer, verdict="pass", findings=["Matches the accepted board."]))["ok"]
        assert state_of(a, name) == "merge-ready"
    asyncio.run(go())


def test_a_designers_fail_goes_to_fix(team):
    h, a, gh, _apps, judge = team

    async def go():
        name, _qa, designer = await into_qa_with_a_designer(h, a, gh, judge)
        (a.sessions / name / IDLE_FILE).touch()
        assert (await give(h, designer, verdict="fail", findings=["The spacing differs from the board."]))["ok"]
        await base.at_prompt(h, a, name)
        assert state_of(a, name) == "fix"
    asyncio.run(go())


# --- the design spike (User Story 6) ---------------------------------------------------------------------------------

def test_a_design_spike_asks_you_raises_look_at_the_design_and_its_merged_pull_request_is_design_accepted(team, tmp_path):
    h, a, gh, _apps, judge = team
    ui = tmp_path / "remote" / "ui"
    ui.mkdir(parents=True)
    git = lambda *x: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *x],  # noqa: E731
                                    cwd=ui, check=True, capture_output=True)
    git("init", "-q", "-b", "main")
    (ui / "README").write_text("ui\n")
    git("add", "README")
    git("commit", "-qm", "base")
    login = h.sessions.create()

    async def go():
        name = (await a.start(a.defaults("implementor", "boot", 7)))["name"]
        await settle(h)
        [engineer] = children(h, a, name, "engineer")
        judge.yes = {"design question"}
        await turn_ends(h, a, name)
        # a design session is full: it waits for your approval, above the implementor
        [card] = [c for c in h.decisions.open_approvals(name) if c["scope"].get("type") == "managed"]
        assert card["scope"]["entry"] == "design-spike"
        got = await h.request({"op": "decision.approve", "token": login, "id": card["id"]})
        assert got["ok"], got
        await settle(h)
        [spike] = children(h, a, name, "design-spike")
        rec = json.loads((a.sessions / spike / "session.json").read_text())
        assert rec["config"]["action"] == "design" and rec["owner"]["name"] == name and rec["full"]
        # "Look at the design": a card on the design session, whose action opens its design view
        looks = [c for c in h.decisions.open_approvals(spike) if c["scope"].get("type") == "design"]
        assert len(looks) == 1 and looks[0]["scope"]["design"] == spike and looks[0]["scope"]["owner"] == name
        # the engineer is done and the checks pass, but the spike started this round: the work waits for its design
        gh.branches[engineer] = [pr()]
        await feed(h, ev("opened", "OPEN"), ev("checks", "passing"))
        assert (await give(h, engineer, status="done", summary=["Done."]))["ok"]
        facts = await h.machine_run.facts_now(name, *a.machines.load(name))
        assert facts["started.design-spike"] is True and "design.accepted" not in facts
        assert state_of(a, name) == "implement"
        # the spike opens its pull request in GlassineOS/ui; the implementor's own pull request stays the engineer's
        gh.branches[spike] = [pr(number=30)]
        await feed(h, ev("opened", "OPEN", repo="ui", number=30))
        facts = await h.machine_run.facts_now(name, *a.machines.load(name))
        assert facts["design.accepted"] is False and [p["number"] for p in a.known_prs(name)] == [PR]
        assert state_of(a, name) == "implement"
        # you merge it: the feed says so, and implement moves on
        gh.branches[spike] = [pr(number=30, state="closed", merged="2026-11-05T15:00:00Z")]
        await feed(h, ev("state", "MERGED", repo="ui", number=30))
        await turn_ends(h, a, name)
        assert state_of(a, name) == "review"
        # looking at it is only that: approving the card settles it and changes nothing else
        got = await h.request({"op": "decision.approve", "token": login, "id": looks[0]["id"]})
        assert got["ok"], got
        return name
    asyncio.run(go())


# --- the repository maintainer and the Steward (FR-071) ----------------------------------------------------------------

def test_the_steward_starts_one_maintainer_per_repository_and_answers_what_comes_up(team):
    h, a, gh, _apps, judge = team

    async def go():
        steward = (await a.start(a.defaults("project-steward", None, None)))["name"]
        tok = token_of(a, steward)
        assert {"start_managed", "answer_report"} <= set(a.scope(tok)["tools"])
        ask = lambda item: h.request({"op": "managed.start", "agent_token": tok, "entry": "repo-maintainer", "item": item})  # noqa: E731
        bad = await ask("boot#3")
        assert not bad.get("started") and "a repository: name it alone" in bad["why"]
        got = await ask("boot")
        await settle(h)
        assert got["ok"] and got["started"], got
        maintainer = got["name"]
        rec = json.loads((a.sessions / maintainer / "session.json").read_text())
        assert rec["config"]["action"] == "repo-maintainer" and rec["config"]["repo"] == "boot" and rec["owner"]["name"] == steward
        assert h.decisions.open_approvals(steward) == []  # within the Steward's grant: no card
        # one per repository: another start for boot is refused, from the Steward or from the page
        again = await ask("boot")
        assert not again.get("started") and "One runs for each repository at a time" in again["why"]
        with pytest.raises(agents_module.AgentError, match="One runs for each repository"):
            await a.start(a.defaults("repo-maintainer", "boot", None))
        # a report from the maintainer reaches the Steward, the session above it, which answers it
        mtok = token_of(a, maintainer)
        sent = await h.request({"op": "managed.report", "agent_token": mtok, "kind": "decision", "evidence": "boot#4 is stalled.",
                                "proposal": "Ask its author."})
        assert sent["ok"] and sent["to"] == steward
        answered = await h.request({"op": "managed.answer", "agent_token": tok, "id": sent["id"], "decision": "approve"})
        assert answered["ok"], answered
        # an implementor for a ready issue names its item; one of another repository is refused
        judge.yes = {"is ready"}
        base.said(a, maintainer)
        other = await h.request({"op": "managed.start", "agent_token": mtok, "entry": "implementor", "item": "hub#9"})
        assert not other.get("started") and "its sessions work there" in other["why"]
        first = await h.request({"op": "managed.start", "agent_token": mtok, "entry": "implementor", "item": "boot#7"})
        await settle(h)
        # an implementor holds more than the maintainer and the Steward: its first start waits for you
        assert not first.get("started") and "waits for an approval" in first["why"]
        assert [c["scope"]["entry"] for c in h.decisions.open_approvals(maintainer)] == ["implementor"]
        return steward
    asyncio.run(go())


def test_approve_steward_reaches_the_steward_session(team):
    h, a, _gh, _apps, _judge = team

    async def go():
        steward = (await a.start(a.defaults("project-steward", None, None)))["name"]
        assert h.managed._answerer(steward) == (steward, a.session_id_of(steward))
        # a session whose exit needs approve = "steward" sends its approval report to the Steward, not to your card
        name = (await a.start(a.defaults("implement", "boot", 7)))["name"]
        _r, inst = a.machines.load(name)
        wait = {"approve": "steward", "session_id": a.session_id_of(name), "state": inst.state, "version": inst.version,
                "exit": 0, "to": "review", "checks": []}
        assert h.managed.route_approval(name, wait)
        [report] = [r for r in a.machines.log.reports(state="open") if r["kind"] == "approval"]
        assert report["to_name"] == steward
    asyncio.run(go())


# --- the Workflow author's drafts (FR-062) ---------------------------------------------------------------------------

def _implement_text(edit=None) -> str:
    text = start_again((REPO / "agents" / "workflows" / "implement.toml").read_text(), "implement")  # as the team's library has it
    return edit(text) if edit else text


def test_drafts_are_checked_never_saved_a_sensitive_one_goes_to_a_reviewer_and_the_hub_proposes_it(team):
    h, a, _gh, _apps, _judge = team

    async def go():
        name = (await a.run("workflow-change", None, None, notes="The workflow: implement. Shorter review instructions."))["name"]
        await settle(h)
        tok = token_of(a, name)
        assert state_of(a, name) == "draft"
        scope = a.scope(tok)
        assert {"draft_workflow", "read_workflow", "read_draft"} <= set(scope["tools"])
        draft = lambda text, note="Shorter.": h.request({"op": "wfdraft.make", "agent_token": tok, "name": "implement", "text": text, "note": note})  # noqa: E731
        # the author can't reach a save or a proposal: those ops need a login, which a token isn't
        for op in ("workflow.save", "workflow.propose"):
            got = await h.request({"op": op, "agent_token": tok, "token": tok, "name": "implement", "text": _implement_text(), "note": "x"})
            assert got.get("denied"), op
        read = await h.request({"op": "wfdraft.workflow", "agent_token": tok, "name": "implement"})
        assert read["ok"] and read["text"] == _implement_text()
        # a draft that the checks refuse is kept as failed; two in a row, then one that passes
        for _ in range(2):
            got = await draft(_implement_text(lambda t: t.replace('to = "merge-ready"', 'to = "nowhere"', 1)))
            assert got["ok"] and got["passes"] is False and got["saved"] is False
            assert got["problems"] and got["failed_in_a_row"] >= 1
        good = _implement_text(lambda t: t.replace("Your pull request waits for review.", "It waits for review.", 1))
        got = await draft(good)
        assert got["passes"] and got["problems"] == [] and got["failed_in_a_row"] == 0 and got["sensitive"]  # implement asks first with merge_pr
        assert a.workflow_store.latest_number("implement", "org") == 0  # nothing saved
        assert [d for d in h.decisions.list() if d["kind"] == "workflow.change"] == []  # nothing proposed
        facts = await h.machine_run.facts_now(name, *a.machines.load(name))
        assert facts["draft.ok"] is True and facts["draft.sensitive"] is True
        # sensitive: propose isn't open to it, review is; the reviewer reads the author's newest draft
        got = await h.request({"op": "session.request_move", "agent_token": tok, "to": "propose"})
        assert not got["moved"]
        got = await h.request({"op": "session.request_move", "agent_token": tok, "to": "review"})
        await settle(h)
        assert got["moved"] and state_of(a, name) == "review"
        [reviewer] = [n for n, _r in h.managed.children(name, a.session_id_of(name), "reviewer")]
        seen = await h.request({"op": "wfdraft.read", "agent_token": token_of(a, reviewer)})
        assert seen["ok"] and seen["text"] == good and seen["sensitive"]
        # in review the author can't draft: what is reviewed is what is proposed
        assert not (await draft(good))["ok"]
        assert (await give(h, reviewer, verdict="pass", findings=[]))["ok"]
        assert state_of(a, name) == "propose"
        [card] = [d for d in h.decisions.list() if d["kind"] == "workflow.change"]
        assert card["scope"]["text"] == good and card["scope"]["proposed_by"] == name and card["scope"]["note"] == "Shorter."
        assert a.workflow_store.latest_number("implement", "org") == 0  # still: only the maintainer's approval saves
    asyncio.run(go())


def test_three_failed_drafts_send_the_author_to_ask_you(team):
    h, a, _gh, _apps, _judge = team

    async def go():
        name = (await a.run("workflow-change", None, None, notes="The workflow: implement."))["name"]
        await settle(h)
        tok = token_of(a, name)
        broken = _implement_text(lambda t: t.replace('to = "merge-ready"', 'to = "nowhere"', 1))
        for i in range(3):
            got = await h.request({"op": "wfdraft.make", "agent_token": tok, "name": "implement", "text": broken, "note": f"Try {i}."})
            assert got["ok"] and not got["passes"] and got["failed_in_a_row"] == i + 1
            assert (await h.request({"op": "session.signal", "agent_token": tok, "how": "PostToolUse"}))["ok"]
            await settle(h)
        assert state_of(a, name) == "ask"
        assert "Ask the maintainer with report_up" in (a.sessions / name / OUTCOMES_FILE).read_text()
        sent = await h.request({"op": "managed.report", "agent_token": tok, "kind": "blocker", "evidence": "The checks refuse it.",
                                "proposal": "Say which exit to drop."})
        assert sent["ok"] and sent["to"] == "you"
        [card] = [c for c in h.decisions.open_approvals(name) if c["scope"].get("type") == "report"]
        login = h.sessions.create()
        (a.sessions / name / IDLE_FILE).touch()  # at its prompt: the move's relaunch goes ahead
        assert (await h.request({"op": "decision.approve", "token": login, "id": card["id"]}))["ok"]
        await settle(h)
        assert state_of(a, name) == "draft"  # a new round: its failed drafts start again at none
        facts = await h.machine_run.facts_now(name, *a.machines.load(name))
        assert facts["drafts.failed"] == 0
    asyncio.run(go())


def test_a_draft_from_another_session_or_an_earlier_conversation_is_refused(team):
    h, a, _gh, _apps, _judge = team

    async def go():
        other = (await a.start(a.defaults("implement", "boot", 7)))["name"]
        got = await h.request({"op": "wfdraft.make", "agent_token": token_of(a, other), "name": "implement", "text": "x", "note": "x"})
        assert got["refused"] and "can't use draft_workflow" in got["error"]
        assert (await h.request({"op": "wfdraft.make", "agent_token": "nope", "name": "implement", "text": "x", "note": "x"}))["refused"]
    asyncio.run(go())


def test_managed_only_actions_are_on_no_menu_and_need_an_owner(team):
    _h, a, _gh, _apps, _judge = team
    listed = {x["id"] for kind in (None, "pr", "issue", "repo", "project") for x in a.actions(kind)}
    assert not listed & {"engineer", "qa-audit", "design-check", "workflow-review"}
    with pytest.raises(agents_module.AgentError, match="runs only under another session"):
        asyncio.run(a.start(a.defaults("engineer", "boot", 7)))


assert APPROVE  # the card kind every Needs-you card above is


# --- review fixes: items, waiting starts, the cap, one per repository, drafts ----------------------------------------

async def a_maintainer(h, a):
    steward = (await a.start(a.defaults("project-steward", None, None)))["name"]
    got = await h.request({"op": "managed.start", "agent_token": token_of(a, steward), "entry": "repo-maintainer", "item": "GlassineOS/boot"})
    await settle(h)
    assert got["ok"] and got["started"], got  # the organisation's prefix is taken too
    return steward, got["name"]


def test_an_approved_start_starts_the_item_it_was_asked_for_and_holds_for_that_item_only(team):
    h, a, _gh, _apps, judge = team

    async def go():
        _steward, m = await a_maintainer(h, a)
        mtok = token_of(a, m)
        judge.yes = {"is ready"}
        base.said(a, m)
        await h.request({"op": "managed.start", "agent_token": mtok, "entry": "implementor", "item": "boot#7"})
        await settle(h)
        [card] = h.decisions.open_approvals(m)
        assert card["scope"]["item"] == "boot#7" and "GlassineOS/boot#7" in card["scope"]["says"]
        assert any("start implementor for GlassineOS/boot#7" in q for q in judge.asked)  # the judge was asked about that issue
        assert (await h.request({"op": "decision.approve", "token": h.sessions.create(), "id": card["id"]}))["ok"]
        await settle(h)
        [child] = children(h, a, m, "implementor")
        rec = json.loads((a.sessions / child / "session.json").read_text())
        assert (rec["config"]["repo"], rec["config"]["number"]) == ("boot", 7)
        # another issue is judged again, not on boot#7's word: not ready, it doesn't start
        judge.yes, asked = set(), len(judge.asked)
        got = await h.request({"op": "managed.start", "agent_token": mtok, "entry": "implementor", "item": "boot#8"})
        assert not got["started"] and "when doesn't hold" in got["why"] and len(judge.asked) > asked
        # ready, it asks again: the approval held for boot#7 only
        judge.yes = {"is ready"}
        h.managed._judged.clear()
        got = await h.request({"op": "managed.start", "agent_token": mtok, "entry": "implementor", "item": "boot#8"})
        await settle(h)
        assert not got["started"] and "waits for an approval" in got["why"]
        assert [c["scope"]["item"] for c in h.decisions.open_approvals(m)] == ["boot#8"]
    asyncio.run(go())


def test_a_start_waiting_for_approval_survives_the_owners_moves_while_its_entry_is_in_force(team):
    h, a, _gh, _apps, judge = team

    async def go():
        _steward, m = await a_maintainer(h, a)
        judge.yes = {"is ready"}
        base.said(a, m)
        await h.request({"op": "managed.start", "agent_token": token_of(a, m), "entry": "implementor", "item": "boot#7"})
        await settle(h)
        [card] = h.decisions.open_approvals(m)
        judge.yes = {"has stalled"}
        await turn_ends(h, a, m)
        assert state_of(a, m) == "stalled" and [c["id"] for c in h.decisions.open_approvals(m)] == [card["id"]]
    asyncio.run(go())


def test_a_design_spike_waiting_for_your_approval_holds_implement_and_leaving_withdraws_it(team):
    h, a, gh, _apps, judge = team

    async def go():
        name = (await a.start(a.defaults("implementor", "boot", 7)))["name"]
        await settle(h)
        [engineer] = children(h, a, name, "engineer")
        judge.yes = {"design question"}
        await turn_ends(h, a, name)
        [card] = [c for c in h.decisions.open_approvals(name) if c["scope"].get("type") == "managed"]
        judge.yes = set()
        gh.branches[engineer] = [pr()]
        await feed(h, ev("opened", "OPEN"), ev("checks", "passing"))
        assert (await give(h, engineer, status="done", summary=["Done."]))["ok"]
        await turn_ends(h, a, name)
        facts = await h.machine_run.facts_now(name, *a.machines.load(name))
        assert facts["started.design-spike"] is True and state_of(a, name) == "implement"
        assert [c["id"] for c in h.decisions.open_approvals(name) if c["scope"].get("type") == "managed"] == [card["id"]]
        # it waits for nothing more once the owner has left implement: the card and its report are withdrawn
        a.machines.move(name, "review", "hand")
        await settle(h)
        assert [c for c in h.decisions.open_approvals(name) if c["scope"].get("type") == "managed"] == []
        assert [r for r in a.machines.log.reports(state="open") if (r.get("action") or {}).get("entry") == "design-spike"] == []
    asyncio.run(go())


def test_a_start_the_cap_held_back_is_told_tried_again_and_qa_isnt_skipped_for_it(team, monkeypatch):
    from hubd import managed as managed_mod  # noqa: PLC0415
    h, a, gh, _apps, judge = team

    async def go():
        blocker = (await a.start(a.defaults("implementor", "boot", 8)))["name"]
        await settle(h)
        [held] = children(h, a, blocker, "engineer")
        monkeypatch.setattr(managed_mod, "MAX_MANAGED", 1)
        name = (await a.start(a.defaults("implementor", "boot", 7)))["name"]
        await settle(h)
        assert children(h, a, name, "engineer") == []
        assert "engineer hasn't started: 1 managed sessions are running" in base.told(a, name)
        a.shells.live.discard(held)  # room again
        await turn_ends(h, a, name)
        [engineer] = children(h, a, name, "engineer")
        # in qa, a user-facing change whose QA engineer can't start yet waits; it isn't taken for one that needs none
        gh.branches[engineer] = [pr()]
        await feed(h, ev("opened", "OPEN"), ev("checks", "passing"))
        assert (await give(h, engineer, status="done", summary=["Done."]))["ok"]
        await turn_ends(h, a, name)
        [reviewer] = children(h, a, name, "reviewer")
        (a.sessions / name / IDLE_FILE).touch()
        assert (await give(h, reviewer, verdict="pass", findings=[]))["ok"]
        await base.at_prompt(h, a, name)
        assert state_of(a, name) == "qa"
        a.shells.live.add(held)  # full again
        judge.yes = {"is user-facing: a person", "isn't user-facing"}
        await turn_ends(h, a, name)
        facts = await h.machine_run.facts_now(name, *a.machines.load(name))
        assert facts["when.qa"] is True and facts["started.qa"] is False
        assert state_of(a, name) == "qa" and children(h, a, name, "qa") == []
    asyncio.run(go())


def _peak(name: str, seen=()) -> int:
    """The most managed sessions a session of this workflow has running under it at once, its own and theirs."""
    if name in seen:
        raise AssertionError(f"{name} manages itself")
    d = LIBRARY.workflows[name]
    return max([sum(m.max * (1 + _peak(m.workflow, (*seen, name))) for _sid, m in machine.managed_of(d, sid))
                for sid, st in d.states.items() if st.initial is None] or [0])


def test_the_default_tree_fits_the_most_managed_sessions_at_once():
    from hubd.agents import MAX_MANAGED  # noqa: PLC0415
    # the Steward's maintainers, each with its implementors, each with an engineer and a design spike, or a QA engineer and a designer
    assert _peak("implementor") == 2 and _peak("repo-maintainer") == 9
    assert _peak("project-steward") <= MAX_MANAGED
    assert all(_peak(n) <= MAX_MANAGED for n in LIBRARY.workflows)


def test_one_maintainer_per_repository_through_concurrent_starts_resumes_and_after_a_final_state(team):
    h, a, _gh, _apps, _judge = team

    async def go():
        orig = a.shells.list

        async def slow():
            await asyncio.sleep(0)
            return await orig()
        a.shells.list = slow
        got = await asyncio.gather(*(a.start(a.defaults("repo-maintainer", "boot", None)) for _ in range(2)), return_exceptions=True)
        a.shells.list = orig
        [first] = [x["name"] for x in got if isinstance(x, dict)]
        assert any(isinstance(x, agents_module.AgentError) for x in got)
        a.shells.live.discard(first)  # it stopped; another may start, and the stopped one can't be resumed beside it
        second = (await a.start(a.defaults("repo-maintainer", "boot", None)))["name"]
        with pytest.raises(agents_module.AgentError, match="One runs for each repository"):
            await a.resume(first)
        # one in a final state (its budget spent) does nothing more: it doesn't hold the repository
        a.machines.move(second, "spent", "hand")
        third = (await a.start(a.defaults("repo-maintainer", "boot", None)))["name"]
        assert third not in (first, second)
    asyncio.run(go())


def test_the_engineers_pull_request_comes_before_one_the_implementor_opened(team):
    h, a, gh, _apps, judge = team

    async def go():
        name = (await a.start(a.defaults("implementor", "boot", 7)))["name"]
        await settle(h)
        [engineer] = children(h, a, name, "engineer")
        gh.branches[name] = [pr(number=40)]
        gh.branches[engineer] = [pr(number=PR)]
        await feed(h, ev("opened", "OPEN"))
        await turn_ends(h, a, name)
        assert [p["number"] for p in a.known_prs(name)] == [PR, 40]
    asyncio.run(go())


def test_the_drafting_states_are_named_in_the_launch_and_checked_on_load(tmp_path):
    import shutil  # noqa: PLC0415
    lib = tmp_path / "agents"
    shutil.copytree(REPO / "agents", lib)
    path = lib / "workflows" / "workflow-change.toml"
    path.write_text(path.read_text().replace('propose = "propose"', 'propose = "draft"'))
    with pytest.raises(agents_module.LibraryError, match="propose is a final state"):
        Library(lib)
    assert LIBRARY.actions["workflow-change"]["drafting"] == {"draft": "draft", "review": "review", "reviewer": "reviewer", "propose": "propose"}
    d = LIBRARY.workflows["workflow-change"]
    assert any(e.to == "stopped" and any("tokens.work" in r for r in e.requires) for e in d.states["work"].exits)


def test_a_refused_call_counts_as_a_failed_draft_and_a_replay_that_cant_run_fails_the_draft(team):
    h, a, gh, _apps, judge = team

    async def go():
        done, _engineer = await through_implement(h, a, gh, judge)  # a session that ran on implementor, to replay over
        name = (await a.run("workflow-change", None, None, notes="The workflow: implementor."))["name"]
        await settle(h)
        tok = token_of(a, name)
        bad = await h.request({"op": "wfdraft.make", "agent_token": tok, "name": "nosuch", "text": "x", "note": "x"})
        assert not bad["ok"]
        facts = await h.machine_run.facts_now(name, *a.machines.load(name))
        assert facts["drafts.failed"] == 1 and facts["draft.ok"] is False
        text = (REPO / "agents" / "workflows" / "implementor.toml").read_text().replace("Don't edit, commit or push yourself.", "Never edit.", 1)
        replayed = []
        real = h.workflows._replay

        def spy(req, who):
            replayed.append(req["session"])
            return real(req, who)
        h.workflows._replay = spy
        got = await h.request({"op": "wfdraft.make", "agent_token": tok, "name": "implementor", "text": text, "note": "Shorter."})
        assert got["passes"] and replayed == [a.session_id_of(done)] and got["replay"]["session"] == a.session_id_of(done)

        def broken(req, who):
            raise machinestore.StoreError("the log can't be read")
        h.workflows._replay = broken
        got = await h.request({"op": "wfdraft.make", "agent_token": tok, "name": "implementor", "text": text, "note": "Shorter."})
        assert not got["passes"] and any("the replay couldn't run" in p["text"] for p in got["problems"])
    asyncio.run(go())


def test_a_re_review_needs_a_new_draft_and_a_stale_draft_goes_back_to_drafting(team):
    h, a, _gh, _apps, _judge = team

    async def go():
        name = (await a.run("workflow-change", None, None, notes="The workflow: implement."))["name"]
        await settle(h)
        tok = token_of(a, name)
        good = _implement_text(lambda t: t.replace("Your pull request waits for review.", "It waits for review.", 1))
        assert (await h.request({"op": "wfdraft.make", "agent_token": tok, "name": "implement", "text": good, "note": "Shorter."}))["passes"]
        assert (await h.request({"op": "session.request_move", "agent_token": tok, "to": "review"}))["moved"]
        await settle(h)
        [reviewer] = [n for n, _r in h.managed.children(name, a.session_id_of(name), "reviewer")]
        (a.sessions / name / IDLE_FILE).touch()
        assert (await give(h, reviewer, verdict="fail", findings=["Too short."]))["ok"]
        await base.at_prompt(h, a, name)
        assert state_of(a, name) == "draft"
        # the same draft can't go to review again
        assert not (await h.request({"op": "session.request_move", "agent_token": tok, "to": "review"}))["moved"]
        again = good.replace("It waits for review.", "It waits for a review.", 1)
        assert (await h.request({"op": "wfdraft.make", "agent_token": tok, "name": "implement", "text": again, "note": "Shorter."}))["passes"]
        assert (await h.request({"op": "session.request_move", "agent_token": tok, "to": "review"}))["moved"]
        await settle(h)
        [_old, reviewer2] = [n for n, _r in h.managed.children(name, a.session_id_of(name), "reviewer")]
        # a version saved meanwhile: the draft is stale, so it isn't proposed and the author drafts again
        h.workflows.save("implement", "org", _implement_text(lambda t: t.replace("Your pull request waits for review.", "It waits.", 1)), 0, "me", "Mine.")
        (a.sessions / name / IDLE_FILE).touch()
        assert (await give(h, reviewer2, verdict="pass", findings=[]))["ok"]
        await base.at_prompt(h, a, name)
        assert [d for d in h.decisions.list() if d["kind"] == "workflow.change"] == []
        assert state_of(a, name) == "draft" and "v1 was saved since" in base.told(a, name)
        facts = await h.machine_run.facts_now(name, *a.machines.load(name))
        assert facts["draft.ok"] is False
    asyncio.run(go())
