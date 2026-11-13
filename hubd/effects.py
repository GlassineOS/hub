# SPDX-License-Identifier: GPL-2.0-or-later
"""What a workflow move does to the running session (spec 012, FR-020 to FR-024, FR-031).

Machines (instances.py) keeps the state; this watches its moves (`Machines.on_move`) and applies them to the session,
for sessions whose workflow has more than one state. A one-state session never moves, and nothing here touches it.

- **Instructions** (FR-020): entering a state that has instructions puts them in the session's next turn, through
  `Agents.tell`, in a block marked as the hub's. They are the definition's words, never a transcript's.
- **Narrowing** (FR-022) is cheap and at once: what the new state doesn't grant goes from the session's tool token and from
  grant.json, which grant_hook.py reads before each tool use, and a GitHub token is made again with fewer capabilities.
- **Widening** (FR-023) is deliberate: Machines holds a move to a capability never held in the instance until the
  maintainer confirms it, on a `machine.widen` card in Needs you (FR-024). A move that adds anything, confirmed now or
  before, resumes the same conversation under a new launch with the new state's grant, once the session is at its prompt.
  A stopped session isn't started: its next resume takes the new grant.
- A conversation keeps its access and its checkout. A move that would change either fails back: a waiting one is
  declined, one that happened is rolled back, and the log says why.
- **Context on entry** (FR-021): `keep` does nothing; `compact` types `/compact <focus>` once the session is idle,
  through the queue typed messages wait in. `fresh` isn't done yet: it is logged and kept.

- **Approvals** (FR-025, FR-052): an exit that holds and whose `approve` asks someone first doesn't move on its own. The
  runner hands it here (`ask_approval`) and it becomes a `machine.approve` card in Needs you, one per session, state,
  version and exit; the maintainer's yes makes the move through the runner (`answer_approval`), after it checks the session
  is still where it was asked from and the exit's `requires` still hold. The levels owner and steward
  go to that session first, when it is running and can answer (managed.py, `route_approval`): an approval report, whose yes
  makes the move the same way. No repository maintainer session exists, so `maintainer` asks the maintainer, as does a level
  whose session isn't there, and the card says so. While either is up the runner tries nothing else for that instance, as
  for a pending confirm. A card ends when the session moves any other way. Cards of the same kind with a `type` (a report
  sent up to Needs you, a managed session's start that needs more than its owner holds) are managed.py's.

The status line of FR-025 isn't posted.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sqlite3

from . import instances, machine
from .agents import GITHUB_FOLDER, HUB_SENDER, AgentError, _full, _mode
from .decisions import APPROVE, WIDEN, DecisionError
from .instances import MachineError
from .machine_log import LogError
from .shells import ShellError

log = logging.getLogger("hubd.effects")

RELAUNCH_WAIT = 3600  # seconds a widening waits for the session to come back to its prompt before it fails back
POLL = 2  # seconds between looks at whether it has
LABEL = "[From the hub, not from the person or a session]"
FAILED_SIGNAL = "hub:relaunch"  # how a move that didn't take effect shows among the evaluations
FULL_MARK = "runs with your own rights: guarded, not limited"
# Who an `approve` level names, and who answers it for now: the chain above a session (FR-050) isn't there yet.
LEVELS = {"me": "you", "owner": "its owner", "maintainer": "the repository maintainer", "steward": "the Steward"}


def path_of(d: machine.Definition, sid: str) -> str:
    return " › ".join(reversed(machine.ancestors(d, sid)))


def _entered(d: machine.Definition, frm: str, to: str) -> list[str]:
    """The states a move into `to` enters, outermost first."""
    left = set(machine.ancestors(d, frm)) if frm in d.states else set()
    return [s for s in reversed(machine.ancestors(d, to)) if s not in left]


def instructions_of(d: machine.Definition, frm: str, to: str) -> str | None:
    texts = [d.states[s].instructions.strip() for s in _entered(d, frm, to) if d.states[s].instructions.strip()]
    if not texts:
        return None
    return f"{LABEL} Workflow: now in {path_of(d, to)}. " + "\n\n".join(texts)


def context_of(d: machine.Definition, frm: str, to: str) -> tuple[str, str]:
    """The context on entry of the nearest state the move enters that sets one, and its focus."""
    entered = set(_entered(d, frm, to))
    for s in machine.ancestors(d, to):
        if s in entered and d.states[s].context != "keep":
            return d.states[s].context, d.states[s].focus
    return "keep", ""


def sensitive_of(adds: dict, grant: machine.Grant) -> dict[str, str]:
    """FR-034's marks on what a confirm adds, and a full session's. A mark adds no rule."""
    marks = {c: machine.SENSITIVE[c] for c in adds.get("github", ()) if c in machine.SENSITIVE}
    marks |= {t: machine.SENSITIVE_HUB_TOOLS[t] for key in ("hub_tools", "asks_first") for t in adds.get(key, ())
              if t in machine.SENSITIVE_HUB_TOOLS}
    if grant.access == "full":
        marks["access"] = FULL_MARK
    return marks


class Effects:
    def __init__(self, agents, decisions=None, relaunch_wait: float = RELAUNCH_WAIT, poll: float = POLL):
        self.approve_move = None  # async (name, wait, who): the runner's move for an approved card (Runner.approved)
        self.agents = agents
        self.machines = agents.machines
        self.decisions = decisions
        self.relaunch_wait = relaunch_wait
        self.poll = poll
        self._tasks: set[asyncio.Task] = set()
        self._quiet: set[str] = set()  # sessions being moved back by this module: only their grant follows
        self._answering: str | None = None  # the card being answered, which the move it confirms mustn't end as stale
        self.managed = None  # managed.Managed: approvals at a level a session above can give, and its own cards
        self.machines.on_move(self.on_move)

    # --- the watcher ----------------------------------------------------------------
    def on_move(self, name: str, result: dict) -> None:
        action = self._action_of(name)
        if action is None or not self.agents.staged(action, name):
            return
        if result.get("needs_confirm"):
            self._ask(name, result)
            return
        self._end_cards(name, "you said no" if result.get("declined") else "the session moved before it was answered")
        if not result.get("moved"):
            return
        self._end_cards(name, "the session moved before it was answered", APPROVE)
        quiet = name in self._quiet
        try:
            problem = None if quiet else self.agents.launch_problem(name)
            if problem:
                self._fail_back(name, result, problem)
                return
            narrowed = self.agents.narrow_to_state(name)
        except Exception:  # noqa: BLE001: the move is saved, so the session can't keep the old grant: nothing, until a resume
            log.exception("%s: its grant couldn't follow its move, so its tools refuse everything", name)
            self.agents.lock_down(name)
            return
        if narrowed["github_changed"]:
            self._spawn(self._renew_token(name, narrowed["config"], narrowed["state"]))
        for child, got in narrowed.get("children", ()):  # the sessions it manages, narrowed to their cap again (FR-043)
            if got["github_changed"]:
                self._spawn(self._renew_token(child, got["config"], got["state"]))
        if quiet:
            return
        _record, inst = self.machines.load(name)
        d = inst.definition()
        words = instructions_of(d, result["from"], result["to"])
        context, focus = context_of(d, result["from"], result["to"])
        if context == "fresh":
            log.warning("%s: %s's context on entry is fresh, which isn't supported yet: kept", name, result["to"])
            context = "keep"
        state = narrowed["state"]
        record = self._record(name)
        # Its own launch takes what its own grant adds; what the sessions it manages add comes with their own launches (FR-023).
        relaunch = bool(result.get("own_widening", result.get("widening"))) or (_full(state) and record.get("permission_mode") != _mode(state))
        if relaunch:
            self._spawn(self._relaunch(name, result, words, focus if context == "compact" else None))
            return
        if words:
            self.agents.tell(name, words)
        if context == "compact":
            self._spawn(self._compact(name, focus))

    # --- widening ---------------------------------------------------------------------
    def _ask(self, name: str, result: dict) -> None:
        """A move waits for the maintainer: refused now if no launch could take it, else a card in Needs you."""
        _record, inst = self.machines.load(name)
        pending = inst.pending
        if pending is None or pending["id"] != result.get("pending"):
            return
        d_from, d_to = inst.definition(), instances._parse(inst.definitions[pending["to_version"]])
        grant = machine.effective(d_to, pending["to"])
        if problem := self.agents.launch_problem(name, grant):
            self._quiet.add(name)
            try:
                self.machines.confirm_move(name, pending["id"], "hub", accept=False)
            finally:
                self._quiet.discard(name)
            self._log_failure(name, pending["to"], pending["to_version"], problem)
            self.agents.tell(name, f"{LABEL} Workflow: the move to {path_of(d_to, pending['to'])} didn't happen: {problem}. "
                                   f"Still in {path_of(d_from, inst.state)}.")
            return
        if self.decisions is None:  # the confirm waits in the session's machine panel alone
            return
        self._end_cards(name, "another move is waiting instead")
        session_id = self._record(name).get("session_id")
        how = "the same conversation resumes under a new launch with the new state's grant, once it is at its prompt"
        scope = {"session": name, "session_id": session_id, "pending": pending["id"], "from": path_of(d_from, inst.state),
                 "to": path_of(d_to, pending["to"]), "by": pending["kind"], "change": result["change"], "adds": result["adds"],
                 "sensitive": sensitive_of(result["adds"], grant), "resumes": how}
        why = (f"The workflow moves {name} from {scope['from']} to {scope['to']}, which gives it what it hasn't held before. "
               f"If you confirm, {how}.")
        try:
            self.decisions.widen_request(scope, why)
        except (DecisionError, OSError):
            log.exception("%s: its confirm couldn't be put in Needs you; it waits in its machine panel", name)

    def answer(self, decision_id, accept: bool, who: str | None, words: str | None = None) -> dict:
        """The maintainer's answer on a `machine.widen` card: the move it names is confirmed or dropped."""
        record = self.decisions._get(decision_id)
        if record["kind"] != WIDEN:
            raise DecisionError("that isn't a workflow move's confirm")
        if self.decisions.current_state(record) != "requested":
            raise DecisionError("that isn't waiting for an answer any more")
        scope = record["scope"]
        if self.agents.session_id_of(scope["session"]) != scope["session_id"]:
            self.decisions.settle(decision_id, False, "the session it was for has gone")
            raise DecisionError("the session it was for has gone")
        self._answering = decision_id
        try:
            self.machines.confirm_move(scope["session"], scope["pending"], who, accept)
        except MachineError as e:
            self.decisions.settle(decision_id, False, f"not applied: {e}")
            raise DecisionError(str(e)) from None
        finally:
            self._answering = None
        if accept:
            return self.decisions.settle(decision_id, True, "confirmed: the session resumes with the new state's grant", words)
        return self.decisions.settle(decision_id, False, f"you said no: {words}" if words else "you said no")

    # --- approvals ---------------------------------------------------------------------
    def ask_approval(self, name: str, wait: dict) -> None:
        """The runner found an exit that holds and waits for an approval: a card, unless one for it is up already."""
        if self.managed is not None and wait.get("approve") in ("owner", "steward") and self.managed.route_approval(name, wait):
            return
        if self.decisions is None:
            return
        same = ("session_id", "state", "version", "exit")
        if any(all(r["scope"].get(k) == wait[k] for k in same) for r in self._exit_cards(name)):
            return
        _record, inst = self.machines.load(name)
        if (inst.state, inst.version) != (wait["state"], wait["version"]):
            return
        d = inst.definition()
        level = wait["approve"]
        to = path_of(d, wait["to"]) if wait["to"] in d.states else wait["to"]
        scope = {"session": name, "session_id": wait["session_id"], "state": wait["state"], "version": wait["version"],
                 "exit": wait["exit"], "to_state": wait["to"], "from": path_of(d, wait["state"]), "to": to,
                 "level": LEVELS.get(level, level), "approve": level, "checks": wait["checks"]}
        why = f"{name}'s workflow can move it from {scope['from']} to {to}: every requirement holds, and its workflow leaves this move to {scope['level']}."
        if level != "me":
            why += f" There is no {scope['level']} session that can answer, so it asks you."
        why += " If you approve, it moves, if it is still there and its requirements still hold."
        try:
            self.decisions.approve_request(scope, why)
        except (DecisionError, OSError):
            log.exception("%s: its approval couldn't be put in Needs you", name)

    def _exit_cards(self, name: str) -> list[dict]:
        return [r for r in self.decisions.open_approvals(name) if not r["scope"].get("type")]

    def approval_open(self, name: str, session_id, state: str, version: str) -> bool:
        if self.managed is not None and self.managed.approval_open(name, session_id, state, version):
            return True
        if self.decisions is None:
            return False
        return any(r["scope"].get("session_id") == session_id and r["scope"].get("state") == state and r["scope"].get("version") == version
                   for r in self._exit_cards(name))

    async def answer_approval(self, decision_id, accept: bool, who: str | None, words: str | None = None) -> dict:
        """The maintainer's answer on a `machine.approve` card: a yes makes the move it names, a no leaves the session where it is."""
        record = self.decisions._get(decision_id)
        if record["kind"] != APPROVE:
            raise DecisionError("that isn't a workflow approval")
        if self.decisions.current_state(record) != "requested":
            raise DecisionError("that isn't waiting for an answer any more")
        scope = record["scope"]
        if scope.get("type") and self.managed is not None:  # a report or a managed start: the chain's own
            return self.managed.answer_card(record, accept, who, words)
        if self.agents.session_id_of(scope["session"]) != scope["session_id"]:
            self.decisions.settle(decision_id, False, "the session it was for has gone")
            raise DecisionError("the session it was for has gone")
        if not accept:
            return self.decisions.settle(decision_id, False, f"you said no: {words}" if words else "you said no")
        if self.approve_move is None:
            raise DecisionError("the workflows don't move on their own here, so this can't be applied")
        self._answering = decision_id
        try:
            result = await self.approve_move(scope["session"], {k: scope[k] for k in ("session_id", "state", "version", "exit")}
                                             | {"to": scope["to_state"]}, who)
        except MachineError as e:
            self.decisions.settle(decision_id, False, f"not applied: {e}")
            raise DecisionError(str(e)) from None
        finally:
            self._answering = None
        if result.get("needs_confirm"):
            return self.decisions.settle(decision_id, True, "approved: the move now waits for your confirm of what it adds", words)
        if not result.get("moved"):
            self.decisions.settle(decision_id, False, "not applied: the machine didn't move")
            raise DecisionError("the machine didn't move")
        return self.decisions.settle(decision_id, True, "approved: the session moved", words)

    async def _relaunch(self, name: str, result: dict, words: str | None, focus: str | None) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.relaunch_wait
        while True:
            state = (await self.agents.session_state(name))["state"]
            if state in ("Stopped", "Not started"):  # not started for this: its next resume has the new grant
                if words:
                    self.agents.tell(name, words)
                return
            if state == "Idle":
                break
            if loop.time() > deadline:
                self._fail_back(name, result, "it didn't come back to its prompt in time")
                return
            await asyncio.sleep(self.poll)
        try:
            _record, inst = self.machines.load(name)
        except MachineError:
            return
        if inst.state != result["to"]:  # moved again meanwhile: that move's effects apply
            return
        try:
            await self.agents.resume(name, relaunch=True)
        except AgentError as e:
            self._fail_back(name, result, str(e))
            return
        log.info("%s relaunched in %s", name, result["to"])
        if words:
            self.agents.tell(name, words)
        if focus is not None:
            await self._compact(name, focus)

    def _fail_back(self, name: str, result: dict, why: str) -> None:
        """A move that happened and can't take effect: back to where it was, logged, and the session told."""
        log.warning("%s: the move to %s didn't take effect: %s", name, result["to"], why)
        try:
            _record, inst = self.machines.load(name)
            d_to = inst.definition()
            if inst.state == result["to"]:
                self._quiet.add(name)
                try:
                    if result.get("by") == "rollback":  # its trail entry went with it: back by a move, not another roll-back
                        self.machines.move(name, result["from"], "hand", who="hub")
                    elif inst.trail:
                        self.machines.rollback(name, "hub")
                finally:
                    self._quiet.discard(name)
            _record, inst = self.machines.load(name)
        except MachineError:
            log.exception("%s: couldn't move it back", name)
            self.agents.lock_down(name)
            return
        self._log_failure(name, result["to"], result["version"], why)
        self.agents.tell(name, f"{LABEL} Workflow: the move to {path_of(d_to, result['to'])} didn't take effect: {why}. "
                               f"Still in {path_of(inst.definition(), inst.state)}.")

    async def _renew_token(self, name: str, config: dict, state: dict) -> None:
        """The GitHub token again, with the capabilities left. If that fails the old, wider one goes: none rather than too much."""
        directory = self.agents.sessions / name
        try:
            await self.agents._github_token(directory, config, state)
        except Exception:  # noqa: BLE001: fails closed
            log.exception("%s: its narrowed GitHub token couldn't be made, so it has none until a resume", name)
            shutil.rmtree(directory / GITHUB_FOLDER, ignore_errors=True)

    # --- context ------------------------------------------------------------------------
    async def _compact(self, name: str, focus: str) -> None:
        text = " ".join(f"/compact {focus}".split())
        try:
            await self.agents._send(name, text, by=HUB_SENDER)
        except (AgentError, ShellError, OSError) as e:
            log.warning("%s: its compaction wasn't queued: %s", name, e)

    # --- helpers ------------------------------------------------------------------------
    def _end_cards(self, name: str, why: str, kind: str = WIDEN) -> None:
        if self.decisions is None:
            return
        for record in self.decisions.open_widenings(name, kind):
            if record["scope"].get("type") == "report":  # a report up stays until it is answered, wherever the session moves
                continue
            if record["id"] != self._answering:
                self.decisions.settle(record["id"], False, why)

    def _log_failure(self, name: str, state: str, version: str, why: str) -> None:
        try:
            session_id = self._record(name).get("session_id")
            if session_id:
                self.machines.log.evaluation(session_id, name, FAILED_SIGNAL, state, version,
                                             checks=[{"check": "the session can run under the new grant", "value": why, "holds": False}],
                                             failed=True)
        except (sqlite3.Error, LogError, OSError):
            log.exception("%s: its failed move wasn't logged", name)

    def _record(self, name: str) -> dict:
        try:
            return json.loads((self.agents.sessions / name / "session.json").read_text())
        except (OSError, ValueError):
            return {}

    def _action_of(self, name: str) -> dict | None:
        config = self._record(name).get("config") or {}
        return self.agents.library.actions.get(config.get("action"))

    def _spawn(self, coroutine) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            log.warning("no event loop to run a move's effect on")
            coroutine.close()
            return
        task = loop.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._done)

    def _done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.error("a move's effect failed", exc_info=task.exception())

    async def drain(self) -> None:
        """Until every effect under way has finished: for a test, or a clean stop."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)


__all__ = ["Effects", "instructions_of", "context_of", "sensitive_of", "path_of"]
