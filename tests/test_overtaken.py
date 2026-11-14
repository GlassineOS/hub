# SPDX-License-Identifier: GPL-2.0-or-later
"""Work that would sit still without anyone being told (spec 012): failing checks send the implementor to fix, an owner at its
prompt is woken when what it manages hands back or ends, a workflow that can't move by itself is put to the maintainer, and
reports that events overtook are withdrawn, by the hub on a move or by their reporter.

The hub is real behind hubd's ops, as in test_personas_flow; the terminal, GitHub and the judge are faked."""
import asyncio
import json

import pytest

from hubd import managed as managed_module
from hubd.agents import IDLE_FILE, OUTCOMES_FILE

import test_implement_flow as base
import test_personas_flow as personas
from test_implement_flow import hub  # noqa: F401  (the fixture)
from test_implement_flow import ev, feed, settle, state_of, token_of, told
from test_personas_flow import children, give, pr

FAILING = [{"name": "build", "workflowName": "CI", "conclusion": "FAILURE",
            "detailsUrl": "https://github.com/GlassineOS/boot/actions/runs/123/job/4"},
           {"name": "lint", "workflowName": "CI", "conclusion": "SUCCESS", "detailsUrl": "https://github.com/GlassineOS/boot/actions/runs/123/job/5"}]


class YieldingShells(base.FakeShells):
    """A terminal that takes a moment to answer, as tmux does: a stop and a start can interleave."""
    async def list(self):
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return await super().list()

    async def kill(self, name):
        await asyncio.sleep(0)
        await super().kill(name)


@pytest.fixture
def team(request, monkeypatch):
    monkeypatch.setattr(base, "FakeGh", personas.BranchGh)
    monkeypatch.setattr(base, "Judge", personas.AskedJudge)
    monkeypatch.setattr(base, "FakeShells", YieldingShells)
    return request.getfixturevalue("hub")


def record(gh_or_a, name):
    return json.loads((gh_or_a.sessions / name / "session.json").read_text())


def watch_sends(a) -> list:
    sent = []
    real = a._send

    async def send(who, words, by=None):
        sent.append((who, words))
        return await real(who, words, by=by)
    a._send = send
    return sent


async def started(h, a):
    name = (await a.start(a.defaults("implementor", "boot", 7)))["name"]
    await settle(h)
    [engineer] = children(h, a, name, "engineer")
    return name, engineer


async def failing_pr(h, gh, engineer):
    gh.branches[engineer] = [pr()]
    gh.pr_more = {"statusCheckRollup": FAILING}
    await feed(h, ev("opened", "OPEN"), ev("checks", "failing"))


# --- 1. failing checks go to fix ------------------------------------------------------------------------------------------

def test_a_done_engineer_whose_checks_fail_is_resumed_in_fix_with_the_failing_runs(team):
    h, a, gh, _apps, _judge = team

    async def go():
        name, engineer = await started(h, a)
        await failing_pr(h, gh, engineer)
        (a.sessions / name / IDLE_FILE).touch()
        sent = watch_sends(a)
        assert (await give(h, engineer, status="done", summary=["Opened the pull request."]))["ok"]
        await settle(h)
        assert state_of(a, name) == "fix"
        # implement held push already: the move asks no confirm, and starts nothing that needs an approval
        assert h.decisions.open_widenings(name) == [] and h.decisions.open_approvals(name) == []
        # the same engineer, stopped and resumed for the new round although the terminal answered slowly
        assert children(h, a, name, "engineer") == [engineer] and engineer in a.shells.live
        said = told(a, engineer)
        assert "A new round." in said and "build (workflow CI) failure https://github.com/GlassineOS/boot/actions/runs/123/job/4" in said
        assert "lint" not in said.split("A new round.")[1]
        assert (engineer, managed_module.NEW_ROUND_WORDS) in sent  # a resumed conversation gets a word to begin its round
        # its grant reads the runs' logs, within its owner's
        assert {"list_runs", "get_run", "get_run_log"} <= set(record(a, engineer)["config"]["hub_tools"])
        # the idle implementor is woken once, with the return's values and the move together
        mine = [w for who, w in sent if who == name]
        assert mine == [f"{engineer}, your engineer, handed back: status done, 1 line of summary."], mine
        return name
    name = asyncio.run(go())
    assert [(m["from"], m["to"]) for m in personas.history(a, name)["moves"]] == [("implement", "fix")]


