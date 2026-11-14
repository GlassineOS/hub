# SPDX-License-Identifier: GPL-2.0-or-later
"""Rounds of work (012 FR-027, FR-028, FR-041, FR-054, FR-055, FR-072): a tool asked about first on a lasting card, moves on
request with a hand-over, waivers, reports that propose an action, and the implementor's rounds back to fix.

The hub is real behind hubd's own ops, as in test_implement_flow; the terminal, GitHub and the judge are faked. A locked
session's PreToolUse hook is played by calling hubd's hook op with a stand-in connection."""
import asyncio
import json

from hubd import agents as agents_module
from hubd import decisions as decisionlib
from hubd.agents import IDLE_FILE
from hubd.managed import handover_text

import test_implement_flow as base
from test_implement_flow import hub  # noqa: F401  (the fixture)
from test_implement_flow import HEAD, PR, ev, feed, settle, state_of, to_review, token_of, told

TOOL = "mcp__glassine-hub__merge_pr"
MERGE = {"repo": "boot", "number": PR, "head": HEAD}


class Hook:
    """The connection a hook holds: what hubd writes back, and a read that never ends (the hook sends nothing more)."""
    def __init__(self):
        self.lines = []
        self._never = asyncio.get_running_loop().create_future()

    async def read(self, _n):
        return await self._never

    def write(self, data):
        self.lines.append(json.loads(data))

    async def drain(self):
        pass


async def hook(h, a, name, tool=TOOL, arguments=None, timeout=5):
    """A locked session's PreToolUse hook for one call: what it prints, as hubd answered it. It must answer at once."""
    conn = Hook()
    req = {"op": "ask.wait", "agent_token": token_of(a, name), "how": "PreToolUse", "tool": tool, "input": dict(arguments or MERGE)}
    await asyncio.wait_for(h.ask_wait(req, conn, conn), timeout)
    [reply] = conn.lines
    out = (reply.get("output") or {}).get("hookSpecificOutput") or {}
    return out.get("permissionDecision"), out.get("permissionDecisionReason") or ""


async def merge_ready(h, a, gh):
    name = (await a.start(a.defaults("implement", "boot", 7)))["name"]
    await to_review(h, a, gh, name)
    await feed(h, ev("review", "APPROVED"))
    assert state_of(a, name) == "merge-ready"
    return name


def card_of(h, name) -> dict:
    [card] = h.decisions.open_asks(name)
    return card


def answer(h, card, verdict, **more):
    return h.request({"op": "decision." + verdict, "token": h.sessions.create(), "id": card["id"], **more})


# --- FR-054: a lasting card -------------------------------------------------------------------------------------------

def test_a_call_asked_about_first_returns_at_once_and_waits_on_a_lasting_card(hub, monkeypatch):
    h, a, gh, _apps, _judge = hub

    async def go():
        name = await merge_ready(h, a, gh)
        decision, why = await hook(h, a, name)
        card = card_of(h, name)
        assert decision == "deny" and card["id"] in why and "End your turn" in why and "nothing ran" in why
        assert card["kind"] == decisionlib.ASK and card["scope"]["tool"] == "merge_pr" and card["scope"]["arguments"] == MERGE
        # the same call again before an answer: the same card, nothing new, still refused with the reason
        decision, why = await hook(h, a, name)
        assert decision == "deny" and card["id"] in why and len(h.decisions.open_asks(name)) == 1
        # the tool server says why too: it waits for the card, not "not allowed"
        got = await h.request({"op": "ask.grant_use", "agent_token": token_of(a, name), "tool": "merge_pr", "arguments": MERGE})
        assert got["refused"] and f"waits for decision card {card['id']}" in got["error"]
        # it lasts: a day later it still waits, unlike a session's own request
        later = h.decisions.clock() + decisionlib.REQUEST_LIFE + 60
        monkeypatch.setattr(h.decisions, "clock", lambda: later)
        assert h.decisions.current_state(h.decisions._get(card["id"])) == "requested"
        # and survives a restart of hubd, still waiting
        assert decisionlib.Decisions(h.decisions.directory)._get(card["id"])["state"] == "requested"
        # an idle session waiting on its card isn't stalled: the answer moves it
        (a.sessions / name / IDLE_FILE).touch()
        assert h.managed._waits_on_someone(name, a.session_id_of(name), [])
    asyncio.run(go())


