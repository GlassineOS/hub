# SPDX-License-Identifier: GPL-2.0-or-later
"""What a piece of work cost (spec 012, FR-090) and how fast its moves were (SC-003): the `machine.costs` op, a login's.

A piece of work is a session and the sessions it manages, theirs too, over every conversation it has had (a fresh context
starts a new one, handoff.py). For one item, it is every such piece whose session is on that issue or pull request.

- **Sessions at once**: the most of them that ran at the same time, from when each started to when it ended (now, for one
  still running).
- **Judge calls**: the evaluations a judge answered, with their time and cost as the machine log kept them (FR-018).
- **Tokens, cost and time per state**: the instance's counters (`tokens.<state>`, `time.<state>`; tokens and cost banked
  from each session's status line as it moves and on its signals, instances.bank_usage). A state's figure counts the
  states inside it. What the status line didn't say is not known, not 0.
- **Overrides**: moves by hand that replaced or undid a move of the machine: a roll-back right after one, or a move by hand
  within OVERRIDE_WINDOW of one. The hub's own moves back (a move that couldn't take effect) aren't overrides.
- **Latency**: from the first signal of a pass to the move it made being logged (machinerun.py keeps it in the
  evaluation's checks). Its fixed parts are said beside it: the debounce, the wait for a pull request lookup, the judge's
  time limit.

Reads only: the machine log, the session folders and the history. Standard library only, as hubd is.
"""
from __future__ import annotations

import json
import logging
import statistics
import time
from pathlib import Path

from . import judge as judgelib
from . import machine
from .handoff import conversations
from .instances import FILE as MACHINE_FILE
from .instances import USAGE_KEY, Instance, MachineError, usage_of

log = logging.getLogger("hubd.machinecost")

OVERRIDE_WINDOW = 600  # seconds after a machine's move in which a move by hand counts as overriding it
MAX_DEPTH = 4          # levels of managed sessions followed under one owner
ENDED_FILE = "ended"


def _ms_stats(values: list[int]) -> dict:
    if not values:
        return {"count": 0, "median_ms": None, "p90_ms": None, "max_ms": None}
    ordered = sorted(values)
    return {"count": len(ordered), "median_ms": round(statistics.median(ordered)),
            "p90_ms": ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))], "max_ms": ordered[-1]}


def overrides(moves: list[dict], window: float = OVERRIDE_WINDOW) -> tuple[int, int]:
    """(overrides, the machine's moves) in a session's moves, oldest first."""
    count, machine_moves, last = 0, 0, None
    for m in moves:
        if m["by"] in ("pause", "resume"):
            continue
        if m["by"] == "machine":
            machine_moves += 1
            last = m
            continue
        if m.get("who") == "hub":  # a move that couldn't take effect, sent back by the hub
            last = None
            continue
        if last is not None and (m["by"] == "rollback" or m["at"] - last["at"] <= window):
            count += 1
        last = None
    return count, machine_moves


