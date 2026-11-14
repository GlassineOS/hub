# SPDX-License-Identifier: GPL-2.0-or-later
"""Work that would sit still without anyone being told (spec 012): failing checks send the implementor to fix, an owner at its
prompt is woken when what it manages hands back or ends, a workflow that can't move by itself is put to the maintainer, and
reports that events overtook are withdrawn, by the hub on a move or by their reporter.

The hub is real behind hubd's ops, as in test_personas_flow; the terminal, GitHub and the judge are faked."""
import asyncio
import json
import os
import time

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
        assert mine == [f"{engineer}, your engineer, handed back: status done, 1 line of summary. {managed_module.MOVED_WORDS}"], mine
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


async def in_qa_unjudged(h, a, gh, judge, lose_wake):
    """The live sequence: the reviewer hands back pass on hub:managed.return, the pass it starts moves the idle owner from
    review to qa, whose QA entry has a `when` judged on the owner's turn ends, and the reviewer is ended. `lose_wake` stands
    in for what became of the wake on entering."""
    name, _engineer = await personas.through_implement(h, a, gh, judge)
    [reviewer] = children(h, a, name, "reviewer")
    (a.sessions / name / IDLE_FILE).touch()
    restore = await lose_wake(h, a, name)
    assert (await give(h, reviewer, verdict="pass", findings=[]))["ok"]
    await settle(h)
    restore()
    assert state_of(a, name) == "qa" and not h.managed._running(reviewer, await h.managed._live())  # the move ended it
    assert h.managed._unjudged(name, a.machines.load(name)[1]) == ["qa"]
    assert not judged_in_qa(a, name)
    return name


def judged_in_qa(a, name) -> list:
    return [e for e in base.history(a, name)["evaluations"] if e["signal"].startswith("hub:managed.when") and e["state"] == "qa"]


async def wake_dropped(h, a, name):
    """The wake on entering didn't reach it: sent while it read as busy, held for a relaunch that never ran, lost."""
    real = h.managed._wake

    async def dropped(who, words=""):
        return None
    h.managed._wake = dropped
    return lambda: setattr(h.managed, "_wake", real)


async def prompt_never_empty(h, a, name):
    """Its prompt never reads as empty (a suggested prompt's grey text, a draft): the wake waits in its queue for good."""
    real = a.shells.prompt_empty

    async def never(who):
        return False if who == name else await real(who)
    a.shells.prompt_empty = never
    return lambda: None


def test_an_idle_owner_whose_wake_on_entering_a_when_was_lost_is_woken_once_on_the_tick(team, monkeypatch):
    h, a, gh, _apps, judge = team
    monkeypatch.setattr(managed_module, "TURN_GRACE", 0.0)

    async def go():
        name = await in_qa_unjudged(h, a, gh, judge, wake_dropped)
        (a.sessions / name / IDLE_FILE).touch()
        sent = watch_sends(a)
        await h.managed.watch()
        await settle(h)
        assert [w for who, w in sent if who == name] == [managed_module.WHEN_WORDS]
        (a.sessions / name / IDLE_FILE).touch()  # its turn went by without a judgement (the judge failed, say): once a stay
        await h.managed.watch()
        await settle(h)
        assert [w for who, w in sent if who == name] == [managed_module.WHEN_WORDS]
        # the turn it was woken for ends: the `when` is judged, not user-facing, and it goes on to merge-ready
        judge.yes = set()
        await base.turn_ends(h, a, name)
        assert state_of(a, name) == "merge-ready"
        assert judged_in_qa(a, name)
    asyncio.run(go())


def test_a_turn_a_pass_or_a_turn_just_ended_holds_the_ticks_wake_back(team, monkeypatch):
    h, a, gh, _apps, judge = team

    async def go():
        name = await in_qa_unjudged(h, a, gh, judge, wake_dropped)
        sent = watch_sends(a)
        (a.sessions / name / IDLE_FILE).touch()
        await h.managed.watch()  # it has just come to its prompt: the pass its turn's end started judges it
        monkeypatch.setattr(managed_module, "TURN_GRACE", 0.0)
        (a.sessions / name / IDLE_FILE).unlink()  # at work
        await h.managed.watch()
        await settle(h)
        assert [w for who, w in sent if who == name] == []
    asyncio.run(go())