def test_a_yes_wakes_the_session_and_lets_that_call_through_once_for_that_head_only(hub):
    h, a, gh, _apps, _judge = hub

    async def go():
        name = await merge_ready(h, a, gh)
        sent = []
        real = a._send

        async def send(who, words, by=None):
            sent.append((who, words))
            return await real(who, words, by=by)
        a._send = send
        (a.sessions / name / IDLE_FILE).touch()
        await hook(h, a, name)
        card = card_of(h, name)
        got = await answer(h, card, "approve", words="Go ahead.")
        await settle(h)
        assert got["ok"], got
        # woken at its prompt with the hub's fixed words; what the maintainer said is in its turn, marked as theirs
        assert (name, f"Card {card['id']} is answered: allowed.") in sent
        assert f"Card {card['id']} is answered: the maintainer allowed your call of merge_pr" in told(a, name)
        assert "Go ahead." in told(a, name)
        # the merge decision is for that head only
        [merge] = [d for d in h.decisions.list() if d["kind"] == "merge"]
        assert merge["scope"]["head"] == HEAD and merge["state"] == "current"
        # another call (another head) isn't covered: it asks again on a card of its own
        moved = {**MERGE, "head": "b" * 40}
        gh.head = "b" * 40
        decision, why = await hook(h, a, name, arguments=moved)
        assert decision == "deny" and "card" in why
        gh.head = HEAD
        # the call as allowed goes through, once: the hook allows, the tool server lets it pass once
        assert (await hook(h, a, name)) == ("allow", "")
        assert (await h.request({"op": "ask.grant_use", "agent_token": token_of(a, name), "tool": "merge_pr", "arguments": MERGE}))["ok"]
        again = await h.request({"op": "ask.grant_use", "agent_token": token_of(a, name), "tool": "merge_pr", "arguments": MERGE})
        assert again["refused"]
        decision, why = await hook(h, a, name)
        assert decision == "deny" and "card" in why, "a second call is a new question"
    asyncio.run(go())


def test_a_no_comes_back_with_the_maintainers_words(hub):
    h, a, gh, _apps, _judge = hub

    async def go():
        name = await merge_ready(h, a, gh)
        await hook(h, a, name)
        card = card_of(h, name)
        got = await answer(h, card, "deny", why="Fix the flaky test first.")
        assert got["ok"] and got["decision"]["state"] == "ended"
        assert f"Card {card['id']} is answered: the maintainer said no to your call of merge_pr" in told(a, name)
        assert "Fix the flaky test first." in told(a, name)
        refused = await h.request({"op": "ask.grant_use", "agent_token": token_of(a, name), "tool": "merge_pr", "arguments": MERGE})
        assert refused["refused"] and "declined on card" in refused["error"] and "Fix the flaky test first." in refused["error"]
        assert not any(d["kind"] == "merge" for d in h.decisions.list())
    asyncio.run(go())


def test_a_card_whose_head_moved_is_withdrawn_and_the_session_asks_again(hub):
    h, a, gh, _apps, _judge = hub

    async def go():
        name = await merge_ready(h, a, gh)
        await hook(h, a, name)
        card = card_of(h, name)
        gh.head = "c" * 40
        got = await answer(h, card, "approve")
        assert not got["ok"] and "head moved" in got["error"]
        assert h.decisions.open_asks(name) == [] and "call merge_pr again with its head" in told(a, name)
        assert not any(d["kind"] == "merge" for d in h.decisions.list())
        # a call for a head that isn't the head makes no card at all
        decision, why = await hook(h, a, name)
        assert decision == "deny" and "isn't the head" in why and h.decisions.open_asks(name) == []
    asyncio.run(go())


def test_a_move_where_the_tool_isnt_asked_about_withdraws_its_card(hub):
    h, a, gh, _apps, _judge = hub

    async def go():
        name = await merge_ready(h, a, gh)
        await hook(h, a, name)
        card = card_of(h, name)
        assert (await h.request({"op": "machine.move", "token": h.sessions.create(), "name": name, "to": "escalated"}))["ok"]
        await settle(h)
        assert h.decisions.open_asks(name) == []
        assert "doesn't ask about merge_pr" in h.decisions._get(card["id"])["why_ended"]
        got = await answer(h, card, "approve")
        assert not got["ok"]
    asyncio.run(go())