def test_a_move_by_hand_from_implement_to_fix_stops_then_resumes_the_same_engineer(team):
    """The old state's stops come before the new state's starts: the engineer about to be stopped doesn't count against the
    fix entry's `max`, and `reuse = "resume"` resumes the session implement's entry of the same name ran."""
    h, a, gh, _apps, _judge = team

    async def go():
        name, engineer = await started(h, a)
        gh.branches[engineer] = [pr()]
        assert engineer in a.shells.live
        a.machines.move(name, "fix", "hand", who="you")
        await settle(h)
        assert state_of(a, name) == "fix"
        assert children(h, a, name, "engineer") == [engineer] and engineer in a.shells.live
        assert "A new round." in told(a, engineer)
        log = personas.history(a, name)["evaluations"]
        assert not [e for e in log if e["failed"] and e["proposal"] == "start engineer"], log
        ends = [i for i, e in enumerate(log) if e["proposal"] == "engineer ended"]
        starts = [i for i, e in enumerate(log) if e["proposal"] == "start engineer" and not e["failed"]]
        assert ends and starts and ends[-1] < starts[-1]
    asyncio.run(go())


def test_an_automatic_start_on_entering_that_didnt_happen_is_tried_again_soon(team, monkeypatch):
    h, a, gh, _apps, _judge = team

    async def go():
        name, engineer = await started(h, a)
        gh.branches[engineer] = [pr()]
        monkeypatch.setattr(managed_module, "MAX_MANAGED", 0)  # no room when it enters fix
        waited = []

        async def sleep(seconds):
            waited.append(seconds)
            monkeypatch.setattr(managed_module, "MAX_MANAGED", 20)  # room by the retry
        h.managed._sleep = sleep
        a.machines.move(name, "fix", "hand", who="you")
        await settle(h)
        assert waited == [managed_module.START_RETRIES[0]]
        assert children(h, a, name, "engineer") == [engineer] and engineer in a.shells.live
        assert h.managed.facts(name, a.machines.load(name)[0])["started.engineer"] is True
    asyncio.run(go())


def test_failing_checks_in_review_go_to_fix_without_a_confirm(team):
    h, a, gh, _apps, judge = team

    async def go():
        name, engineer = await personas.through_implement(h, a, gh, judge)
        assert state_of(a, name) == "review"
        gh.pr_more = {"statusCheckRollup": FAILING}
        (a.sessions / name / IDLE_FILE).touch()  # at its prompt, where the move that adds push back relaunches it
        await feed(h, ev("checks", "failing"))
        assert state_of(a, name) == "fix"
        assert h.decisions.open_widenings(name) == []  # review dropped push; implement held it, so fix asks no confirm
        assert "build (workflow CI) failure" in told(a, engineer)
    asyncio.run(go())


# --- 2. an idle owner is woken ----------------------------------------------------------------------------------------------

def test_an_owner_is_woken_when_a_session_under_it_ends_by_itself_but_not_when_it_stops_it(team):
    h, a, gh, _apps, _judge = team

    async def go():
        name, engineer = await started(h, a)
        (a.sessions / name / IDLE_FILE).touch()
        sent = watch_sends(a)
        a.shells.live.discard(engineer)  # its terminal went: it ended by itself
        await h.managed.sweep()
        await settle(h)
        assert (name, f"{engineer}, your engineer, ended.") in sent
    asyncio.run(go())


# --- 3. stalls ----------------------------------------------------------------------------------------------------------------

