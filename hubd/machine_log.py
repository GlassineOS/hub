# SPDX-License-Identifier: GPL-2.0-or-later
"""The machine log: every evaluation and every move of a workflow instance (spec 012, FR-018, FR-026).

Rows are keyed by the session's conversation id, not its name: names come back, and a later session under the same name
mustn't inherit an earlier one's moves. The log outlives the session's folder, so a past session's history stays
readable. Evidence is a quote from a transcript, so it can be an outsider's words: it is kept as data and shown as data.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

KEEP_ROWS = 100000      # per table
MAX_READ = 1000
MAX_TEXT = 4000         # a proposal or a piece of evidence, clipped
MOVE_KINDS = ("hand", "machine", "rollback", "pause", "resume")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluations (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, name TEXT NOT NULL, at REAL NOT NULL,
    signal TEXT NOT NULL, state TEXT NOT NULL, version TEXT NOT NULL, proposal TEXT, evidence TEXT, checks TEXT NOT NULL,
    judge TEXT, ms INTEGER, cost REAL, failed INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS evaluations_session ON evaluations (session_id, seq);
CREATE TABLE IF NOT EXISTS moves (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, name TEXT NOT NULL, at REAL NOT NULL,
    from_state TEXT NOT NULL, to_state TEXT NOT NULL, from_version TEXT NOT NULL, to_version TEXT NOT NULL,
    by TEXT NOT NULL, who TEXT, widening INTEGER NOT NULL, confirmed_by TEXT, change TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS moves_session ON moves (session_id, seq);
"""


class LogError(Exception):
    """A row the log won't take."""


def _clip(value, limit: int = MAX_TEXT) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise LogError("text fields are text")
    return value if len(value) <= limit else value[:limit - 1] + "…"


class Log:
    def __init__(self, path: Path | str, clock=time.time):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.lock = threading.RLock()
        self._clock = clock

    # --- writing -------------------------------------------------------------------
    def evaluation(self, session_id: str, name: str, signal: str, state: str, version: str, proposal: str | None = None,
                   evidence: str | None = None, checks=None, judge: str | None = None, ms: int | None = None,
                   cost: float | None = None, failed: bool = False) -> int:
        """One try of a state's exits. checks: each check with the value it saw, as a list or a mapping (kept as JSON).
        A judge that was unreachable or answered out of form is `failed`, with no proposal."""
        for value in (session_id, name, signal, state, version):
            if not isinstance(value, str) or not value:
                raise LogError("an evaluation names its session, signal, state and version")
        if ms is not None and (not isinstance(ms, int) or isinstance(ms, bool) or ms < 0):
            raise LogError("ms is a whole number")
        if cost is not None and (not isinstance(cost, (int, float)) or isinstance(cost, bool) or cost < 0):
            raise LogError("cost is a number")
        try:
            checks_json = json.dumps(checks if checks is not None else [])
        except (TypeError, ValueError) as e:
            raise LogError("checks must be JSON") from e
        with self.lock, self.db:
            cur = self.db.execute(
                "INSERT INTO evaluations (session_id, name, at, signal, state, version, proposal, evidence, checks, judge, ms, cost, failed) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, name, self._clock(), signal, state, version, _clip(proposal), _clip(evidence), checks_json,
                 _clip(judge, 64), ms, cost, int(bool(failed))))
            self._prune("evaluations")
            return cur.lastrowid

    def move(self, session_id: str, name: str, from_state: str, to_state: str, by: str, from_version: str = "",
             to_version: str = "", who: str | None = None, widening: bool = False, confirmed_by: str | None = None,
             change: dict | None = None) -> int:
        """A move, a roll-back, or a pause or resume of the machine (from and to the same state then).
        `who` is whoever did it by hand; `confirmed_by` whoever confirmed a move that gave a capability never held."""
        if by not in MOVE_KINDS:
            raise LogError(f"by is one of {', '.join(MOVE_KINDS)}")
        for value in (session_id, name, from_state, to_state):
            if not isinstance(value, str) or not value:
                raise LogError("a move names its session and both states")
        with self.lock, self.db:
            cur = self.db.execute(
                "INSERT INTO moves (session_id, name, at, from_state, to_state, from_version, to_version, by, who, widening, confirmed_by, change) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, name, self._clock(), from_state, to_state, from_version, to_version, by, _clip(who, 64),
                 int(bool(widening)), _clip(confirmed_by, 64), json.dumps(change or {})))
            self._prune("moves")
            return cur.lastrowid

    def _prune(self, table: str) -> None:
        newest = self.db.execute(f"SELECT max(seq) AS n FROM {table}").fetchone()["n"] or 0
        if newest > KEEP_ROWS:
            self.db.execute(f"DELETE FROM {table} WHERE seq <= ?", (newest - KEEP_ROWS,))

    # --- reading -------------------------------------------------------------------
    def sessions(self, limit: int = 200) -> list[dict]:
        """The conversations the log has rows for, newest first: the name each last had, when, how many evaluations, and
        the versions it ran on. What a replay can be run on."""
        with self.lock:
            rows = self.db.execute(
                "SELECT session_id, max(at) AS last, count(*) AS n, group_concat(DISTINCT version) AS versions, "
                "(SELECT name FROM evaluations e2 WHERE e2.session_id = e.session_id ORDER BY seq DESC LIMIT 1) AS name "
                "FROM evaluations e GROUP BY session_id ORDER BY last DESC LIMIT ?", (max(1, min(MAX_READ, limit)),)).fetchall()
        return [{"session_id": r["session_id"], "name": r["name"], "last": r["last"], "evaluations": r["n"],
                 "versions": (r["versions"] or "").split(",")} for r in rows]

    def history(self, session_id: str, limit: int = MAX_READ) -> dict:
        """The session's evaluations and moves, oldest first, each list the newest `limit` rows."""
        limit = max(1, min(MAX_READ, limit)) if isinstance(limit, int) and not isinstance(limit, bool) else MAX_READ
        with self.lock:
            evaluations = self.db.execute(
                "SELECT * FROM (SELECT * FROM evaluations WHERE session_id = ? ORDER BY seq DESC LIMIT ?) ORDER BY seq",
                (session_id, limit)).fetchall()
            moves = self.db.execute(
                "SELECT * FROM (SELECT * FROM moves WHERE session_id = ? ORDER BY seq DESC LIMIT ?) ORDER BY seq",
                (session_id, limit)).fetchall()
        return {"evaluations": [{**dict(r), "checks": json.loads(r["checks"]), "failed": bool(r["failed"])} for r in evaluations],
                "moves": [{**{k: r[k] for k in r.keys() if k not in ("from_state", "to_state")}, "from": r["from_state"],
                           "to": r["to_state"], "widening": bool(r["widening"]), "change": json.loads(r["change"])} for r in moves]}