def test_a_tool_not_granted_says_so(hub):
    """FR-054: the real reason: a tool its state doesn't hold is refused as that, never as a declined card."""
    h, a, _gh, _apps, _judge = hub

    async def go():
        name = (await a.start(a.defaults("implement", "boot", 7)))["name"]
        grant = json.loads((a.sessions / name / agents_module.GRANT_FILE).read_text())
        from hubd import grant_hook
        assert "isn't granted in this session's current workflow state" in grant_hook.decide(grant, "mcp__glassine-hub__close_pr")
    asyncio.run(go())


# --- FR-027: a move on request, with reasons and a hand-over --------------------------------------------------------------

from test_personas_flow import children, give, team, through_implement  # noqa: E402,F401  (team: the fixture)


def grant_of(a, name) -> dict:
    return json.loads((a.sessions / name / agents_module.GRANT_FILE).read_text())


async def ask_move(h, a, name, to, **words):
    got = await h.request({"op": "session.request_move", "agent_token": token_of(a, name), "to": to, **words})
    await settle(h)
    return got


def test_request_move_is_held_only_where_an_exit_moves_on_request_and_keeps_its_words(team):
    h, a, gh, _apps, judge = team

    async def go():
        name = (await a.start(a.defaults("implementor", "boot", 7)))["name"]
        await settle(h)
        # implement has no exit moved on request: the tool isn't held there, and a call says why
        assert state_of(a, name) == "implement"
        # listed for the whole workflow (Claude Code lists a server's tools once), held per state: the hook refuses it here
        assert "request_move" in a.scope(token_of(a, name))["tools"] and "request_move" not in grant_of(a, name)["hub_tools"]
        from hubd import grant_hook
        assert "isn't granted in this session's current workflow state" in grant_hook.decide(grant_of(a, name), "mcp__glassine-hub__request_move")
        got = await ask_move(h, a, name, "fix", reasons="x")
        assert got["refused"] and "request_move isn't held in work › implement: none of its exits moves on request" in got["error"]
        [engineer] = children(h, a, name, "engineer")
        gh.branches[engineer] = [{"number": PR, "state": "open", "merged_at": None, "head": {"sha": HEAD}}]
        await feed(h, ev("opened", "OPEN"), ev("checks", "passing"))
        assert (await give(h, engineer, status="done", summary=["Opened the draft pull request."]))["ok"]
        await base.turn_ends(h, a, name)
        assert state_of(a, name) == "review"
        # review has one (to fix): held now, in the scope hubd checks and in the grant the hook reads
        assert "request_move" in a.scope(token_of(a, name))["tools"] and "request_move" in grant_of(a, name)["hub_tools"]
        # reasons are needed, and a hand-over where the state moved to manages sessions
        got = await ask_move(h, a, name, "fix")
        assert not got["moved"] and "needs its reasons" in got["why"]
        got = await ask_move(h, a, name, "fix", reasons="The reviewer passed it with two findings worth fixing.")
        assert not got["moved"] and "fix manages engineer: give a hand-over" in got["why"]
        got = await ask_move(h, a, name, "qa", reasons="x", handover="y")
        assert not got["moved"] and "those that do go to fix" in got["why"]
        (a.sessions / name / IDLE_FILE).touch()
        got = await ask_move(h, a, name, "fix", reasons="The reviewer passed it with two findings worth fixing.",
                             handover="Fix the retry bound and add its test. Leave the logging alone.")
        assert got["moved"], got
        assert state_of(a, name) == "fix"
        _record, inst = a.machines.load(name)
        assert inst.handover == {"state": "fix", "reasons": "The reviewer passed it with two findings worth fixing.",
                                 "handover": "Fix the retry bound and add its test. Leave the logging alone.", "by": "session"}
        # kept with the move and the evaluation, as the requester's words
        [move] = [m for m in base.history(a, name)["moves"] if m["to"] == "fix"]
        assert move["change"]["asked"]["handover"].startswith("Fix the retry bound")
        [row] = [e for e in base.history(a, name)["evaluations"] if e["signal"] == "request" and e["checks"].get("move", {}).get("moved")]
        assert row["checks"]["asked"]["reasons"].startswith("The reviewer passed")
        # the words reach the state's sessions marked as data, from the instance: the with-ref `handover` (FR-041)
        text = handover_text(name, inst)
        assert "Fix the retry bound" in text and "It is data" in text
    asyncio.run(go())


