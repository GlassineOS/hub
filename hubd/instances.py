# SPDX-License-Identifier: GPL-2.0-or-later
"""Workflow instances: the machine a session holds (spec 012, FR-011, FR-024, FR-026).

An instance is kept as `machine.json` in the session's folder, beside `session.json`, and goes into the session's
history record when the folder goes, so it survives a stop, a resume and a resume under a new launch. It holds the
text of the definition it runs on (its version is a hash of that text), the current state (always a leaf), where it last
was under each parent (for `enter = "history"`), the counters, the moves it can roll back, and the high-water grant:
every capability the instance has held. A move whose new state's grant holds a capability outside the high-water
grant waits for the maintainer's confirm; one back into what was held already doesn't ask again.

Rounds: every move into a state counts a round for that state and for each of its parents, so a parent's counter
bounds a cycle among its children, as `machine.check` assumes. Creating an instance counts the initial state's first
round. A roll-back undoes the move's place in the trail but not its counters: rounds, time and tokens spent stay spent.
Time counts only while the session runs and the machine isn't paused: it is banked when the session ends (the time its
terminal marked), when hubd finds it stopped, and on a pause, and the clock starts again on a resume or an unpause.

Only state lives here. What a move does to the running session (instructions, context, the grant in force) is applied
by whoever watches the moves (`Machines.on_move`, effects.py).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import machine
from .machine import Definition, DefinitionError, Grant
from .machine_log import Log, LogError

log = logging.getLogger("hubd.instances")

SCHEMA = 1
FILE = "machine.json"
MAX_TRAIL = 50                  # moves that can be rolled back, newest last
ENDED = "ended"                 # the marker a session's terminal leaves when Claude ends (agents.ENDED_FILE)
OPS = ("machine.get", "machine.history", "machine.move", "machine.confirm", "machine.rollback", "machine.pause")

_LISTS = ("tools", "hub_tools", "asks_first", "github")
_LEVELS = {"access": machine.ACCESS, "permission_mode": machine.PERMISSION_MODES, "all_repos": (False, True)}


class MachineError(Exception):
    """A request about an instance that can't be done; the message goes back to the caller."""