async def stalled_in_fix(h, a, gh):
    """In fix with the engineer done again and the checks still failing: nothing moves it."""
    name, engineer = await started(h, a)
    await failing_pr(h, gh, engineer)
    assert (await give(h, engineer, status="done", summary=["Opened it."]))["ok"]
    assert state_of(a, name) == "fix"
    gh.head = "b" * 40
    gh.branches[engineer] = [pr(sha=gh.head)]
    await feed(h, ev("head", old_head=base.HEAD, new_head=gh.head), ev("checks", "failing"))
    assert (await give(h, engineer, status="done", summary=["Tried again."]))["ok"]
    assert state_of(a, name) == "fix"
    for who in (name, engineer):  # both at their prompts, with what was queued for them delivered
        (a.sessions / who / IDLE_FILE).touch()
        await a._send_next(who)
        (a.sessions / who / IDLE_FILE).touch()
    a._sends.clear()
    return name, engineer


def test_a_stalled_workflow_raises_one_card_after_the_quiet_time_which_a_move_ends(team):
    h, a, gh, _apps, _judge = team

    async def go():
        name, _engineer = await stalled_in_fix(h, a, gh)
        now = [1_000_000.0]
        a.machines.clock = lambda: now[0]
        await h.managed.watch()
        assert not [c for c in h.decisions.open_approvals(name) if c["scope"].get("type") == "stalled"]
        now[0] += managed_module.STALL_AFTER - 1
        await h.managed.watch()
        assert not [c for c in h.decisions.open_approvals(name) if c["scope"].get("type") == "stalled"]
        sent = watch_sends(a)
        now[0] += 2
        await h.managed.watch()
        await h.managed.watch()  # once a stay
        await settle(h)
        [card] = [c for c in h.decisions.open_approvals(name) if c["scope"].get("type") == "stalled"]
        says = card["scope"]["says"]
        assert says.startswith(f"{name} stalled in work › fix: to work › review needs pr.checks == pass (pr.checks is fail)"), says
        assert "to escalated needs managed.engineer.status == blocked (managed.engineer.status is done)" in says
        # the machine panel says so too, and the session hears it with the same facts
        record_, inst = a.machines.load(name)
        assert a.machines.view(record_, inst)["stalled"]["why"][0].startswith("to work › review needs pr.checks == pass")
        assert "can't move by itself" in told(a, name)
        assert any(who == name and "stalled in work › fix" in w for who, w in sent)
        # any move ends it
        a.machines.move(name, "review", "hand", who="you")
        await settle(h)
        assert not [c for c in h.decisions.open_approvals(name) if c["scope"].get("type") == "stalled"]
        assert a.machines.view(*a.machines.load(name))["stalled"] is None
    asyncio.run(go())


def test_pending_checks_or_a_working_session_are_a_wait_not_a_stall(team):
    h, a, gh, _apps, _judge = team

    async def go():
        name, engineer = await stalled_in_fix(h, a, gh)
        record_, inst = a.machines.load(name)
        live = await h.managed._live()
        assert h.managed.stall_of(name, record_, inst, live)
        (a.sessions / engineer / IDLE_FILE).unlink()  # the engineer works
        assert h.managed.stall_of(name, record_, inst, live) is None
        (a.sessions / engineer / IDLE_FILE).touch()
        await feed(h, ev("checks", "pending"))
        assert h.managed.stall_of(name, record_, inst, live) is None
    asyncio.run(go())


# --- 4. reports overtaken by events ---------------------------------------------------------------------------------------

async def report(h, a, name, evidence="The engineer is still working; pr.checks has no answer yet."):
    got = await h.request({"op": "managed.report", "agent_token": token_of(a, name), "kind": "blocker",
                           "evidence": evidence, "proposal": "Wait for it."})
    assert got["ok"], got
    return got["id"]


def report_cards(h, name):
    return [c for c in h.decisions.open_approvals(name) if c["scope"].get("type") == "report"]