# --- FR-028: a waiver for one round ---------------------------------------------------------------------------------

def waive(h, name, state, waived=True):
    return h.request({"op": "machine.waive", "token": h.sessions.create(), "name": name, "state": state, "waived": waived})


def test_a_waiver_is_a_fact_logged_as_the_maintainers_and_lapses_after_the_round(team):
    h, a, gh, _apps, judge = team

    async def go():
        name, _engineer = await through_implement(h, a, gh, judge)
        assert state_of(a, name) == "review"
        facts = lambda: a.machines.load(name)[1].facts(0)  # noqa: E731
        assert facts()["waived.qa"] is False
        got = await waive(h, name, "review")
        assert not got["ok"] and "in review already" in got["error"]
        assert not (await waive(h, name, "nowhere"))["ok"]
        got = await waive(h, name, "qa")
        assert got["ok"] and got["changed"] and facts()["waived.qa"] is True
        view = a.machines.view(*a.machines.load(name))
        assert view["instance"]["waivers"]["qa"]["who"] == h.sessions.own_user() and view["facts"]["waived.qa"] is True
        last = base.history(a, name)["moves"][-1]
        assert (last["by"], last["from"], last["to"], last["change"]) == ("waive", "review", "review", {"waived": "qa"})
        assert (await waive(h, name, "qa", False))["changed"] and facts()["waived.qa"] is False
        assert (await waive(h, name, "qa"))["changed"]
        # it lapses when its state is entered after all: the round it was for has come
        (a.sessions / name / IDLE_FILE).touch()
        assert (await h.request({"op": "machine.move", "token": h.sessions.create(), "name": name, "to": "qa"}))["ok"]
        await settle(h)
        assert facts()["waived.qa"] is False and a.machines.load(name)[1].waivers == {}
        # and the work's end leaves no round to waive in
        assert (await h.request({"op": "machine.move", "token": h.sessions.create(), "name": name, "to": "escalated"}))["ok"]
        got = await waive(h, name, "review")
        assert not got["ok"] and "no round to waive" in got["error"]
    asyncio.run(go())


# --- FR-055: a report that proposes an action -----------------------------------------------------------------------

def report(h, a, who, action, proposal="Do it."):
    return h.request({"op": "managed.report", "agent_token": token_of(a, who), "kind": "decision", "evidence": "Seen in the run.",
                      "proposal": proposal, "action": action})


def test_a_proposed_move_is_carried_out_when_the_maintainer_approves_it(team):
    h, a, gh, _apps, judge = team

    async def go():
        name, _engineer = await through_implement(h, a, gh, judge)
        [reviewer] = children(h, a, name, "reviewer")
        # checked when sent: a state the workflow has, and a hand-over where it manages sessions
        bad = await report(h, a, reviewer, {"type": "move", "for": "owner", "to": "nowhere"})
        assert not bad["ok"] and "to is one of" in bad["error"]
        bad = await report(h, a, reviewer, {"type": "move", "for": "owner", "to": "fix"})
        assert not bad["ok"] and "fix manages engineer" in bad["error"]
        sent = await report(h, a, reviewer, {"type": "move", "for": "owner", "to": "fix", "handover": "Fix the bound only."},
                            "Two findings should be fixed before QA.")
        assert sent["ok"] and sent["to"] == name and sent["proposes"] == f"move {name} to fix, with the reporter's hand-over"
        # the implementor approves: only the maintainer carries a proposed action out, so it goes up with that approval
        got = await h.request({"op": "managed.answer", "agent_token": token_of(a, name), "id": sent["id"], "decision": "approve"})
        assert got["ok"] and got["to"] == "you" and "only the maintainer carries out" in got["why"]
        [card] = [c for c in h.decisions.open_approvals(reviewer) if c["scope"].get("type") == "report"]
        assert card["scope"]["does"] == sent["proposes"] and "Approving does this as your decision" in card["why"]
        assert "Fix the bound only." in card["why"]
        (a.sessions / name / IDLE_FILE).touch()
        got = await answer(h, card, "approve")
        await settle(h)
        assert got["ok"], got
        assert state_of(a, name) == "fix"
        [move] = [m for m in base.history(a, name)["moves"] if m["to"] == "fix"]
        assert move["by"] == "hand" and move["who"] == h.sessions.own_user()
        assert a.machines.load(name)[1].handover["handover"] == "Fix the bound only."
        assert h.managed.log.get_report(card["scope"]["report"])["state"] == "answered"
    asyncio.run(go())


