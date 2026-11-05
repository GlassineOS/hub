# SPDX-License-Identifier: GPL-2.0-or-later
"""What a session asks a person: through the real hook script and hubd's socket."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from hubd import asks as asks_module
from hubd.asks import Asks, AskError, _always
from tests.test_hubd import Harness, fake_gh, run  # noqa: F401: fake_gh is a fixture

HOOK = Path(asks_module.__file__).with_name("ask_hook.py")
TOKEN = "session-secret"
OTHER = "other-session-secret"
BASH = {"hook_event_name": "PermissionRequest", "tool_name": "Bash", "tool_input": {"command": "git push", "description": "Push it"},
        "permission_suggestions": [{"type": "addRules", "rules": [{"toolName": "Bash", "ruleContent": "git push:*"}], "behavior": "allow", "destination": "localSettings"}]}
QUESTION = {"questions": [{"question": "Tea or coffee?", "header": "Drink", "options": [{"label": "Tea", "description": ""}, {"label": "Coffee", "description": ""}]}]}


class FakeAgents:
    def __init__(self, wait=600):
        self.wait = wait
        self.marks = []
        self.state = "Working"

    def scope(self, token):
        return {TOKEN: {"session": "s1", "tools": [], "persona": "reviewer"}, OTHER: {"session": "s2", "tools": [], "persona": "reviewer"}}.get(token)

    def asker(self, name, tool=None):
        return {"title": "Review", "persona": "reviewer", "repo": "hub", "number": 4}, self.wait

    def mark_asking(self, name, asking, prompt_up=False):
        self.marks.append((asking, prompt_up))

    async def session_state(self, name):
        return {"state": self.state}


class Hook:
    """The script as Claude Code runs it: event on stdin, and what it prints is the answer."""

    def __init__(self, tmp_path, path, event, token=TOKEN):
        (tmp_path / "tool-token").write_text(token + "\n")
        self.args = [sys.executable, "-I", str(HOOK), str(path), str(tmp_path / "tool-token")]
        self.event = event

    async def __aenter__(self):
        self.process = await asyncio.create_subprocess_exec(*self.args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.process.stdin.write(json.dumps(self.event).encode())
        self.process.stdin.close()
        return self

    async def __aexit__(self, *a):
        if self.process.returncode is None:
            self.process.kill()
            await self.process.wait()

    async def printed(self):
        out, err = await asyncio.wait_for(self.process.communicate(), 10)
        assert self.process.returncode == 0 and not err
        return json.loads(out) if out.strip() else None


async def open_asks(h, want=1):
    for _ in range(500):
        asks = h.hubd.asks.list()["open"]
        if len(asks) >= want:
            return asks
        await asyncio.sleep(0.01)
    raise AssertionError("nothing arrived")


async def closed(h):
    for _ in range(500):
        if not h.hubd.asks.list()["open"]:
            return h.hubd.asks.list()["answered"][0]
        await asyncio.sleep(0.01)
    raise AssertionError("still open")


def harness(tmp_path, fake_gh, wait=600):
    h = Harness(tmp_path, fake_gh)
    h.hubd.agents = FakeAgents(wait)
    return h


def test_allowing_from_the_hub_is_what_the_hook_prints(tmp_path, fake_gh):
    async def go():
        async with harness(tmp_path, fake_gh) as h, Hook(tmp_path, h.path, BASH) as hook:
            token = await h.login()
            [ask] = await open_asks(h)
            assert ask["session"] == "s1" and ask["input"]["command"] == "git push" and ask["always"] == "git push …"
            assert h.hubd.agents.marks == [(True, False)]
            reply = await h.call(op="ask.answer", token=token, id=ask["id"], verdict="allow")
            assert reply["ask"]["state"] == "allowed"
            assert await hook.printed() == {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}
            assert h.hubd.asks.list()["open"] == []
            await asyncio.sleep(0.05)
            assert h.hubd.agents.marks == [(True, False), (False, False)]
    run(go())


def test_denying_tells_claude_why(tmp_path, fake_gh):
    async def go():
        async with harness(tmp_path, fake_gh) as h, Hook(tmp_path, h.path, BASH) as hook:
            token = await h.login()
            [ask] = await open_asks(h)
            await h.call(op="ask.answer", token=token, id=ask["id"], verdict="deny", reason="after the boot test")
            decision = (await hook.printed())["hookSpecificOutput"]["decision"]
            assert decision == {"behavior": "deny", "message": "after the boot test"}
    run(go())


def test_always_allow_stays_in_the_session_whatever_was_suggested(tmp_path, fake_gh):
    async def go():
        async with harness(tmp_path, fake_gh) as h, Hook(tmp_path, h.path, BASH) as hook:
            token = await h.login()
            [ask] = await open_asks(h)
            reply = await h.call(op="ask.answer", token=token, id=ask["id"], verdict="always")
            assert reply["ask"]["state"] == "always"
            [update] = (await hook.printed())["hookSpecificOutput"]["decision"]["updatedPermissions"]
            assert update["destination"] == "session" and update["rules"][0]["ruleContent"] == "git push:*"
    run(go())


@pytest.mark.parametrize("suggestion", [{"type": "setMode", "mode": "bypassPermissions", "destination": "session"},
                                        {"type": "addRules", "behavior": "deny", "rules": [{"toolName": "Bash"}]},
                                        {"type": "addDirectories", "directories": ["/"], "destination": "session"},
                                        {"type": "addRules", "behavior": "allow", "rules": ["x"]}, "nonsense"])
def test_only_plain_offers_become_always_allow(suggestion):
    assert _always([suggestion]) == ([], None)


def test_accepting_edits_says_so():
    kept, words = _always([{"type": "setMode", "mode": "acceptEdits", "destination": "userSettings"}])
    assert kept[0]["destination"] == "session" and words == "file edits in this session"


def test_a_question_is_answered_with_its_own_input_and_your_words(tmp_path, fake_gh):
    async def go():
        event = {"hook_event_name": "PermissionRequest", "tool_name": "AskUserQuestion", "tool_input": QUESTION}
        async with harness(tmp_path, fake_gh) as h, Hook(tmp_path, h.path, event) as hook:
            token = await h.login()
            [ask] = await open_asks(h)
            assert ask["kind"] == "question" and ask["terminal"]
            for bad in ({}, {"Other?": "x"}, {"Tea or coffee?": " "}, {"Tea or coffee?": 3}, None):
                assert not (await h.call(op="ask.answer", token=token, id=ask["id"], verdict="answer", answers=bad))["ok"]
            assert not (await h.call(op="ask.answer", token=token, id=ask["id"], verdict="allow"))["ok"]
            assert not (await h.call(op="ask.answer", token=token, id=ask["id"], verdict="deny"))["ok"]
            reply = await h.call(op="ask.answer", token=token, id=ask["id"], verdict="answer", answers={"Tea or coffee?": ["Green tea, actually"]})
            assert reply["ask"]["state"] == "answered"
            decision = (await hook.printed())["hookSpecificOutput"]["decision"]
            assert decision["updatedInput"] == {**QUESTION, "answers": {"Tea or coffee?": "Green tea, actually"}}
    run(go())


def test_a_held_question_comes_back_as_a_pre_tool_use_answer(tmp_path, fake_gh):
    async def go():
        event = {"hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion", "tool_input": QUESTION}
        async with harness(tmp_path, fake_gh, wait=None) as h, Hook(tmp_path, h.path, event) as hook:
            token = await h.login()
            [ask] = await open_asks(h)
            assert not ask["terminal"] and ask["left"] is None
            await h.call(op="ask.answer", token=token, id=ask["id"], verdict="answer", answers={"Tea or coffee?": "Tea"})
            out = (await hook.printed())["hookSpecificOutput"]
            assert out["hookEventName"] == "PreToolUse" and out["permissionDecision"] == "allow"
            assert out["updatedInput"]["answers"] == {"Tea or coffee?": "Tea"}
    run(go())


def test_several_picks_reach_claude_as_one_answer(tmp_path, fake_gh):
    async def go():
        event = {"hook_event_name": "PermissionRequest", "tool_name": "AskUserQuestion", "tool_input": QUESTION}
        async with harness(tmp_path, fake_gh) as h, Hook(tmp_path, h.path, event) as hook:
            token = await h.login()
            [ask] = await open_asks(h)
            await h.call(op="ask.answer", token=token, id=ask["id"], verdict="answer", answers={"Tea or coffee?": ["Tea", "Coffee"]})
            assert (await hook.printed())["hookSpecificOutput"]["decision"]["updatedInput"]["answers"] == {"Tea or coffee?": "Tea, Coffee"}
    run(go())


def test_card_ids_arent_reused_after_a_restart():
    async def go():
        first, second = Asks(), Asks()
        one = first.add("s", "PermissionRequest", "Bash", {"command": "a"}, None, None, 600)
        two = second.add("s", "PermissionRequest", "Bash", {"command": "b"}, None, None, 600)
        assert one.id != two.id
        with pytest.raises(AskError):
            second.answer(one.id, "allow")
        with pytest.raises(AskError):
            second.answer(1, "allow")
    run(go())


def test_an_unknown_ask_op_does_nothing(tmp_path, fake_gh):
    async def go():
        async with harness(tmp_path, fake_gh) as h:
            reply = await h.call(op="ask.nonsense", token=await h.login(), name="s1")
            assert not reply["ok"] and "unknown" in reply["error"]
    run(go())


def test_a_connection_lost_while_waiting_leaves_it_to_the_terminal(tmp_path):
    async def go():
        async def hang_up(reader, writer):
            await reader.readline()
            writer.close()
        path = tmp_path / "h.sock"
        server = await asyncio.start_unix_server(hang_up, path=str(path))
        async with server, Hook(tmp_path, path, BASH) as hook:
            assert await hook.printed() is None
    run(go())


def test_only_a_login_answers(tmp_path, fake_gh):
    async def go():
        async with harness(tmp_path, fake_gh) as h, Hook(tmp_path, h.path, BASH):
            [ask] = await open_asks(h)
            for token in (TOKEN, "agent-secret", None, "wrong"):
                reply = await h.call(op="ask.answer", token=token, agent_token=token, id=ask["id"], verdict="allow")
                assert reply["denied"]
                assert (await h.call(op="ask.list", token=token, agent_token=token))["denied"]
            assert h.hubd.asks.list()["open"]
    run(go())


@pytest.mark.parametrize("token", ["wrong", "agent-secret"])
def test_only_a_sessions_own_token_asks(tmp_path, fake_gh, token):
    async def go():
        async with harness(tmp_path, fake_gh) as h, Hook(tmp_path, h.path, BASH, token=token) as hook:
            assert await hook.printed() is None
            assert h.hubd.asks.list()["open"] == []
    run(go())


def test_answering_in_the_terminal_closes_the_card_and_a_late_answer_changes_nothing(tmp_path, fake_gh):
    async def go():
        async with harness(tmp_path, fake_gh) as h:
            token = await h.login()
            async with Hook(tmp_path, h.path, BASH) as hook:
                [ask] = await open_asks(h)
                hook.process.kill()  # what Claude Code does when you answer in the terminal
                assert (await closed(h))["state"] == "terminal"
            reply = await h.call(op="ask.answer", token=token, id=ask["id"], verdict="allow")
            assert not reply["ok"] and "already" in reply["error"]
            assert h.hubd.asks.list()["answered"][0]["state"] == "terminal"
            assert h.hubd.agents.marks[-1] == (False, False)
    run(go())


async def moved(tmp_path, h, event):
    hook = Hook(tmp_path, h.path, event)
    async with hook:
        assert await hook.printed() is None


def test_a_yes_in_the_terminal_closes_the_card_and_lets_the_hook_go(tmp_path, fake_gh):
    async def go():
        async with harness(tmp_path, fake_gh) as h, Hook(tmp_path, h.path, BASH) as hook:
            await open_asks(h)
            await moved(tmp_path, h, {**BASH, "hook_event_name": "PostToolUse", "tool_input": {"command": "something else"}})
            await moved(tmp_path, h, {**BASH, "hook_event_name": "PostToolUse", "tool_name": "Edit"})
            assert len(h.hubd.asks.list()["open"]) == 1
            await moved(tmp_path, h, {**BASH, "hook_event_name": "PostToolUse"})
            assert h.hubd.asks.list()["answered"][0]["state"] == "terminal"
            assert await hook.printed() is None
    run(go())


def test_an_answer_in_the_terminal_closes_the_question(tmp_path, fake_gh):
    async def go():
        event = {"hook_event_name": "PermissionRequest", "tool_name": "AskUserQuestion", "tool_input": QUESTION}
        async with harness(tmp_path, fake_gh) as h, Hook(tmp_path, h.path, event) as hook:
            await open_asks(h)
            await moved(tmp_path, h, {**event, "hook_event_name": "PostToolUse", "tool_input": {**QUESTION, "answers": {"Tea or coffee?": "Tea"}, "annotations": {}}})
            assert await hook.printed() is None and h.hubd.asks.list()["open"] == []
    run(go())


def test_a_failed_tool_also_closes_its_card(tmp_path, fake_gh):
    async def go():
        async with harness(tmp_path, fake_gh) as h, Hook(tmp_path, h.path, BASH) as hook:
            await open_asks(h)
            await moved(tmp_path, h, {**BASH, "hook_event_name": "PostToolUseFailure"})
            assert await hook.printed() is None and h.hubd.asks.list()["open"] == []
    run(go())


@pytest.mark.parametrize("size", [70_000, 200_000])
def test_a_yes_in_the_terminal_closes_a_card_too_long_to_show(tmp_path, fake_gh, size):
    async def go():
        event = {**BASH, "tool_input": {"command": "x" * size}}
        async with harness(tmp_path, fake_gh) as h, Hook(tmp_path, h.path, event) as hook:
            [ask] = await open_asks(h)
            assert ask["too_long"]
            await moved(tmp_path, h, {**event, "hook_event_name": "PostToolUse"})
            assert await hook.printed() is None and h.hubd.asks.list()["open"] == []
    run(go())


def test_a_turn_that_ended_leaves_no_prompts(tmp_path, fake_gh):
    async def go():
        async with harness(tmp_path, fake_gh) as h, Hook(tmp_path, h.path, BASH) as hook:
            await open_asks(h)
            await moved(tmp_path, h, {"hook_event_name": "Stop"})
            assert await hook.printed() is None and h.hubd.asks.list()["answered"][0]["state"] == "terminal"
    run(go())


def test_a_session_cant_close_anothers_card(tmp_path, fake_gh):
    async def go():
        async with harness(tmp_path, fake_gh) as h, Hook(tmp_path, h.path, BASH):
            await open_asks(h)
            assert (await h.call(op="ask.moved", agent_token="wrong", tool="Bash", input=BASH["tool_input"]))["refused"]
            assert (await h.call(op="ask.moved", agent_token=OTHER, how="Stop"))["ok"]
            assert (await h.call(op="ask.moved", agent_token=OTHER, how="PostToolUse", tool="Bash", input=BASH["tool_input"]))["ok"]
            assert len(h.hubd.asks.list()["open"]) == 1
    run(go())


def test_a_second_answer_changes_nothing(tmp_path, fake_gh):
    async def go():
        async with harness(tmp_path, fake_gh) as h, Hook(tmp_path, h.path, BASH) as hook:
            token = await h.login()
            [ask] = await open_asks(h)
            assert (await h.call(op="ask.answer", token=token, id=ask["id"], verdict="deny"))["ok"]
            assert not (await h.call(op="ask.answer", token=token, id=ask["id"], verdict="allow"))["ok"]
            assert (await hook.printed())["hookSpecificOutput"]["decision"]["behavior"] == "deny"
    run(go())


def test_a_stopped_session_is_not_called_answered(tmp_path, fake_gh):
    async def go():
        async with harness(tmp_path, fake_gh) as h, Hook(tmp_path, h.path, BASH) as hook:
            await open_asks(h)
            h.hubd.agents.state = "Stopped"
            hook.process.kill()
            assert (await closed(h))["state"] == "stopped"
    run(go())


def test_when_the_hub_stops_waiting_nothing_is_approved(tmp_path, fake_gh):
    async def go():
        async with harness(tmp_path, fake_gh, wait=0.1) as h, Hook(tmp_path, h.path, BASH) as hook:
            assert await hook.printed() is None
            assert h.hubd.asks.list()["answered"][0]["state"] == "timeout"
            await asyncio.sleep(0.05)
            assert h.hubd.agents.marks[-1] == (False, True)  # still waiting for you, in the terminal
    run(go())


@pytest.mark.parametrize("how", ["PermissionRequest", "PreToolUse"])
def test_without_hubd_the_hook_leaves_it_to_the_terminal(tmp_path, how):
    async def go():
        async with Hook(tmp_path, tmp_path / "gone.sock", {**BASH, "hook_event_name": how}) as hook:
            assert await hook.printed() is None
    run(go())


def test_too_long_for_a_card_can_only_be_denied_here(tmp_path, fake_gh):
    async def go():
        event = {**BASH, "tool_input": {"command": "x" * 200_000}}
        async with harness(tmp_path, fake_gh) as h, Hook(tmp_path, h.path, event) as hook:
            token = await h.login()
            [ask] = await open_asks(h)
            assert ask["too_long"] and ask["input"] is None
            for verdict in ("allow", "always"):
                assert not (await h.call(op="ask.answer", token=token, id=ask["id"], verdict=verdict))["ok"]
            assert (await h.call(op="ask.answer", token=token, id=ask["id"], verdict="deny"))["ok"]
            assert (await hook.printed())["hookSpecificOutput"]["decision"]["behavior"] == "deny"
    run(go())


def test_a_question_too_long_to_show_stays_in_the_terminal(tmp_path, fake_gh):
    async def go():
        event = {"hook_event_name": "PermissionRequest", "tool_name": "AskUserQuestion", "tool_input": {"questions": [{"question": "x" * 200_000}]}}
        async with harness(tmp_path, fake_gh) as h, Hook(tmp_path, h.path, event) as hook:
            assert await hook.printed() is None
            assert h.hubd.asks.list()["open"] == []
    run(go())


def test_one_session_cant_bury_the_others():
    async def go():
        asks = Asks()
        for _ in range(asks_module.MAX_OPEN):
            asks.add("noisy", "PermissionRequest", "Bash", {"command": "x"}, None, None, 600)
        with pytest.raises(AskError):
            asks.add("noisy", "PermissionRequest", "Bash", {"command": "x"}, None, None, 600)
        asks.add("quiet", "PermissionRequest", "Bash", {"command": "x"}, None, None, 600)
    run(go())


def test_a_yes_lapses_and_too_many_lose_the_oldest(monkeypatch):
    from hubd import asks as asks_module
    asks = asks_module.Asks()

    async def go():
        tool = asks_module.TOOL_PREFIX + "comment_pr"
        yes = lambda n: asks.answer(asks.add("s", "PreToolUse", tool, {"number": n}, None, None, 600).id, "allow")
        yes(1)
        now = asks_module.time.time()
        monkeypatch.setattr(asks_module.time, "time", lambda: now + asks_module.GRANT_LIFE + 1)
        assert not asks.use_grant("s", "comment_pr", {"number": 1}), "too late"
        monkeypatch.undo()
        for n in range(asks_module.MAX_GRANTS + 1):
            yes(n)
        assert not asks.use_grant("s", "comment_pr", {"number": 0}), "the oldest went: you're asked again"
        assert asks.use_grant("s", "comment_pr", {"number": asks_module.MAX_GRANTS})
    asyncio.run(go())