def test_an_open_report_is_withdrawn_when_its_sessions_machine_moves(team):
    h, a, gh, _apps, _judge = team

    async def go():
        name, engineer = await started(h, a)
        rid = await report(h, a, name)
        [card] = report_cards(h, name)
        await failing_pr(h, gh, engineer)
        assert (await give(h, engineer, status="done", summary=["Opened it."]))["ok"]
        assert state_of(a, name) == "fix"
        assert a.machines.log.get_report(rid)["state"] == "withdrawn"
        assert report_cards(h, name) == []
        ended = h.decisions._get(card["id"])
        assert ended["state"] == "ended" and "withdrawn" in ended["why_ended"] and "moved on to work › fix" in ended["why_ended"]
        assert f"your open reports {rid} are withdrawn" in told(a, name)
        # withdrawn isn't answered: an exit waiting for an answer doesn't take it for one
        assert h.managed.facts(name, a.machines.load(name)[0])["report.answered"] is False
    asyncio.run(go())


def test_a_reporter_is_woken_with_its_open_reports_and_withdraws_one_of_its_own(team):
    h, a, gh, _apps, _judge = team

    async def go():
        name, engineer = await started(h, a)
        rid = await report(h, a, name)
        (a.sessions / name / IDLE_FILE).touch()
        sent = watch_sends(a)
        gh.branches[engineer] = [pr()]
        await feed(h, ev("opened", "OPEN"), ev("checks", "pending"))  # no move: the checks are still running
        assert (await give(h, engineer, status="done", summary=["Opened it."]))["ok"]
        await settle(h)
        assert state_of(a, name) == "implement"
        [words] = [w for who, w in sent if who == name]
        assert f"Your open reports: {rid}, a blocker, waiting for the maintainer." in words and "withdraw_report" in words
        # only its own: the engineer can't take back the implementor's report
        other = await h.request({"op": "managed.withdraw", "agent_token": token_of(a, engineer), "id": rid, "why": "done"})
        assert not other["ok"] and "isn't a report you sent" in other["error"]
        got = await h.request({"op": "managed.withdraw", "agent_token": token_of(a, name), "id": rid,
                               "why": "The engineer handed back."})
        assert got["ok"] and got["withdrawn"], got
        assert report_cards(h, name) == [] and a.machines.log.get_report(rid)["state"] == "withdrawn"
        again = await h.request({"op": "managed.withdraw", "agent_token": token_of(a, name), "id": rid, "why": "again"})
        assert not again["ok"] and "isn't waiting" in again["error"]
    asyncio.run(go())


def test_a_change_of_a_fact_a_report_named_wakes_its_reporter(team):
    h, a, gh, _apps, _judge = team

    async def go():
        name, engineer = await started(h, a)
        gh.branches[engineer] = [pr()]
        await feed(h, ev("opened", "OPEN"), ev("checks", "pending"))
        await h.machine_run.facts_now(name, *a.machines.load(name))  # the pull request is looked up
        rid = await report(h, a, name)
        (a.sessions / name / IDLE_FILE).touch()
        sent = watch_sends(a)
        await h.managed.watch()
        await settle(h)
        assert [w for who, w in sent if who == name] == []  # nothing changed yet
        await feed(h, ev("checks", "failing"))
        await h.managed.watch()
        await h.managed.watch()  # once a change
        await settle(h)
        mine = [w for who, w in sent if who == name]
        assert len(mine) == 1 and mine[0].startswith(f"A fact report {rid} named has changed: pr.checks is now fail."), mine
    asyncio.run(go())


def test_a_session_that_reports_up_also_has_withdraw_report():
    from hubd.agents import CHAIN_TOOLS
    assert "withdraw_report" in CHAIN_TOOLS
    from app.hub import tools  # noqa: PLC0415
    from app.hub.github import GitHub  # noqa: PLC0415
    names = {t.name for t in asyncio.run(tools.build(GitHub.__new__(GitHub), None).every_tool())}
    assert {"report_up", "withdraw_report", "answer_report"} <= names


def test_the_outcomes_file_name_is_what_told_reads():
    assert OUTCOMES_FILE  # the helper above reads the same file the hook does
