# SPDX-License-Identifier: GPL-2.0-or-later
"""Signals, routing and evaluation: what makes a workflow instance move on its own (spec 012, FR-006, FR-007,
FR-013 to FR-015, FR-017, FR-018).

A signal is a session event (its hook: `turn.end`, `session.end`, `tool.after`, `compact.before`), a change feed event
(`feed:<kind>.<what>`, for the sessions that cover the item or hold its pull request) or a hub event (`hub:decision`,
`hub:managed.return`, `hub:managed.end`). Routing uses no model: a signal reaches an instance only when its current state
has an exit, its own or a parent's, that moves on its own and names that signal in `on`. A session with no such exit
costs nothing, not even a look at its transcript.

Evaluations are debounced per instance (signals within the window share one pass) and run one at a time per instance;
a signal that arrives during a pass gets one more pass after it. A pass tries the matching exits in order:

- `facts` and `counter` exits hold when every `requires` holds;
- `judge` exits are put to the judge once per pass, after the session's rolling summary has taken the last turn, and
  hold only when the judge picks that exit and every `requires` holds as well;
- `hand` exits and `move = "on-request"` exits are never tried here;
- the first exit that holds ends the pass. If its `approve` asks for anyone, nothing moves, the evaluation says what
  it waits for, and `on_blocked` hears of it (effects.py puts it to the maintainer as a `machine.approve` card, whose yes
  comes back through `approved`); otherwise the instance moves by the machine.

An exit with `move = "on-request"` is tried only when the session asks for it (`request`, the `request_move` tool): the
request stands in for the judge, and the exit's `requires` and `approve` are checked as above.

A fact the hub can't tell is missing from the facts, so a requirement on it doesn't hold either way. Every pass that tried
an exit is logged, with each check and the value it saw. This module only decides: what a move does to the running
session is for whoever listens to the moves.

Standard library only, as hubd is.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import sqlite3
from pathlib import Path

from . import judge as judgelib
from . import machine, summary
from .instances import MachineError, Machines
from .machine_log import LogError

log = logging.getLogger("hubd.machinerun")

DEBOUNCE = 2.0  # seconds a pass waits for more signals after the first
HOOK_SIGNALS = {"Stop": "turn.end", "SessionEnd": "session.end", "PostToolUse": "tool.after", "PreCompact": "compact.before"}
SESSION_SIGNALS = tuple(HOOK_SIGNALS.values())
HUB_SIGNALS = ("hub:decision", "hub:managed.return", "hub:managed.end")

# The change feed's words, in the words `requires` uses. A value not here (no checks at all, say) is not a fact.
CHECKS = {"passing": "pass", "failing": "fail", "pending": "pending"}
REVIEWS = {"APPROVED": "approved", "CHANGES_REQUESTED": "changes_requested", "REVIEW_REQUIRED": "none"}
PR_STATES = ("OPEN", "CLOSED", "MERGED")


WHEN_SIGNALS = ("turn.end",)  # what a `manages` entry that starts on its own once its `when` holds is tried on


def wanted(d: machine.Definition, among=SESSION_SIGNALS) -> set[str]:
    """The signals among `among` that an exit of the definition names, or that a `manages` entry with a `when` is tried on:
    what a session on it needs to send."""
    out = {s for st in d.states.values() for e in st.exits for s in e.on if s in among}
    if any(m.start == "auto" and m.when.strip() for st in d.states.values() for m in st.manages):
        out |= {s for s in WHEN_SIGNALS if s in among}
    return out


def tried(d: machine.Definition, state_id: str, signals) -> list[tuple[int, machine.Exit]]:
    """The exits a pass tries on these signals, each with its place in `machine.exits_of`, in order: those that move on
    their own and name one of the signals."""
    signals = set(signals)
    return [(i, e) for i, e in enumerate(machine.exits_of(d, state_id))
            if e.decided_by != "hand" and e.move == "auto" and signals & set(e.on)]


def check(expr: str, facts: dict) -> dict:
    """One `requires` entry against the facts: each term with the value it saw, and whether the entry holds."""
    req = machine.parse_requires(expr)
    terms = [{"fact": t.name, "op": t.op, "want": t.value, "value": facts.get(t.name), "holds": t.holds(facts)} for t in req.terms]
    return {"requires": expr, "terms": terms, "holds": req.holds(facts)}


# ---- facts ----

def pr_facts(state: str | None, seen: dict, own_branch: bool) -> dict:
    """A pull request's facts from its state (as last looked up or fed) and what the feed saw of it since its head."""
    out = {}
    if state in PR_STATES:
        out["pr.open"], out["pr.merged"] = state == "OPEN", state == "MERGED"
    if seen.get("checks") in CHECKS:
        out["pr.checks"] = CHECKS[seen["checks"]]
    if seen.get("review") in REVIEWS:
        out["pr.review"] = REVIEWS[seen["review"]]
    if seen:  # the feed has seen it: whether a review came since its newest head, so a push since a review shows
        out["pr.reviewed"] = seen.get("review") in REVIEWS
    if own_branch:  # found by the session's own branch, so that branch is on GitHub
        out["branch.pushed"] = True
    return out