def test_an_unjudged_when_with_the_owner_idle_and_only_the_hubs_wake_queued_is_a_stall(team, monkeypatch):
    h, a, gh, _apps, judge = team
    monkeypatch.setattr(managed_module, "TURN_GRACE", 0.0)

    async def go():
        name = await in_qa_unjudged(h, a, gh, judge, prompt_never_empty)
        (a.sessions / name / IDLE_FILE).touch()
        assert a._sends.get(name)  # the wake, waiting behind a prompt that never empties
        record_, inst = a.machines.load(name)
        live = await h.managed._live()
        why = h.managed.stall_of(name, record_, inst, live)
        assert why and why[0].startswith("qa's when isn't judged yet"), why
        assert any("to merge-ready needs not when.qa (when.qa is not judged yet)" in w for w in why), why
        assert any("managed.qa.verdict is nothing, as it hasn't started" in w for w in why), why
        # words of a person waiting for its prompt are a wait: its turn comes with them
        a._sends[name].append("How does it stand?")
        a._from[name].append(None)
        assert h.managed.stall_of(name, record_, inst, live) is None
        a._sends[name].pop()
        a._from[name].pop()
        sent = watch_sends(a)
        now = [1_000_000.0]
        a.machines.clock = lambda: now[0]
        await h.managed.watch()
        now[0] += managed_module.STALL_AFTER + 1
        await h.managed.watch()
        await settle(h)
        [card] = [c for c in h.decisions.open_approvals(name) if c["scope"].get("type") == "stalled"]
        assert "qa's when isn't judged yet" in card["scope"]["says"]
        # the tick doesn't wake it again over the hub's words still queued
        assert not [w for who, w in sent if who == name and w == managed_module.WHEN_WORDS]
    asyncio.run(go())


def test_a_when_judged_this_round_or_a_start_without_one_is_not_put_as_unjudged(team):
    h, a, gh, _apps, judge = team

    async def go():
        name = await in_qa_unjudged(h, a, gh, judge, wake_dropped)
        judge.yes = {"is user-facing: a person"}
        await base.turn_ends(h, a, name)
        assert children(h, a, name, "qa") and h.managed._unjudged(name, a.machines.load(name)[1]) == []
    asyncio.run(go())


# --- 4. reports overtaken by events ---------------------------------------------------------------------------------------

# --- a move's words reach an idle session -------------------------------------------------------------------------------

async def kept(h, a, name):
    """The wake on entering qa went as it should."""
    return lambda: None


def old_idle(a, name, ago=3600.0):
    """At its prompt for a while: its turn ended `ago` seconds back."""
    idle = a.sessions / name / IDLE_FILE
    idle.touch()
    then = time.time() - ago
    os.utime(idle, (then, then))


def test_an_idle_owner_moved_to_merge_ready_on_its_turns_end_is_woken_for_its_instructions_once(team):
    """The live case: qa's `when` judged no on the owner's turn end moves it to merge-ready, a final state whose
    instructions ask for the merge. Its prompt gets the hub's fixed words; the instructions wait in its turn."""
    h, a, gh, _apps, judge = team

    async def go():
        name = await in_qa_unjudged(h, a, gh, judge, kept)
        sent = watch_sends(a)
        judge.yes = set()
        (a.sessions / name / IDLE_FILE).touch()
        await base.turn_ends(h, a, name)
        assert state_of(a, name) == "merge-ready"
        assert [w for who, w in sent if who == name] == [managed_module.MOVED_WORDS]
        assert "Workflow: now in merge-ready." in told(a, name) and "`merge_pr`" in told(a, name)
        old_idle(a, name)  # its turn didn't come (the paste went nowhere): the tick doesn't send it twice
        await h.managed.watch()
        await settle(h)
        assert [w for who, w in sent if who == name] == [managed_module.MOVED_WORDS]
    asyncio.run(go())


