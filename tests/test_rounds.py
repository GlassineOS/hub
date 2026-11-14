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