def test_a_proposal_that_no_longer_holds_keeps_the_report_open_and_says_why(team):
    h, a, _gh, _apps, _judge = team

    async def go():
        name = (await a.start(a.defaults("implementor", "boot", 7)))["name"]
        await settle(h)
        # its engineer runs, at its most at once: a start of another can't happen
        sent = await report(h, a, name, {"type": "start", "entry": "engineer"}, "Start another engineer.")
        assert sent["ok"] and sent["to"] == "you"
        [card] = [c for c in h.decisions.open_approvals(name) if c["scope"].get("type") == "report"]
        got = await answer(h, card, "approve")
        assert not got["ok"] and "this no longer holds" in got["error"] and "engineer has 1 running" in got["error"]
        assert h.decisions.current_state(h.decisions._get(card["id"])) == "requested"
        assert h.managed.log.get_report(sent["id"])["state"] == "open"
        # a report with no action: the card says approving only answers
        plain = await h.request({"op": "managed.report", "agent_token": token_of(a, name), "kind": "decision",
                                 "evidence": "Seen.", "proposal": "Look at it."})
        [other] = [c for c in h.decisions.open_approvals(name) if c["scope"].get("report") == plain["id"]]
        assert "Approving only sends your answer back" in other["why"]
        # a waiver it proposes for its own round is carried out as yours
        sent = await report(h, a, name, {"type": "waive", "state": "qa"}, "QA has nothing to run here.")
        [card] = [c for c in h.decisions.open_approvals(name) if c["scope"].get("report") == sent["id"]]
        assert (await answer(h, card, "approve"))["ok"]
        assert a.machines.load(name)[1].waivers["qa"]["who"] == h.sessions.own_user()
    asyncio.run(go())


def test_a_machine_record_from_before_hand_overs_and_waivers_still_loads():
    from hubd import instances
    text = (base.REPO / "agents" / "workflows" / "implementor.toml").read_text()
    raw = instances.Instance.new(text, 0.0).to_json()
    del raw["handover"], raw["waivers"]
    inst = instances.Instance.from_json(raw)
    assert inst.handover is None and inst.waivers == {} and inst.facts(0.0)["waived.review"] is False
    # a stored definition whose grant lists request_move, as they did, still passes the checks
    old = text.replace('"submit_result", "mark_ready"]', '"submit_result", "request_move", "mark_ready"]', 1)
    assert old != text and not [f for f in instances.machine.check(instances.machine.parse(old)) if f.kind == "problem"]


def test_a_proposed_start_is_carried_out_when_the_maintainer_approves_it(team):
    h, a, gh, _apps, judge = team

    async def go():
        name, _engineer = await through_implement(h, a, gh, judge)
        judge.yes = {"a person sees", "accepted design board"}
        [reviewer] = children(h, a, name, "reviewer")
        assert (await give(h, reviewer, verdict="pass", findings=[]))["ok"]
        await base.turn_ends(h, a, name)
        assert state_of(a, name) == "qa" and children(h, a, name, "designer") == []
        sent = await report(h, a, name, {"type": "start", "entry": "designer"}, "Check it against the boards.")
        assert sent["ok"] and sent["proposes"] == f"start {name}'s designer"
        [card] = [c for c in h.decisions.open_approvals(name) if c["scope"].get("report") == sent["id"]]
        got = await answer(h, card, "approve")
        await settle(h)
        assert got["ok"], got
        [designer] = children(h, a, name, "designer")
        assert f"What report {sent['id']} proposed is carried out: {name}'s designer started." in told(a, name)
        assert h.decisions._get(card["id"])["why_ended"] == f"approved: {name}'s designer started."
        assert designer
    asyncio.run(go())