def test_a_session_at_work_when_it_moved_is_woken_once_its_turn_ends_and_not_before(team, monkeypatch):
    h, a, gh, _apps, judge = team

    async def go():
        name = await in_qa_unjudged(h, a, gh, judge, kept)
        sent = watch_sends(a)
        (a.sessions / name / IDLE_FILE).unlink(missing_ok=True)  # at work
        a.machines.move(name, "merge-ready", "hand", who="you")
        await settle(h)
        assert state_of(a, name) == "merge-ready" and "Workflow: now in merge-ready." in told(a, name)
        await h.managed.watch()
        await settle(h)
        assert [w for who, w in sent if who == name] == []  # nothing typed into a turn
        (a.sessions / name / IDLE_FILE).touch()
        await h.managed.watch()  # its turn has just ended: the pass that end started may move it again
        await settle(h)
        assert [w for who, w in sent if who == name] == []
        old_idle(a, name)
        a._sends[name] = ["How does it stand?"]  # a person's words on their way: the turn they begin reads it
        a._from[name] = [None]
        await h.managed.watch()
        assert [w for who, w in sent if who == name] == []
        a._sends.pop(name)
        a._from.pop(name)
        await h.managed.watch()
        await settle(h)
        assert [w for who, w in sent if who == name] == [managed_module.MOVED_WORDS]
        old_idle(a, name)
        await h.managed.watch()  # once a move
        await settle(h)
        assert [w for who, w in sent if who == name] == [managed_module.MOVED_WORDS]
    asyncio.run(go())


def test_words_its_turn_read_or_a_relaunch_under_way_hold_the_ticks_wake_back(team):
    h, a, gh, _apps, judge = team

    async def go():
        name = await in_qa_unjudged(h, a, gh, judge, kept)
        sent = watch_sends(a)
        (a.sessions / name / IDLE_FILE).unlink(missing_ok=True)
        a.machines.move(name, "merge-ready", "hand", who="you")
        await settle(h)
        old_idle(a, name)
        h.managed.relaunching = lambda who: who == name  # its move relaunches it: the wake comes after
        await h.managed.watch()
        await settle(h)
        assert [w for who, w in sent if who == name] == []
        h.managed.relaunching = lambda who: False
        (a.sessions / name / OUTCOMES_FILE).unlink()  # a turn of its own read them meanwhile
        await h.managed.watch()
        await settle(h)
        assert [w for who, w in sent if who == name] == []
    asyncio.run(go())


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


# --- follow-ups: waits that aren't stalls, counters, rounds across a relaunch, resumes that fail, reports answered late ---

def _clock(a, start=1_000_000.0):
    now = [start]
    a.machines.clock = lambda: now[0]
    return now


def test_a_report_naming_a_counter_never_wakes_its_reporter(team):
    """time.*, tokens.*, rounds.* change by themselves: naming one isn't a fact that can overtake the report."""
    h, a, _gh, _apps, _judge = team

    async def go():
        name, _engineer = await started(h, a)
        now = _clock(a, time.time())  # after it entered implement: time.implement counts up
        await report(h, a, name, evidence="We have been in time.implement long; still waiting.")
        (a.sessions / name / IDLE_FILE).touch()
        sent = watch_sends(a)
        for _ in range(4):
            now[0] += 30
            await h.managed.watch()
            await settle(h)
            (a.sessions / name / IDLE_FILE).touch()
        assert not [w for who, w in sent if who == name and "named has changed" in w]
    asyncio.run(go())


def test_a_named_fact_wakes_its_reporter_once_a_value_and_not_more_often_than_the_gap(team):
    h, a, gh, _apps, _judge = team

    async def go():
        name, engineer = await started(h, a)
        now = _clock(a)
        gh.branches[engineer] = [pr()]
        await feed(h, ev("opened", "OPEN"), ev("checks", "pending"))
        await h.machine_run.facts_now(name, *a.machines.load(name))
        rid = await report(h, a, name)
        sent = watch_sends(a)

        async def tick(checks=None, later=0.0):
            if checks:
                await feed(h, ev("checks", checks))
            now[0] += later
            (a.sessions / name / IDLE_FILE).touch()
            await h.managed.watch()
            await settle(h)
            return [w for who, w in sent if who == name and "named has changed" in w]
        assert len(await tick("failing")) == 1
        assert len(await tick("passing", 10)) == 1          # within the gap: it waits
        woken = await tick(None, managed_module.NAMED_WAKE_GAP)  # the gap is over: the new value is told
        assert len(woken) == 2 and "pr.checks is now pass" in woken[-1] and rid in woken[-1]
        assert len(await tick("failing", managed_module.NAMED_WAKE_GAP + 1)) == 2  # fail was told already
    asyncio.run(go())