class HubFacts:
    """The facts hubd has without asking GitHub: the pull requests the session view last looked up, the change feed's
    events for them, and what the session was started on. Nothing here makes a call."""

    def __init__(self, agents, feed):
        self.agents = agents
        self.feed = feed

    def __call__(self, name: str, record: dict) -> dict:
        out = {"issue.linked": True} if record.get("object") == "issue" else {}
        out.update(self._design(name))
        prs = self.agents.known_prs(name)
        if prs is None:  # never looked up: whether there is one is unknown
            return out
        if not prs:
            return {**out, "pr.open": False, "pr.merged": False}
        pr = min(prs, key=lambda p: p.get("state") != "OPEN")
        seen = self._seen(pr["repo"], pr["number"])
        return {**out, **pr_facts(seen.get("state") or pr.get("state"), seen, record.get("object") != "pr")}

    def _design(self, name: str) -> dict:
        """design.accepted (012 FR-073): a design session this one manages had its pull request merged, as the feed (or the
        last lookup) says. False while its pull requests are there and none is merged; unknown before it has one."""
        design_prs = getattr(self.agents, "design_prs", None)
        prs = design_prs(name) if design_prs else []
        if not prs:
            return {}
        states = [self._seen(p["repo"], p["number"]).get("state") or p.get("state") for p in prs]
        return {"design.accepted": any(s == "MERGED" for s in states)}

    def _seen(self, repo: str, number: int) -> dict:
        if self.feed is None:
            return {}
        try:
            return self.feed.latest("pr", repo, number)
        except sqlite3.Error:
            log.exception("the change feed can't be read")
            return {}


# ---- the runner ----

