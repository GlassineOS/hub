# SPDX-License-Identifier: GPL-2.0-or-later
"""What sessions are asking a person right now: a permission prompt, or a question from Claude.

A hook in the session (ask_hook.py) holds a connection to hubd until someone answers. So this lives in
memory, for as long as the prompt does. When hubd restarts, each hook sees the connection end, and the
prompt carries on in the terminal alone. Only a login can answer: see Hubd.request.

Answered in the terminal, a prompt goes one of two ways. No, or Esc, and Claude Code ends the hook, which
hubd sees as the connection ending. Yes, and it leaves the hook running, so the tool's PostToolUse says so.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import time

WAIT = 600  # seconds the hub waits; then the prompt is the terminal's alone, and nothing was approved
HOOK_MARGIN = 30  # the hook's own limit is longer, so hubd is the one that says time's up
FOREVER = 20 * 24 * 3600  # a hook has to have some limit, and this session's question has no other. Under 2^31 ms
MAX_INPUT = 60_000  # characters. Longer doesn't go on a card, as a card has to show all of it
MAX_OPEN = 8  # for one session, so a session can't bury everyone else's
MAX_QUESTIONS = 8
MAX_ANSWER = 2000
MAX_REASON = 2000
KEEP_ANSWERED = 50
DENIED = "Not now."
GRANT_LIFE = 120  # seconds for the tool call to follow the hook's allow
MAX_GRANTS = 16
TOOL_PREFIX = "mcp__glassine-hub__"
QUESTION_TOOL = "AskUserQuestion"
HOW = ("PermissionRequest", "PreToolUse")


class AskError(Exception):
    pass


def _rule(rule) -> str | None:
    if not isinstance(rule, dict) or not isinstance(rule.get("toolName"), str):
        return None
    content = rule.get("ruleContent")
    if not isinstance(content, str):
        return rule["toolName"]
    # The button has to show the wildcard: `git push:*` covers `git push --force` too.
    return content.removesuffix(":*").removesuffix(" *") + " …" if content.endswith((":*", " *")) else content or None


def _always(suggestions) -> tuple[list[dict], str | None]:
    """Claude Code's own offer, kept to this session whatever it says, and in words.

    Only kinds with a plain meaning: nothing goes into a settings file, and no mode gets wider than
    accepting edits."""
    kept, words = [], []
    for s in suggestions if isinstance(suggestions, list) else ():
        if not isinstance(s, dict):
            continue
        if s.get("type") == "addRules" and s.get("behavior") == "allow" and isinstance(s.get("rules"), list):
            names = [_rule(r) for r in s["rules"]]
            if names and all(names):
                kept.append({**s, "destination": "session"})
                words += names
        elif s.get("type") == "setMode" and s.get("mode") == "acceptEdits":
            kept.append({**s, "destination": "session"})
            words.append("file edits in this session")
    return kept, ", ".join(dict.fromkeys(words)) or None


def _shown(tool_input) -> dict | None:
    """What can go on a card, which has to show all of it. The hook sends nothing above its own, larger limit."""
    return tool_input if isinstance(tool_input, dict) and len(json.dumps(tool_input)) <= MAX_INPUT else None


def _same(arguments) -> str:
    return json.dumps(arguments, sort_keys=True)


def _questions(tool_input) -> list[dict]:
    questions = tool_input.get("questions") if isinstance(tool_input, dict) else None
    if not (isinstance(questions, list) and 0 < len(questions) <= MAX_QUESTIONS):
        raise AskError("not a question this can show")
    for q in questions:
        if not (isinstance(q, dict) and isinstance(q.get("question"), str) and q["question"]):
            raise AskError("not a question this can show")
    return questions


class Ask:
    def __init__(self, ask_id: str, session: str, how: str, tool: str, tool_input, suggestions, agent: dict | None, wait: float | None):
        self.id = ask_id
        self.session = session
        self.how = how
        self.tool = tool
        self.kind = "question" if tool == QUESTION_TOOL else "permission"
        self.too_long = tool_input is None
        self.input = tool_input
        self.updates, self.always = _always(suggestions)
        self.agent = agent
        self.wait = wait
        self.made = time.time()
        self.state = "pending"
        self.said = None  # what Claude was told
        self.answered_at = None
        self.future: asyncio.Future = asyncio.get_running_loop().create_future()

    def view(self) -> dict:
        now = time.time()
        return {"id": self.id, "session": self.session, "kind": self.kind, "tool": self.tool, "input": self.input, "too_long": self.too_long,
                "always": self.always, "agent": self.agent, "state": self.state, "said": self.said, "answered_at": self.answered_at,
                # When a PreToolUse hook holds the question, the terminal shows no prompt of its own.
                "terminal": self.how == "PermissionRequest", "waited": round(now - self.made), "wait": self.wait,
                "left": None if self.wait is None else max(0, round(self.made + self.wait - now))}

    def same_call(self, tool_input) -> bool:
        if self.too_long:
            return tool_input is None
        if self.kind == "question":  # the answer comes back in its input
            return isinstance(tool_input, dict) and tool_input.get("questions") == self.input.get("questions")
        return tool_input == self.input

    def output(self, behavior: str, message=None, updated_input=None, updates=None) -> dict:
        """What the hook prints. Worked out here, from the prompt, not from what a page sent."""
        if self.how == "PreToolUse":
            out = {"hookEventName": "PreToolUse", "permissionDecision": behavior}
            if message:
                out["permissionDecisionReason"] = message
            if updated_input:
                out["updatedInput"] = updated_input
            return {"hookSpecificOutput": out}
        decision = {"behavior": behavior}
        if message:
            decision["message"] = message
        if updated_input:
            decision["updatedInput"] = updated_input
        if updates:
            decision["updatedPermissions"] = updates
        return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": decision}}


class Asks:
    def __init__(self):
        self._open: dict[str, Ask] = {}
        self._done: list[Ask] = []
        self._grants: list[tuple[str, str, str, float]] = []  # session, tool, its arguments, until

    def use_grant(self, session: str, tool: str, arguments) -> bool:
        """Whether you allowed exactly this call, for the tool server. Once: a second call is a new question."""
        now = time.time()
        self._grants = [g for g in self._grants if g[3] > now]
        wanted = (session, tool, _same(arguments))
        for grant in self._grants:
            if grant[:3] == wanted:
                self._grants.remove(grant)
                return True
        return False

    def add(self, session: str, how, tool, tool_input, suggestions, agent: dict | None, wait: float | None) -> Ask:
        if how not in HOW:
            raise AskError("not a hook this knows")
        if not (isinstance(tool, str) and tool):
            raise AskError("no tool named")
        tool_input = _shown(tool_input)
        if tool == QUESTION_TOOL:
            _questions(tool_input)  # a question nobody can read can't be answered from a card
        if sum(a.session == session for a in self._open.values()) >= MAX_OPEN:
            raise AskError("this session has enough open already")
        # Never reused, even after a restart, so an old page's card can't answer a new prompt.
        ask = Ask(secrets.token_urlsafe(12), session, how, tool, tool_input, suggestions, agent, wait)
        self._open[ask.id] = ask
        return ask

    def waiting(self, ask_id) -> Ask | None:
        return self._open.get(ask_id) if isinstance(ask_id, str) else None

    def has_open(self, session: str) -> bool:
        return any(a.session == session for a in self._open.values())

    def _settle(self, ask: Ask, state: str, said=None) -> None:
        del self._open[ask.id]
        ask.state, ask.said, ask.answered_at = state, said, time.time()
        self._done.insert(0, ask)
        del self._done[KEEP_ANSWERED:]

    def close(self, ask: Ask, state: str) -> None:
        """The hook has gone, or hubd stopped waiting. If it was answered first, that stands."""
        if ask.id in self._open:
            self._settle(ask, state)

    def moved_on(self, session: str, how, tool, tool_input) -> None:
        """A tool ran, so a prompt for that same call was answered in the terminal. An ended turn has no
        prompts left, whatever they were. If this ever closes one too many, its prompt is still in the terminal."""
        tool_input = _shown(tool_input)
        for ask in sorted(self._open.values(), key=lambda a: a.made):
            if ask.session != session:
                continue
            if how == "Stop" or (ask.tool == tool and ask.same_call(tool_input)):
                ask.future.set_result(None)
                self._settle(ask, "terminal")
                if how != "Stop":
                    return

    def list(self) -> dict:
        today = time.strftime("%Y-%m-%d")
        done = [a for a in self._done if time.strftime("%Y-%m-%d", time.localtime(a.answered_at)) == today]
        return {"open": [a.view() for a in sorted(self._open.values(), key=lambda a: a.made)], "answered": [a.view() for a in done]}

    def answer(self, ask_id, verdict, reason=None, answers=None) -> dict:
        ask = self._open.get(ask_id) if isinstance(ask_id, str) else None
        if ask is None:
            raise AskError("that has already been answered, or isn't waiting any more")
        if verdict == "deny":
            if ask.kind != "permission":
                raise AskError("a question is answered, not denied")
            if reason is not None and not isinstance(reason, str):
                raise AskError("the reason has to be text")
            message = (reason or "").strip()[:MAX_REASON] or DENIED
            ask.future.set_result(ask.output("deny", message=message))
            self._settle(ask, "denied", message)
        elif verdict in ("allow", "always"):
            if ask.kind != "permission":
                raise AskError("a question is answered, not allowed")
            if ask.too_long:
                raise AskError("the card couldn't show all of it, so it can only be allowed in the terminal")
            if verdict == "always" and not ask.updates:
                raise AskError("Claude Code didn't offer that for this one")
            if ask.tool.startswith(TOOL_PREFIX):
                self._grants = [*self._grants, (ask.session, ask.tool.removeprefix(TOOL_PREFIX), _same(ask.input), time.time() + GRANT_LIFE)][-MAX_GRANTS:]
            ask.future.set_result(ask.output("allow", updates=ask.updates if verdict == "always" else None))
            self._settle(ask, "always" if verdict == "always" else "allowed", ask.always if verdict == "always" else None)
        elif verdict == "answer":
            if ask.kind != "question":
                raise AskError("only a question takes an answer")
            words = self._answers(ask, answers)
            ask.future.set_result(ask.output("allow", updated_input={**ask.input, "answers": words}))
            self._settle(ask, "answered", words)
        else:
            raise AskError("not an answer this knows")
        return ask.view()

    @staticmethod
    def _answers(ask: Ask, answers) -> dict:
        wanted = [q["question"] for q in _questions(ask.input)]
        if not isinstance(answers, dict) or set(answers) != set(wanted):
            raise AskError("every question needs its answer")
        words = {}
        for question, answer in answers.items():
            text = ", ".join(answer) if isinstance(answer, list) and all(isinstance(a, str) for a in answer) else answer
            if not (isinstance(text, str) and text.strip() and len(text) <= MAX_ANSWER):
                raise AskError("every question needs its answer")
            words[question] = text.strip()
        return words