def test_a_widening_move_clears_last_rounds_returns_at_once(team):
    """review → fix widens (fix adds push), so the engineer starts after the relaunch; meanwhile its `done` from implement
    mustn't take fix on to review once the checks pass."""
    h, a, gh, _apps, judge = team

    async def go():
        name, _engineer = await personas.through_implement(h, a, gh, judge)
        assert state_of(a, name) == "review"
        h.effects.relaunch_wait = 120
        (a.sessions / name / IDLE_FILE).unlink(missing_ok=True)  # in a turn: its relaunch waits for its prompt
        sent, launches = watch_sends(a), a.shells.made.count(name)
        gh.pr_more = {"statusCheckRollup": FAILING}
        assert (await h.request({"op": "feed.record", "events": [ev("checks", "failing")]}))["kept"] == 1
        for _ in range(4):
            await h.machine_run.idle()
            await asyncio.sleep(0)
        assert state_of(a, name) == "fix" and a.machines.load(name)[1].managed["engineer"]["returns"] == {}
        gh.pr_more = {"statusCheckRollup": []}
        assert (await h.request({"op": "feed.record", "events": [ev("checks", "passing")]}))["kept"] == 1
        for _ in range(4):
            await h.machine_run.idle()
            await asyncio.sleep(0)
        assert state_of(a, name) == "fix"  # no hand-back in this round yet
        assert [w for who, w in sent if who == name] == []  # nothing typed into its turn, nor before its relaunch
        (a.sessions / name / IDLE_FILE).touch()
        await settle(h)
        assert [(m["from"], m["to"]) for m in personas.history(a, name)["moves"]][-1] != ("fix", "review")
        # relaunched at its prompt, then woken there once for fix's instructions, which wait in its turn
        assert a.shells.made.count(name) == launches + 1
        assert [w for who, w in sent if who == name] == [managed_module.MOVED_WORDS]
        assert "Workflow: now in work › fix." in told(a, name)
    asyncio.run(go())


def test_two_widening_moves_before_the_first_relaunch_keep_the_second_moves_starts(team):
    """What a move waits to start is keyed by that move: the first move's relaunch doesn't start, or drop, the second's."""
    h, a, gh, _apps, _judge = team

    async def go():
        name, engineer = await started(h, a)
        gh.branches[engineer] = [pr()]
        a.machines._watchers = [w for w in a.machines._watchers if getattr(w, "__self__", None) is not h.effects]  # no relaunch
        now = _clock(a)
        a.machines.move(name, "review", "hand", who="you")
        await settle(h)
        now[0] += 5
        a.machines.move(name, "fix", "hand", who="you")
        await settle(h)
        [first] = list(h.managed._deferred[name])
        now[0] += 5
        a.machines.move(name, "review", "hand", who="you")
        now[0] += 5
        a.machines.move(name, "fix", "hand", who="you")
        await settle(h)
        [second] = list(h.managed._deferred[name])
        assert first != second and first[0] == second[0] == "fix"
        h.managed.relaunched(name, True, first)
        await settle(h)
        assert engineer not in a.shells.live and second in h.managed._deferred[name]
        assert "engineer" not in h.managed.waiting_starts(name, a.machines.load(name)[1])  # it waits for its relaunch
        h.managed.relaunched(name, True, second)
        await settle(h)
        assert children(h, a, name, "engineer") == [engineer] and engineer in a.shells.live
    asyncio.run(go())


def test_a_start_tried_again_gives_up_once_its_owner_has_moved(team, monkeypatch):
    h, a, gh, _apps, _judge = team

    async def go():
        name, engineer = await started(h, a)
        gh.branches[engineer] = [pr()]
        monkeypatch.setattr(managed_module, "MAX_MANAGED", 0)
        tries = []
        real_start = h.managed.start

        async def start(owner, entry, by="entry", item=None):
            tries.append(by)
            return await real_start(owner, entry, by, item)
        h.managed.start = start

        async def sleep(_seconds):
            # it moves on while the retry waits, and there is room again
            a.machines._watchers = [w for w in a.machines._watchers if getattr(w, "__self__", None) is not h.managed]
            a.machines.move(name, "implement", "hand", who="you")
            monkeypatch.setattr(managed_module, "MAX_MANAGED", 20)
        h.managed._sleep = sleep
        a.machines.move(name, "fix", "hand", who="you")
        await settle(h)
        assert tries == ["entry"]  # tried once on entering fix, and not again for a state it left
    asyncio.run(go())