class Runner:
    """Routes signals to instances and evaluates them. `facts(name, record)` gives the facts beyond the counters,
    `judges()` the judge table (it may raise judge.ConfigError), `turn(name, record)` the turn that just ended,
    `items(name, record)` the (repository, number) pairs a session is on, `names()` the sessions. `sleep` and the
    machines' clock are injectable, so tests don't wait."""

    def __init__(self, machines: Machines, *, facts=None, judges=None, turn=None, items=None, names=None, refresh=None,
                 debounce: float = DEBOUNCE, sleep=asyncio.sleep):
        self.machines = machines
        self._facts = facts or (lambda _name, _record: {})
        self._judges = judges or (lambda: {})
        self._turn = turn or (lambda _name, _record: "")
        self._items = items or (lambda _name, _record: ())
        self._names = names or (lambda: ())
        self._refresh = refresh  # async (name): look up what facts need a look first (its pull requests), if it's due
        self.on_blocked = None   # (name, wait) when an exit holds and its `approve` asks someone first
        self.approval_open = None  # (name, session_id, state, version): whether its card for that is still up
        # The managed sessions (managed.py): `waiting_starts(name, inst)` the entries whose `when` waits for a signal, tried by
        # `try_starts(name, record, inst, signals)` before the exits; `more_facts(name, record)` what they returned and reports.
        self.waiting_starts = None
        self.try_starts = None
        self.more_facts = None
        self.on_head = None  # (name, sha): a pull request it covers has a new head, before the signal is routed (managed.py)
        self.debounce = debounce
        self._sleep = sleep
        self._waiting: dict[str, list[str]] = {}       # signals that came since the last pass began
        self._received: dict[str, float] = {}          # when the first of them came, for the time to a move (SC-003)
        self._tasks: dict[str, asyncio.Task] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._folded: dict[tuple[str, str], str] = {}  # (name, conversation) -> the hash of the turn last folded

    # --- signals ----------------------------------------------------------------------
    def signal(self, name: str, session: str | None = None, payload: dict | None = None) -> list[str]:
        """A signal for one session (session and hub signals) or for the item a payload names (feed signals: repo and
        number). The sessions it was routed to. Never raises: a signal that reaches nothing is no fault."""
        if name not in machine.SIGNALS:
            return []
        if name.startswith("feed:"):
            index = self.index()
            item = _item(payload)
            return self._route(name, sorted(index.get(item, ()))) if item else []
        return self._route(name, [session] if isinstance(session, str) and session else [])

    def hook(self, session: str, how) -> list[str]:
        """A session's hook said this event happened. Only the events in HOOK_SIGNALS are signals."""
        return self.signal(HOOK_SIGNALS[how], session) if isinstance(how, str) and how in HOOK_SIGNALS else []

    def feed(self, rows) -> list[str]:
        """Changes the feed has just stored, each a row as Feed.changes gives it. One index for them all."""
        index, routed = None, []
        for row in rows:
            signal = f"feed:{row.get('kind')}.{row.get('what')}"
            item = _item(row)
            if signal not in machine.SIGNALS or item is None:
                continue
            index = self.index() if index is None else index
            if row.get("what") == "head" and self.on_head is not None and isinstance(row.get("new_head"), str) and row["new_head"]:
                for name in sorted(index.get(item, ())):
                    try:
                        self.on_head(name, row["new_head"])
                    except Exception:  # noqa: BLE001 — the signal still goes on
                        log.exception("%s: its new head couldn't be noted", name)
            routed += self._route(signal, sorted(index.get(item, ())))
        return list(dict.fromkeys(routed))

    def index(self) -> dict[tuple[str, int], set[str]]:
        """(repository in lower case, number) -> the sessions on that item or holding that pull request."""
        out: dict[tuple[str, int], set[str]] = {}
        for name in self._names():
            try:
                record, _inst = self.machines.load(name)
                for repo, number in self._items(name, record):
                    out.setdefault((str(repo).lower(), number), set()).add(name)
            except (MachineError, OSError, KeyError, TypeError, ValueError):
                continue
        return out

    def _route(self, signal: str, names: list[str]) -> list[str]:
        out = []
        for name in names:
            if self._listens(name, signal) and self._schedule(name, signal):
                out.append(name)
        return out

    def _listens(self, name: str, signal: str) -> bool:
        try:
            record, inst = self.machines.load(name)
            if inst.paused or inst.pending:
                return False
            if signal in WHEN_SIGNALS and self._starts_wait(name, inst):
                return True
            return not self._approval_waits(name, record, inst) and bool(tried(inst.definition(), inst.state, [signal]))
        except (MachineError, OSError):
            return False

    def _starts_wait(self, name: str, inst) -> bool:
        if self.waiting_starts is None:
            return False
        try:
            return bool(self.waiting_starts(name, inst))
        except Exception:  # noqa: BLE001
            log.exception("%s: its managed sessions couldn't be looked at", name)
            return False

    def _approval_waits(self, name: str, record: dict, inst) -> bool:
        """An approval card is up for where the instance is: like a pending confirm, nothing else is tried until it's answered."""
        if self.approval_open is None:
            return False
        try:
            return bool(self.approval_open(name, record.get("session_id"), inst.state, inst.version))
        except Exception:  # noqa: BLE001 — unsure means evaluate: the card is deduplicated anyway
            log.exception("%s: its approval card couldn't be looked at", name)
            return False

    def _schedule(self, name: str, signal: str) -> bool:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            log.warning("%s: %s came with no event loop to evaluate it", name, signal)
            return False
        waiting = self._waiting.setdefault(name, [])
        if not waiting:
            self._received[name] = self.machines.clock()
        if signal not in waiting:
            waiting.append(signal)
        if name not in self._tasks:
            self._tasks[name] = loop.create_task(self._run(name))
        return True

    async def _run(self, name: str) -> None:
        """A fixed window from the first signal, so a stream of them can't put a pass off for good."""
        try:
            while self._waiting.get(name):
                await self._sleep(self.debounce)
                signals = self._waiting.pop(name, [])
                received = self._received.pop(name, None)
                if signals:
                    try:
                        await self.evaluate(name, signals, received)
                    except Exception:  # noqa: BLE001 — one instance's fault mustn't stop the next signal
                        log.exception("%s: the evaluation broke", name)
        finally:
            self._tasks.pop(name, None)

    async def idle(self) -> None:
        """Until no pass is waiting or running."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)

    # --- evaluation -------------------------------------------------------------------
    async def evaluate(self, name: str, signals, received: float | None = None) -> dict:
        """One pass over the instance's exits that name one of these signals. At most one per instance at a time.
        `received`: when the first signal came (the machines' clock), so a move logs how long it took."""
        lock = self._locks.setdefault(name, asyncio.Lock())
        async with lock:
            return await self._evaluate(name, list(dict.fromkeys(signals)), received)

    async def _evaluate(self, name: str, signals: list[str], received: float | None = None) -> dict:
        bank = getattr(self.machines, "bank", None)
        if bank is not None:  # what it used since the last look counts in the state it is in (FR-090)
            bank(name)
        try:
            record, inst = self.machines.load(name)
        except (MachineError, OSError) as e:
            return {"skipped": str(e)}
        if inst.paused:
            return {"skipped": "paused"}
        if inst.pending:  # another proposal would replace the one waiting for the maintainer's confirm
            return {"skipped": "a move waits for a confirm"}
        if self.try_starts is not None and set(signals) & set(WHEN_SIGNALS) and self._starts_wait(name, inst):
            try:
                await self.try_starts(name, record, inst, signals)
            except Exception:  # noqa: BLE001 — a start that fails leaves the exits to be tried
                log.exception("%s: its managed sessions' starts broke", name)
            try:
                record, inst = self.machines.load(name)
            except (MachineError, OSError) as e:
                return {"skipped": str(e)}
            if inst.paused or inst.pending:
                return {"skipped": "the machine changed while its managed sessions started"}
        if self._approval_waits(name, record, inst):
            return {"skipped": "a move waits for an approval"}
        d, state, version = inst.definition(), inst.state, inst.version
        candidates = tried(d, state, signals)
        if not candidates:
            return {"skipped": "no exit names the signal"}
        facts = await self._facts_now(name, record, inst)
        verdict, fold, failed, chosen, rows = None, None, None, None, []
        for i, e in candidates:
            picked = True
            if e.decided_by == "judge":
                if verdict is None:
                    verdict, fold = await self._judge(name, record, d, state, facts, [c for c in candidates if c[1].decided_by == "judge"])
                    if verdict.failed:  # no move on a failed judgement, even by a later exit: the order would be broken
                        failed = verdict.failed
                        break
                picked = verdict.exit == i
            reqs = [check(expr, facts) for expr in e.requires]
            holds = picked and all(r["holds"] for r in reqs)
            rows.append({"exit": i, "to": e.to, "decided_by": e.decided_by, **({"picked": picked} if e.decided_by == "judge" else {}),
                         "checks": reqs, "holds": holds})
            if holds:
                chosen = (i, e)
                break
        blocked, result = None, None
        if chosen and not failed:
            exit_ = chosen[1]
            if exit_.approve != "none":
                blocked = f"approve {exit_.approve}"
                self._ask(name, record, state, version, chosen[0], exit_, rows[-1]["checks"])
            else:
                result = self._move(name, state, version, exit_)
        latency = round((self.machines.clock() - received) * 1000) if received is not None and result and result.get("moved") else None
        self._log(record, name, signals, state, version, d, verdict, fold, failed, chosen, rows, blocked, result, latency)
        return {"exit": chosen[0] if chosen else None, "failed": failed, "blocked": blocked, "move": result, "checks": rows,
                "latency_ms": latency}

    async def _facts_now(self, name: str, record: dict, inst) -> dict:
        if self._refresh is not None:
            try:
                await self._refresh(name)
            except Exception:  # noqa: BLE001 — a look that fails leaves what was known, which may be nothing
                log.exception("%s: its pull requests couldn't be looked up", name)
        return {**inst.facts(self.machines.clock()), **self._facts_of(name, record)}

    def _ask(self, name, record, state, version, index, exit_, checks) -> None:
        if self.on_blocked is None:
            return
        try:
            self.on_blocked(name, {"session_id": record.get("session_id"), "state": state, "version": version, "exit": index,
                                   "to": exit_.to, "approve": exit_.approve, "checks": checks})
        except Exception:  # noqa: BLE001 — the evaluation stands and is logged; the card is tried again on the next signal
            log.exception("%s: its approval couldn't be asked for", name)

    # --- moves the session or the maintainer asks for -----------------------------------
    async def request(self, name: str, session_id, to, signal: str = "request") -> dict:
        """The session asks to take one of its state's `move = "on-request"` exits to `to`. Only its own conversation's
        token gets here (the caller checks it); the request is the proposal, and `requires` and `approve` decide."""
        lock = self._locks.setdefault(name, asyncio.Lock())
        async with lock:
            try:
                record, inst = self.machines.load(name)
            except (MachineError, OSError) as e:
                return {"moved": False, "why": str(e)}
            if not isinstance(session_id, str) or record.get("session_id") != session_id:
                return {"moved": False, "why": "that isn't this session's conversation"}
            d, state, version = inst.definition(), inst.state, inst.version
            here = " › ".join(reversed(machine.ancestors(d, state)))
            if inst.paused:
                return {"moved": False, "why": f"the machine is paused in {here}"}
            if inst.pending:
                return {"moved": False, "why": "a move already waits for the maintainer's confirm"}
            offered = [(i, e) for i, e in enumerate(machine.exits_of(d, state)) if e.move == "on-request" and e.decided_by != "hand"]
            if not isinstance(to, str) or not any(e.to == to for _i, e in offered):
                can = sorted({e.to for _i, e in offered})
                return {"moved": False, "why": f"no exit of {here} to {str(to)[:64]!r} moves on request"
                        + (f"; those that do go to {', '.join(can)}" if can else "; none of its exits does")}
            facts = await self._facts_now(name, record, inst)
            rows, chosen = [], None
            for i, e in offered:
                if e.to != to:
                    continue
                reqs = [check(expr, facts) for expr in e.requires]
                holds = all(r["holds"] for r in reqs)
                rows.append({"exit": i, "to": e.to, "decided_by": e.decided_by, "checks": reqs, "holds": holds})
                if holds:
                    chosen = (i, e)
                    break
            blocked, result = None, None
            if chosen and chosen[1].approve != "none":
                blocked = f"approve {chosen[1].approve}"
                self._ask(name, record, state, version, chosen[0], chosen[1], rows[-1]["checks"])
            elif chosen:
                result = self._move(name, state, version, chosen[1])
            self._log(record, name, [signal], state, version, d, None, None, None, chosen, rows, blocked, result)
        if result is not None:
            if result.get("needs_confirm"):
                return {**result, "why": "the move waits for the maintainer's confirm: the new state gives what you haven't held"}
            return {**result, "why": None} if result.get("moved") else {**result, "moved": False, "why": "the machine changed meanwhile"}
        if blocked:
            return {"moved": False, "waits": blocked, "why": f"the exit to {to} holds and waits for the maintainer's approval"}
        failed = [t["fact"] for r in rows for c in r["checks"] if not c["holds"] for t in c["terms"]]
        return {"moved": False, "why": f"its requirements don't hold: {', '.join(dict.fromkeys(failed))}", "checks": rows}

    async def approved(self, name: str, wait: dict, who: str | None) -> dict:
        """The maintainer approved the move a `machine.approve` card asked about: it happens if the session is still where it
        was asked from and the exit's `requires` still hold. The judge isn't asked again: the approval is the decision."""
        lock = self._locks.setdefault(name, asyncio.Lock())
        async with lock:
            record, inst = self.machines.load(name)
            if record.get("session_id") != wait.get("session_id"):
                raise MachineError("the session it was for has gone")
            if (inst.state, inst.version) != (wait.get("state"), wait.get("version")):
                raise MachineError("the session has moved since that was asked")
            d = inst.definition()
            exits = machine.exits_of(d, inst.state)
            index = wait.get("exit")
            if not isinstance(index, int) or not 0 <= index < len(exits) or exits[index].to != wait.get("to"):
                raise MachineError("that exit isn't there any more")
            exit_ = exits[index]
            facts = await self._facts_now(name, record, inst)
            reqs = [check(expr, facts) for expr in exit_.requires]
            row = {"exit": index, "to": exit_.to, "decided_by": exit_.decided_by, "checks": reqs, "holds": all(r["holds"] for r in reqs)}
            result = self._move(name, inst.state, inst.version, exit_, who) if row["holds"] else None
            self._log(record, name, ["hub:approved"], inst.state, inst.version, d, None, None, None, (index, exit_), [row], None, result)
        if result is None:
            failed = [t["fact"] for c in reqs if not c["holds"] for t in c["terms"]]
            raise MachineError(f"its requirements don't hold any more: {', '.join(dict.fromkeys(failed))}")
        if result.get("stale"):  # a move by hand while its facts were looked up
            raise MachineError("the session has moved since that was asked")
        return result

    def _facts_of(self, name: str, record: dict) -> dict:
        out = {}
        for source in (self._facts, self.more_facts):
            if source is None:
                continue
            try:
                out.update(source(name, record))
            except Exception:  # noqa: BLE001 — a fact that can't be read is unknown, never a crash
                log.exception("%s: the facts can't be read", name)
        return out

    async def facts_now(self, name: str, record: dict, inst) -> dict:
        """The facts an evaluation would see now, for a managed session's `when` (managed.py)."""
        return await self._facts_now(name, record, inst)

    async def judge_when(self, name: str, record: dict, inst, facts: dict, label: str, question: str):
        """Puts one plain-language question to the judge, as the one exit of the state it is in: whether a managed session's
        `when` holds. The verdict, with the summary fold, as an exit's judgement has them."""
        d = inst.definition()
        return await self._judge(name, record, d, inst.state, facts, [(0, machine.Exit(to=label, decided_by="judge", when=question))])

    async def _judge(self, name, record, d, state, facts, offered):
        try:
            table = self._judges()
        except judgelib.ConfigError as e:
            return judgelib.Verdict(None, "", 0.0, "none", 0, None, f"the judges can't be read: {e}"[:judgelib.MAX_FAULT]), None
        if not table:
            return judgelib.Verdict(None, "", 0.0, "none", 0, None, "no judge is set up"), None
        judge, _note = judgelib.pick(table, d.judge)
        directory = self.machines.sessions / name
        turn = self._turn_of(name, record)
        fold = None
        key, digest = (name, str(record.get("session_id"))), hashlib.sha256(turn.encode()).hexdigest()
        if turn and self._folded.get(key) != digest:
            fold = await summary.update(directory, turn, judge)
            self._folded[key] = digest
        request = judgelib.JudgeRequest(d.name, state, tuple((i, e.to, e.when) for i, e in offered), dict(facts),
                                        summary.read(directory), turn)
        return await judgelib.decide(table, d.judge, request), fold

    def _turn_of(self, name: str, record: dict) -> str:
        try:
            turn = self._turn(name, record)
        except Exception:  # noqa: BLE001
            log.exception("%s: the last turn can't be read", name)
            return ""
        return turn if isinstance(turn, str) else ""

    def _move(self, name: str, state: str, version: str, exit_: machine.Exit, who: str | None = None) -> dict:
        """Only if nothing moved the instance while the judge thought or the facts were looked up. No await between the
        look and the move. `who` agreed to it, for an approved exit."""
        try:
            _record, inst = self.machines.load(name)
            if (inst.state, inst.version) != (state, version) or inst.paused or inst.pending:
                return {"moved": False, "stale": "the machine changed during the evaluation"}
            return self.machines.move(name, exit_.to, by="machine", enter=exit_.enter, who=who, why=reason_of(exit_))
        except (MachineError, OSError) as e:
            return {"moved": False, "error": str(e)}

    def _log(self, record, name, signals, state, version, d, verdict, fold, failed, chosen, rows, blocked, result, latency=None) -> None:
        proposal = None
        exits = machine.exits_of(d, state)
        if verdict is not None and verdict.exit is not None and 0 <= verdict.exit < len(exits):
            proposal = f"exit {verdict.exit} to {exits[verdict.exit].to}"
        elif chosen:
            proposal = f"exit {chosen[0]} to {chosen[1].to}"
        checks = {"exits": rows}
        if blocked:
            checks["blocked"] = blocked
        if result is not None:
            checks["move"] = {k: result[k] for k in ("moved", "to", "needs_confirm", "stale", "error") if k in result}
            if result.get("paused") and not result.get("moved"):
                checks["move"]["paused"] = True
        if latency is not None:  # from the first signal of the pass to the move logged (SC-003)
            checks["latency_ms"] = max(0, latency)
        if verdict is not None and verdict.note:
            checks["note"] = verdict.note
        if fold is not None:
            checks["summary"] = {"failed": fold.failed, "ms": fold.ms}
        costs = [c for c in ((verdict.cost if verdict else None), (fold.cost if fold else None)) if c is not None]
        try:
            self.machines.log.evaluation(
                str(record.get("session_id") or name), name, ", ".join(signals), state, version, proposal=proposal,
                evidence=verdict.evidence if verdict and verdict.evidence else None, checks=checks,
                judge=verdict.judge if verdict else None, ms=(verdict.ms + (fold.ms if fold else 0)) if verdict else None,
                cost=sum(costs) if costs else None, failed=bool(failed))
        except (sqlite3.Error, LogError, OSError):
            log.exception("%s: the evaluation wasn't logged", name)


def reason_of(exit_: machine.Exit) -> str:
    """Why an exit moved, in the definition's own words: a judge's question, else the facts it requires. Never the judge's
    evidence, which can quote a transcript."""
    if exit_.decided_by == "judge" and exit_.when.strip():
        return " ".join(exit_.when.split())
    return ", ".join(exit_.requires) or {"counter": "a counter", "facts": "its facts"}.get(exit_.decided_by, exit_.decided_by)


def _item(payload) -> tuple[str, int] | None:
    if not isinstance(payload, dict):
        return None
    repo, number = payload.get("repo"), payload.get("number")
    if not isinstance(repo, str) or not repo or not isinstance(number, int) or isinstance(number, bool):
        return None
    return repo.lower(), number


def for_hub(agents, feed, judges) -> Runner:
    """The runner over hubd's own sessions, facts and transcripts. `judges()` gives the judge table as configured now."""
    from .agents import covers_of

    def items(name, record):
        found = [(c["repo"], c["number"]) for c in covers_of(record.get("config", {}))]
        # what it carries, and its design sessions' pull requests, whose merge is its design.accepted
        return found + [(p["repo"], p["number"]) for p in [*(agents.known_prs(name) or ()), *agents.design_prs(name)]]

    def turn(_name, record):
        session_id = record.get("session_id")
        return summary.last_turn(agents._transcript(session_id)) if isinstance(session_id, str) else ""

    def names():
        root = Path(agents.sessions)
        return [p.name for p in root.iterdir() if (p / "session.json").exists()] if root.is_dir() else []

    async def refresh(name):  # at most once a minute a session, so a pull request opened since its last look is found
        await agents.refresh_prs([name])

    return Runner(agents.machines, facts=HubFacts(agents, feed), judges=judges, turn=turn, items=items, names=names, refresh=refresh)