def version_of(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def definition_for(action: dict) -> str:
    """The definition text a session of this action runs on: its workflow's file as the library loaded it. The version is
    the hash of that text, so it changes only when the file does."""
    return action["definition"]


_parsed: dict[str, Definition] = {}


def _parse(text: str) -> Definition:
    key = version_of(text)
    if key not in _parsed:
        try:
            d = machine.parse(text)
        except DefinitionError as e:
            raise MachineError(f"the definition has problems: {e}") from None
        if problems := [f for f in machine.check(d) if f.kind == "problem"]:
            raise MachineError("the definition has problems: " + "; ".join(f"{p.where}: {p.text}" for p in problems[:5]))
        if len(_parsed) > 256:
            _parsed.clear()
        _parsed[key] = d
    return _parsed[key]


def _is_leaf(d: Definition, sid: str) -> bool:
    return sid in d.states and d.states[sid].initial is None


def _enter(d: Definition, sid: str, history: dict, enter: str) -> str:
    """The leaf a move into `sid` lands on: the state itself, or a parent's first state down to a leaf, or for
    `history` the leaf it was last in under that parent, if the definition still has it there."""
    if enter == "history":
        last = history.get(sid)
        if isinstance(last, str) and _is_leaf(d, last) and sid in machine.ancestors(d, last):
            return last
    while d.states[sid].initial is not None:
        sid = d.states[sid].initial
    return sid


# ---- the high-water grant ----

def held_of(g: Grant) -> dict:
    return {**{k: list(getattr(g, k)) for k in _LISTS}, **{k: getattr(g, k) for k in _LEVELS}, "checkout": [g.checkout]}


def unheld(held: dict, g: Grant) -> dict:
    """What an effective grant has that the instance has never held, per key, as Change.adds lists it."""
    adds = {}
    for k in _LISTS:
        if new := [x for x in getattr(g, k) if x not in held[k]]:
            adds[k] = new
    for k, order in _LEVELS.items():
        if order.index(getattr(g, k)) > order.index(held[k]):
            adds[k] = [getattr(g, k)]
    if g.checkout is not False and g.checkout not in held["checkout"]:
        adds["checkout"] = [g.checkout]
    return adds


def _raised(held: dict, g: Grant) -> dict:
    out = {k: [*held[k], *(x for x in getattr(g, k) if x not in held[k])] for k in _LISTS}
    for k, order in _LEVELS.items():
        out[k] = max(held[k], getattr(g, k), key=order.index)
    out["checkout"] = [*held["checkout"], *([g.checkout] if g.checkout not in held["checkout"] else [])]
    return out


def _held_ok(held) -> bool:
    if not isinstance(held, dict) or set(held) != {*_LISTS, *_LEVELS, "checkout"}:
        return False
    if not all(isinstance(held[k], list) and all(isinstance(x, str) for x in held[k]) for k in _LISTS):
        return False
    if not all(any(held[k] is v or (type(v) is str and held[k] == v) for v in order) for k, order in _LEVELS.items()):
        return False
    return isinstance(held["checkout"], list) and all(c is False or (isinstance(c, str) and c in machine.CHECKOUTS) for c in held["checkout"])


def grant_json(g: Grant) -> dict:
    return {k: list(v) if isinstance(v, tuple) else v for k, v in dataclasses.asdict(g).items()}


def change_json(c: machine.Change) -> dict:
    return {part: {k: list(v) for k, v in getattr(c, part).items()} for part in ("adds", "removes", "keeps")}


def _exit_json(e: machine.Exit) -> dict:
    return {k: list(v) if isinstance(v, tuple) else v for k, v in dataclasses.asdict(e).items()}


# ---- the instance ----

@dataclass
class Instance:
    workflow: str
    version: str
    state: str
    definitions: dict[str, str]          # version -> text: the current one, and those the trail or a pending move names
    entered: float                       # when the current state was entered, for time
    held: dict
    history: dict[str, str] = field(default_factory=dict)  # parent -> the leaf it was last in under it
    counters: dict[str, dict[str, float]] = field(default_factory=lambda: {c: {} for c in machine.COUNTERS})
    paused: bool = False
    kept: bool = False               # stays on its version until a move by hand: the newest one dropped its state
    stopped: bool = False            # the session isn't running: its clock doesn't run, as while paused
    trail: list[dict] = field(default_factory=list)        # {from, from_version, to, to_version}, newest last
    pending: dict | None = None
    created: float = 0.0

    @classmethod
    def new(cls, text: str, now: float) -> Instance:
        d = _parse(text)
        leaf = _enter(d, d.initial, {}, "first")
        inst = cls(workflow=d.name, version=version_of(text), state=leaf, definitions={version_of(text): text}, entered=now,
                   held=held_of(machine.effective(d, leaf)), created=now)
        for s in machine.ancestors(d, leaf):
            inst.counters["rounds"][s] = 1
        return inst

    def definition(self, version: str | None = None) -> Definition:
        return _parse(self.definitions[version or self.version])

    def to_json(self) -> dict:
        return {"schema": SCHEMA, **dataclasses.asdict(self)}

    @classmethod
    def from_json(cls, raw) -> Instance:
        bad = MachineError("the session's machine record can't be read")
        if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
            raise bad
        names = {f.name for f in dataclasses.fields(cls)}
        if set(raw) - {"schema"} != names:
            raise bad
        try:
            inst = cls(**{k: raw[k] for k in names})
        except TypeError:
            raise bad from None
        defs = inst.definitions
        if not (isinstance(defs, dict) and all(isinstance(t, str) and version_of(t) == v for v, t in defs.items())
                and inst.version in defs and isinstance(inst.workflow, str)):
            raise bad
        try:
            d = inst.definition()
        except (DefinitionError, MachineError):
            raise bad from None
        if not _is_leaf(d, inst.state) or not isinstance(inst.paused, bool) or not isinstance(inst.kept, bool) or not isinstance(inst.stopped, bool) or not _held_ok(inst.held):
            raise bad
        if not isinstance(inst.history, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in inst.history.items()):
            raise bad
        if not (isinstance(inst.counters, dict) and set(inst.counters) == set(machine.COUNTERS) and all(
                isinstance(c, dict) and all(isinstance(k, str) and type(v) in (int, float) for k, v in c.items()) for c in inst.counters.values())):
            raise bad
        if type(inst.entered) not in (int, float) or type(inst.created) not in (int, float):
            raise bad
        keys = {"from", "from_version", "to", "to_version"}
        if not isinstance(inst.trail, list) or not all(isinstance(t, dict) and set(t) == keys and t["from_version"] in defs
                                                       and t["to_version"] in defs for t in inst.trail):
            raise bad
        if inst.pending is not None and not (isinstance(inst.pending, dict) and inst.pending.get("to_version") in defs):
            raise bad
        return inst

    @property
    def ticking(self) -> bool:
        return not self.paused and not self.stopped

    def facts(self, now: float) -> dict:
        """The counters as `requires` names them, with the time in the current state up to now."""
        d = self.definition()
        chain = machine.ancestors(d, self.state)
        out = {}
        for sid in d.states:
            out[f"rounds.{sid}"] = int(self.counters["rounds"].get(sid, 0))
            out[f"time.{sid}"] = int(self.counters["time"].get(sid, 0) + (max(0.0, now - self.entered) if sid in chain and self.ticking else 0))
            out[f"tokens.{sid}"] = int(self.counters["tokens"].get(sid, 0))
        return out


def add_tokens(inst: Instance, tokens: int) -> None:
    """Tokens a turn used, counted in the current state and its parents."""
    if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0:
        raise MachineError("tokens is a whole number")
    for s in machine.ancestors(inst.definition(), inst.state):
        inst.counters["tokens"][s] = inst.counters["tokens"].get(s, 0) + tokens


# ---- moves ----
# Each returns what happened. A move that happened carries "log": the row for the machine log, which the caller writes.

def move(inst: Instance, to: str, by: str, *, enter: str = "first", latest: str | None = None, who: str | None = None,
         now: float | None = None) -> dict:
    """Move to `to` (a parent enters its first state, or with enter = "history" where it last was). `latest` is the
    definition's newest text: a move to a state it has takes it. Once a machine's move finds the current state gone from
    the newest text, the instance keeps its version until a move by hand."""
    now = time.time() if now is None else now
    if by not in ("hand", "machine"):
        raise MachineError("a move is by hand or by the machine")
    if not isinstance(enter, str) or enter not in machine.ENTERS:
        raise MachineError(f"enter is one of {', '.join(machine.ENTERS)}")
    if not isinstance(to, str):
        raise MachineError("to names a state")
    if inst.paused and by == "machine":
        return {"moved": False, "paused": True}
    text = inst.definitions[inst.version]
    if latest is not None and version_of(latest) != inst.version:
        try:
            newest = _parse(latest)
        except (DefinitionError, MachineError) as e:
            log.warning("%s: its newest definition can't be used: %s", inst.workflow, e)
        else:
            if by == "machine" and inst.state not in newest.states:
                inst.kept = True
            if to in newest.states and (by == "hand" or not inst.kept):
                text = latest
    target = _parse(text)
    if to not in target.states:
        raise MachineError(f"{to[:64]!r} isn't a state of {inst.workflow}")
    return _propose(inst, text, _enter(target, to, inst.history, enter), by, who, now)


def rollback(inst: Instance, who: str | None = None, now: float | None = None) -> dict:
    """Back to the state before the last move, on the version it was on."""
    now = time.time() if now is None else now
    if not inst.trail:
        raise MachineError("there's no move to roll back")
    last = inst.trail[-1]
    return _propose(inst, inst.definitions[last["from_version"]], last["from"], "rollback", who, now)


def confirm_move(inst: Instance, pending_id, who: str | None, accept: bool = True, now: float | None = None) -> dict:
    """Completes the move that waits for a confirm, or drops it. Refused if the session has moved since it was asked."""
    now = time.time() if now is None else now
    p = inst.pending
    if p is None or not isinstance(pending_id, str) or not secrets.compare_digest(p["id"], pending_id):
        raise MachineError("no move waits for that confirm")
    inst.pending = None
    if p["from"] != inst.state or p["from_version"] != inst.version:
        _prune(inst)
        raise MachineError("the session has moved since that was asked: ask again")
    if not accept:
        _prune(inst)
        return {"moved": False, "declined": True}
    text = inst.definitions[p["to_version"]]
    change = machine.compare(machine.effective(inst.definition(), inst.state), machine.effective(_parse(text), p["to"]))
    return _apply(inst, text, p["to"], p["kind"], p["who"], who, change, now)


def pause(inst: Instance, paused: bool, who: str | None = None, now: float | None = None) -> dict:
    """While paused, the machine doesn't move on its own and its clock doesn't run. Moves by hand and roll-backs still
    move."""
    if not isinstance(paused, bool):
        raise MachineError("paused is true or false")
    if inst.paused == paused:
        return {"paused": paused, "changed": False}
    _bank(inst, time.time() if now is None else now)
    inst.paused = paused
    return {"paused": paused, "changed": True,
            "log": {"from_state": inst.state, "to_state": inst.state, "from_version": inst.version, "to_version": inst.version,
                    "by": "pause" if paused else "resume", "who": who}}


def _propose(inst: Instance, text: str, leaf: str, by: str, who, now: float) -> dict:
    new_d = _parse(text)
    old_grant, new_grant = machine.effective(inst.definition(), inst.state), machine.effective(new_d, leaf)
    change = machine.compare(old_grant, new_grant)
    adds = unheld(inst.held, new_grant)
    if not adds:
        return _apply(inst, text, leaf, by, who, None, change, now)
    to_version = version_of(text)
    inst.definitions[to_version] = text
    inst.pending = {"id": secrets.token_hex(8), "kind": by, "from": inst.state, "from_version": inst.version, "to": leaf,
                    "to_version": to_version, "who": who, "change": change_json(change), "adds": adds}
    _prune(inst)
    return {"moved": False, "needs_confirm": True, "pending": inst.pending["id"], "to": leaf, "change": change_json(change),
            "adds": adds, "widening": change.widens}


def _bank(inst: Instance, now: float) -> None:
    """The time since the clock last started, counted in the current state and its parents if the clock is running."""
    if inst.ticking:
        elapsed = max(0.0, now - inst.entered)
        for s in machine.ancestors(inst.definition(), inst.state):
            inst.counters["time"][s] = inst.counters["time"].get(s, 0) + elapsed
    inst.entered = max(inst.entered, now)


def set_stopped(inst: Instance, stopped: bool, at: float) -> bool:
    """The session stopped running at `at`, or runs again from `at`. Whether that changed anything."""
    if inst.stopped == stopped:
        return False
    _bank(inst, at)
    inst.stopped = stopped
    return True


def _apply(inst: Instance, text: str, leaf: str, by: str, who, confirmed_by, change: machine.Change, now: float) -> dict:
    old_d, old, old_version = inst.definition(), inst.state, inst.version
    _bank(inst, now)
    chain = machine.ancestors(old_d, old)
    for parent in chain[1:]:
        inst.history[parent] = old
    to_version = version_of(text)
    inst.definitions[to_version] = text
    new_d = _parse(text)
    if by == "hand":
        inst.kept = False
    if by == "rollback":
        inst.trail.pop()
    else:
        for s in machine.ancestors(new_d, leaf):
            inst.counters["rounds"][s] = inst.counters["rounds"].get(s, 0) + 1
        inst.trail = [*inst.trail, {"from": old, "from_version": old_version, "to": leaf, "to_version": to_version}][-MAX_TRAIL:]
    inst.state, inst.version, inst.entered = leaf, to_version, now
    inst.workflow = new_d.name
    inst.held = _raised(inst.held, machine.effective(new_d, leaf))
    inst.pending = None
    _prune(inst)
    return {"moved": True, "from": old, "to": leaf, "widening": change.widens, "change": change_json(change),
            "log": {"from_state": old, "to_state": leaf, "from_version": old_version, "to_version": to_version, "by": by,
                    "who": who, "widening": change.widens, "confirmed_by": confirmed_by, "change": change_json(change)}}


def _prune(inst: Instance) -> None:
    keep = {inst.version, *(t["from_version"] for t in inst.trail), *(t["to_version"] for t in inst.trail)}
    if inst.pending:
        keep.add(inst.pending["to_version"])
    inst.definitions = {v: t for v, t in inst.definitions.items() if v in keep}


# ---- the service: files, the log, the socket ops ----

class Machines:
    """The instances of the sessions under `sessions`. `action_of(id)` gives an action as the library has it now, or None;
    `is_session(name)` says whether a name is a session's."""

    def __init__(self, sessions: Path, log_path: Path, action_of, is_session, clock=time.time):
        self.sessions = Path(sessions)
        self.log_path = log_path
        self.action_of = action_of
        self.is_session = is_session
        self.clock = clock
        self._log: Log | None = None
        self._watchers: list = []

    def on_move(self, callback) -> None:
        """callback(name, result) after each move, confirm and roll-back that was saved, by hand or by the machine: one
        that moved ("moved"), one that waits for a confirm ("needs_confirm", "pending") and a confirm said no to
        ("declined"). The result also says who did it ("by") and the state and version after it. A watcher that fails is
        logged and doesn't undo the move, which is saved before it is called."""
        self._watchers.append(callback)

    @property
    def log(self) -> Log:
        if self._log is None:
            self._log = Log(self.log_path, clock=self.clock)
        return self._log

    def latest(self, record: dict) -> str | None:
        """The newest definition text for a session's workflow."""
        action = self.action_of(record.get("config", {}).get("action"))
        return definition_for(action) if action else None

    # --- files ---------------------------------------------------------------------
    @staticmethod
    def _write(directory: Path, inst: Instance) -> None:
        path = Path(directory) / FILE
        scratch = path.with_suffix(".tmp")
        fd = os.open(scratch, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(inst.to_json(), f)
        scratch.replace(path)

    def start(self, directory: Path, action: dict) -> Instance:
        """When a session starts: its machine, on its action's workflow."""
        inst = Instance.new(definition_for(action), self.clock())
        self._write(directory, inst)
        return inst

    def remembered(self, directory: Path) -> dict:
        """What goes into the session's history record when its folder goes. The time in the current state so far is
        banked, so the days it spends ended don't count as time in its state."""
        try:
            inst = Instance.from_json(json.loads((Path(directory) / FILE).read_text()))
        except (OSError, ValueError, MachineError):
            return {}
        set_stopped(inst, True, self._ended_at(Path(directory), inst))
        return {"machine": inst.to_json()}

    def restore(self, directory: Path, record: dict) -> None:
        """When resume brings a folder back from the history: the machine it had, if the record kept one."""
        if "machine" in record:
            try:
                self._write(directory, Instance.from_json(record["machine"]))  # stopped: resume starts its clock
            except MachineError as e:  # it starts again from its workflow's first state, on the next look
                log.warning("%s: %s", record.get("name"), e)

    def load(self, name: str) -> tuple[dict, Instance]:
        if not self.is_session(name):
            raise MachineError("no such session")
        directory = self.sessions / name
        try:
            record = json.loads((directory / "session.json").read_text())
        except (OSError, ValueError) as e:
            raise MachineError("no such session") from e
        try:
            raw = json.loads((directory / FILE).read_text())
        except FileNotFoundError:  # a session from before instances: it gets one now
            latest = self.latest(record)
            if latest is None:
                raise MachineError(f"{name}'s action is gone, so it has no workflow") from None
            inst = Instance.new(latest, self.clock())
            self._write(directory, inst)
            return record, inst
        except (OSError, ValueError) as e:
            raise MachineError("the session's machine record can't be read") from e
        inst = Instance.from_json(raw)
        if not inst.stopped and (directory / ENDED).exists():  # Claude has ended there: its clock stopped then
            set_stopped(inst, True, self._ended_at(directory, inst))
            self._write(directory, inst)
        return record, inst

    def _ended_at(self, directory: Path, inst: Instance) -> float:
        try:
            at = (directory / ENDED).stat().st_mtime
        except OSError:
            at = self.clock()
        return min(at, self.clock())

    def stopped(self, name: str) -> None:
        """Its terminal is gone: the clock stops now, if nothing said so sooner."""
        self._running(name, False)

    def resumed(self, name: str) -> None:
        """Called as a session starts again, before its markers go: the clock runs from now."""
        self._running(name, True)

    def _running(self, name: str, running: bool) -> None:
        try:
            _record, inst = self.load(name)
            if set_stopped(inst, not running, self.clock()):
                self.save(name, inst)
        except (MachineError, OSError) as e:
            log.warning("%s: %s", name, e)

    def save(self, name: str, inst: Instance) -> None:
        self._write(self.sessions / name, inst)

    # --- views ---------------------------------------------------------------------
    def view(self, record: dict, inst: Instance) -> dict:
        d = inst.definition()
        latest = self.latest(record)
        newer = None
        if latest is not None and version_of(latest) != inst.version:
            try:
                newer = {"version": version_of(latest), "has_state": inst.state in _parse(latest).states, "kept": inst.kept}
            except (DefinitionError, MachineError):
                newer = None
        pending = {k: v for k, v in inst.pending.items() if k != "who"} if inst.pending else None
        return {"instance": {"workflow": inst.workflow, "version": inst.version, "state": inst.state, "paused": inst.paused,
                             "history": dict(inst.history), "counters": inst.counters, "held": inst.held, "pending": pending,
                             "can_roll_back": bool(inst.trail), "created": inst.created, "entered": inst.entered,
                             "definition": inst.definitions[inst.version]},
                "grant": grant_json(machine.effective(d, inst.state)),
                "exits": [_exit_json(e) for e in machine.exits_of(d, inst.state)],
                "facts": inst.facts(self.clock()), "newer": newer}

    # --- acting on a session's machine: load, change, save, log ---------------------
    def _act(self, name, change, by: str | None = None) -> dict:
        record, inst = self.load(name)
        result = change(record, inst, self.clock())
        self.save(name, inst)
        row = result.pop("log", None)
        if row is not None:
            try:
                self.log.move(record["session_id"], name, **row)
            except (sqlite3.Error, LogError, OSError):
                log.exception("%s: the move wasn't logged", name)
        result = {**result, "state": inst.state, "version": inst.version, "paused": inst.paused}
        if by is not None and (result.get("moved") or result.get("needs_confirm") or result.get("declined")):
            told = {**result, "by": row["by"] if row else by}
            for watcher in list(self._watchers):
                try:
                    watcher(name, told)
                except Exception:  # noqa: BLE001: the move is saved; what watches it says what went wrong
                    log.exception("%s: a watcher of its moves failed", name)
        return result

    def move(self, name, to, by: str = "machine", enter: str = "first", who: str | None = None) -> dict:
        return self._act(name, lambda record, inst, now: move(inst, to, by, enter=enter, latest=self.latest(record), who=who, now=now), by)

    def rollback(self, name, who: str | None = None) -> dict:
        return self._act(name, lambda _record, inst, now: rollback(inst, who, now), "rollback")

    def confirm_move(self, name, pending_id, who: str | None, accept: bool = True) -> dict:
        if not isinstance(accept, bool):
            raise MachineError("accept is true or false")
        return self._act(name, lambda _record, inst, now: confirm_move(inst, pending_id, who, accept, now), "confirm")

    def pause(self, name, paused, who: str | None = None) -> dict:
        return self._act(name, lambda _record, inst, now: pause(inst, paused, who, now))

    # --- the socket ops (maintainer only: the caller checks the login) ----------------
    def request(self, op: str, req: dict, who: str | None) -> dict:
        """Moves here are always by hand, and `who` is the logged-in maintainer: neither comes from the request."""
        if op not in OPS:
            return {"ok": False, "error": f"unknown request: {op}"}
        name = req.get("name")
        try:
            if op == "machine.get":
                return {"ok": True, **self.view(*self.load(name))}
            if op == "machine.history":
                return {"ok": True, **self.log.history(self.load(name)[0]["session_id"])}
            if op == "machine.move":
                return {"ok": True, **self.move(name, req.get("to"), "hand", req.get("enter", "first"), who)}
            if op == "machine.confirm":
                return {"ok": True, **self.confirm_move(name, req.get("pending"), who, req.get("accept", True))}
            if op == "machine.rollback":
                return {"ok": True, **self.rollback(name, who)}
            return {"ok": True, **self.pause(name, req.get("paused"), who)}
        except (MachineError, LogError) as e:
            return {"ok": False, "error": str(e)}
        except sqlite3.Error:
            log.exception("%s: the machine log can't be read", name)
            return {"ok": False, "error": "the machine log can't be read"}