def test_a_resume_that_cant_happen_starts_a_fresh_session_and_wakes_nobody_over_and_over(team):
    h, a, gh, _apps, _judge = team

    async def go():
        name, engineer = await started(h, a)
        gh.branches[engineer] = [pr()]

        async def broken(child, **kw):
            raise managed_module.AgentError("a later session used the name and its branch")
        a.resume = broken
        (a.sessions / name / IDLE_FILE).touch()
        sent = watch_sends(a)
        a.machines.move(name, "fix", "hand", who="you")
        await settle(h)
        for _ in range(3):
            await h.managed.sweep()
            await settle(h)
            (a.sessions / name / IDLE_FILE).touch()
            await h.request({"op": "session.signal", "agent_token": token_of(a, name), "how": "Stop"})
            await settle(h)
        assert len([w for who, w in sent if who == name]) <= 1
        [fresh] = [n for n in children(h, a, name, "engineer") if n != engineer]
        assert fresh in a.shells.live and "can't be resumed" in told(a, name)
        assert record(a, engineer)["owner"].get("ended") is not False  # never marked running again
    asyncio.run(go())


def test_waiting_for_an_answer_to_its_report_is_not_a_stall_and_the_report_stays_open(team):
    """workflow-change's ask waits on report.answered: entering it keeps the report it waits on, and the wait isn't a stall."""
    h, a, _gh, _apps, _judge = team

    async def go():
        name = (await a.run("workflow-change", None, None, notes="The workflow: implement."))["name"]
        await settle(h)
        rid = await report(h, a, name, evidence="Three drafts failed.")
        a.machines.move(name, "ask", "hand", who="you")
        await settle(h)
        assert state_of(a, name) == "ask" and a.machines.log.get_report(rid)["state"] == "open"
        (a.sessions / name / IDLE_FILE).touch()
        a._sends.clear()
        now = _clock(a)
        await h.managed.watch()
        now[0] += managed_module.STALL_AFTER + 5
        await h.managed.watch()
        await settle(h)
        assert "stalled" not in [c["scope"].get("type") for c in h.decisions.open_approvals(name)]
    asyncio.run(go())


def test_an_answer_that_reaches_a_report_just_withdrawn_goes_to_the_reporter_as_a_note(team):
    h, a, gh, _apps, _judge = team

    async def go():
        name, engineer = await started(h, a)
        rid = await report(h, a, name)
        [card] = report_cards(h, name)
        await failing_pr(h, gh, engineer)
        assert (await give(h, engineer, status="done", summary=["Opened it."]))["ok"]
        assert a.machines.log.get_report(rid)["state"] == "withdrawn"
        from hubd.decisions import DecisionError  # noqa: PLC0415
        with pytest.raises(DecisionError, match="withdrawn .* your answer and your words went to"):
            await h.effects.answer_approval(card["id"], True, "you", "Wait for the checks.")
        said = told(a, name)
        assert f"Report {rid} was withdrawn" in said and "Wait for the checks." in said and "Nothing was carried out" in said
    asyncio.run(go())


def test_a_withdrawn_report_has_its_own_answer_and_everyone_on_its_way_hears_it(team):
    h, a, _gh, _apps, _judge = team

    async def go():
        name, engineer = await started(h, a)
        rid = await report(h, a, engineer, evidence="The tests need a device.")  # to its owner, which can answer
        assert a.machines.log.get_report(rid)["to_name"] == name
        got = await h.request({"op": "managed.withdraw", "agent_token": token_of(a, engineer), "id": rid, "why": "Found an emulator."})
        assert got["ok"], got
        assert f"Report {rid} from {engineer} is withdrawn: Found an emulator." in told(a, name)
        late = await h.request({"op": "managed.answer", "agent_token": token_of(a, name), "id": rid, "decision": "approve"})
        assert not late["ok"] and "was withdrawn (Found an emulator.)" in late["error"], late
    asyncio.run(go())