class Costs:
    def __init__(self, agents, clock=time.time, debounce: float | None = None):
        self.agents = agents
        self.clock = clock
        self.debounce = debounce

    # --- the sessions, live and past --------------------------------------------------------
    def _records(self) -> list[dict]:
        """Every session the hub knows: the folders, then the history's (the old conversations of a fresh context too). Each
        with its instance, its cost per state, and when it started and ended (None: still there)."""
        out, seen = [], set()
        root = Path(self.agents.sessions)
        for directory in sorted(root.iterdir()) if root.is_dir() else ():
            try:
                record = json.loads((directory / "session.json").read_text())
            except (OSError, ValueError):
                continue
            if not isinstance(record, dict) or not isinstance(record.get("session_id"), str):
                continue
            try:
                inst = Instance.from_json(json.loads((directory / MACHINE_FILE).read_text()))
            except (OSError, ValueError, MachineError):
                inst = None
            ended = directory / ENDED_FILE
            out.append({"record": {**record, "name": directory.name}, "inst": inst, "cost": usage_of(directory),
                        "ended": ended.stat().st_mtime if ended.exists() else None})
            seen.add(record["session_id"])
        for record in self.agents.history.records():
            if not isinstance(record, dict) or record.get("session_id") in seen or not isinstance(record.get("session_id"), str):
                continue
            try:
                inst = Instance.from_json(record["machine"]) if "machine" in record else None
            except MachineError:
                inst = None
            out.append({"record": record, "inst": inst, "cost": dict(record.get(USAGE_KEY) or {}), "ended": record.get("ended") or 0.0})
            seen.add(record["session_id"])
        # A conversation a fresh context took over is part of the session that took over: its log rows are read with it.
        taken = {c for r in out for c in conversations(r["record"])[:-1]}
        return [r for r in out if r["record"]["session_id"] not in taken]

    @staticmethod
    def _owner_of(row: dict) -> tuple[str, str] | None:
        owned = row["record"].get("owner")
        if isinstance(owned, dict) and isinstance(owned.get("name"), str) and isinstance(owned.get("session_id"), str):
            return owned["name"], owned["session_id"]
        return None

    def _piece(self, top: dict, rows: list[dict]) -> list[dict]:
        """The session and everything it manages, down the levels."""
        found, level = [top], [top]
        for _ in range(MAX_DEPTH):
            ids = {(r["record"]["name"], c) for r in level for c in conversations(r["record"])}
            level = [r for r in rows if self._owner_of(r) in ids and r not in found]
            if not level:
                break
            found += level
        return found

    # --- one session's figures --------------------------------------------------------------
    def _session(self, row: dict) -> dict:
        record, inst = row["record"], row["inst"]
        history = self.agents.machines.log.history(conversations(record))
        judged = [e for e in history["evaluations"] if e.get("judge")]
        latency = [e["checks"]["latency_ms"] for e in history["evaluations"]
                   if isinstance(e.get("checks"), dict) and isinstance(e["checks"].get("latency_ms"), int)]
        over, by_machine = overrides(history["moves"])
        states = []
        if inst is not None:
            facts = inst.facts(self.clock())
            d = inst.definition()
            for sid, s in d.states.items():
                rounds = facts.get(f"rounds.{sid}", 0)
                seconds, tokens = facts.get(f"time.{sid}", 0), facts.get(f"tokens.{sid}", 0)
                if rounds or seconds or tokens or sid in row["cost"]:
                    states.append({"state": sid, "parent": s.parent, "rounds": rounds, "seconds": seconds, "tokens": tokens,
                                   "cost": row["cost"].get(sid)})
            tops = [st for st in states if st["parent"] is None]
            tokens = sum(st["tokens"] for st in tops)
            cost = round(sum(st["cost"] or 0 for st in tops), 6) if any(st["cost"] is not None for st in tops) else None
            seconds = sum(st["seconds"] for st in tops)
        else:
            tokens, cost, seconds = 0, None, 0
        config = record.get("config") or {}
        return {"name": record.get("name"), "session_id": record["session_id"], "conversations": len(conversations(record)),
                "persona": config.get("persona"), "action": config.get("action"),
                "workflow": inst.workflow if inst else None, "state": inst.state if inst else None,
                "entry": (record.get("owner") or {}).get("entry") if isinstance(record.get("owner"), dict) else None,
                "started": record.get("created"), "ended": row["ended"], "running": row["ended"] is None,
                "judge_calls": len(judged), "judge_ms": sum(e.get("ms") or 0 for e in judged),
                "judge_cost": round(sum(e.get("cost") or 0 for e in judged), 6),
                "tokens": tokens, "cost": cost, "seconds": seconds, "states": states,
                "machine_moves": by_machine, "overrides": over, "latency": latency}

    def _summed(self, rows: list[dict]) -> dict:
        sessions = [self._session(r) for r in rows]
        now = self.clock()
        spans = [(s["started"], max(s["started"], s["ended"] if s["ended"] is not None else now)) for s in sessions if isinstance(s["started"], (int, float))]
        edges = sorted([(a, 1) for a, _b in spans] + [(b, -1) for _a, b in spans], key=lambda e: (e[0], e[1]))
        at_once = most = 0
        for _t, step in edges:
            at_once += step
            most = max(most, at_once)
        machine_moves = sum(s["machine_moves"] for s in sessions)
        over = sum(s["overrides"] for s in sessions)
        costs = [s["cost"] for s in sessions if s["cost"] is not None]
        latency = [ms for s in sessions for ms in s.pop("latency")]
        return {"sessions": sessions, "at_once": most, "judge_calls": sum(s["judge_calls"] for s in sessions),
                "judge_ms": sum(s["judge_ms"] for s in sessions), "judge_cost": round(sum(s["judge_cost"] for s in sessions), 6),
                "tokens": sum(s["tokens"] for s in sessions), "cost": round(sum(costs), 6) if costs else None,
                "seconds": sum(s["seconds"] for s in sessions), "machine_moves": machine_moves, "overrides": over,
                "override_rate": round(over / machine_moves, 3) if machine_moves else None,
                "latency": {**_ms_stats(latency), **self.budget()}}

    def budget(self) -> dict:
        """The fixed parts of a signal's way to a move, in seconds."""
        from .agents import PRS_FOR, PRS_WAIT
        from .machinerun import DEBOUNCE

        return {"debounce_s": self.debounce if self.debounce is not None else DEBOUNCE, "pr_lookup_wait_s": PRS_WAIT,
                "pr_lookup_every_s": PRS_FOR, "judge_limit_s": max(judgelib.CLAUDE_TIMEOUT, judgelib.OPENAI_TIMEOUT)}

    # --- the op -----------------------------------------------------------------------------
    def request(self, req: dict) -> dict:
        """{session: name} for one session's piece of work; {repo, number} for every piece on one item; {workflows: true} for
        each workflow's averages."""
        rows = self._records()
        if req.get("workflows") is True:
            return {"ok": True, "workflows": self.by_workflow(rows)}
        if isinstance(req.get("session"), str):
            named = [r for r in rows if r["record"].get("name") == req["session"]]  # its folder first, then the newest ended one
            top = next((r for r in named if "how" not in r["record"]), None) or max(named, key=lambda r: r["ended"] or 0, default=None)
            if top is None:
                return {"ok": False, "error": "no such session"}
            return {"ok": True, "session": req["session"], **self._summed(self._piece(top, rows))}
        repo, number = req.get("repo"), req.get("number")
        if isinstance(repo, str) and isinstance(number, int) and not isinstance(number, bool):
            tops = [r for r in rows if self._owner_of(r) is None and self._on(r, repo, number)]
            pieces = [self._summed(self._piece(t, rows)) | {"session": t["record"].get("name")} for t in tops]
            return {"ok": True, "repo": repo, "number": number, "pieces": pieces}
        return {"ok": False, "error": "name a session, an item (repo and number), or workflows"}

    def _on(self, row: dict, repo: str, number: int) -> bool:
        from .agents import covers_of

        record = row["record"]
        if any(c["repo"].lower() == repo.lower() and c["number"] == number for c in covers_of(record.get("config") or {})):
            return True
        if row["ended"] is None:
            return any(p["repo"].lower() == repo.lower() and p["number"] == number for p in self.agents.known_prs(record["name"]) or ())
        return False

    def by_workflow(self, rows: list[dict]) -> list[dict]:
        """Per workflow that can move: how many sessions ran it, their average judge calls, how often a machine's move was
        overridden by hand, and the median time from a signal to its move."""
        groups: dict[str, list[dict]] = {}
        for r in rows:
            if r["inst"] is not None and len(r["inst"].definition().states) > 1:
                groups.setdefault(r["inst"].workflow, []).append(r)
        out = []
        for name, members in sorted(groups.items()):
            sessions = [self._session(r) for r in members]
            moves = sum(s["machine_moves"] for s in sessions)
            over = sum(s["overrides"] for s in sessions)
            latency = [ms for s in sessions for ms in s["latency"]]
            out.append({"workflow": name, "sessions": len(sessions),
                        "judge_calls_avg": round(sum(s["judge_calls"] for s in sessions) / len(sessions), 2),
                        "judge_cost": round(sum(s["judge_cost"] for s in sessions), 6), "machine_moves": moves, "overrides": over,
                        "override_rate": round(over / moves, 3) if moves else None, "latency_median_ms": _ms_stats(latency)["median_ms"]})
        return out


__all__ = ["Costs", "overrides", "OVERRIDE_WINDOW"]
