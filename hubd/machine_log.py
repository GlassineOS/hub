# SPDX-License-Identifier: GPL-2.0-or-later
"""The machine log: every evaluation and every move of a workflow instance (spec 012, FR-018, FR-026), and every report
sent up the chain of owners with its answer (FR-053).

Rows are keyed by the session's conversation id, not its name: names come back, and a later session under the same name
mustn't inherit an earlier one's moves. The log outlives the session's folder, so a past session's history stays
readable. Evidence is a quote from a transcript, so it can be an outsider's words: it is kept as data and shown as data.
"""
from __future__ import annotations

import json
import secrets
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
CREATE TABLE IF NOT EXISTS reports (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, at REAL NOT NULL, kind TEXT NOT NULL,
    from_name TEXT NOT NULL, from_sid TEXT NOT NULL, to_name TEXT NOT NULL, to_sid TEXT, evidence TEXT NOT NULL,
    proposal TEXT NOT NULL, chain TEXT NOT NULL, parent TEXT, action TEXT, state TEXT NOT NULL, decision TEXT, note TEXT,
    answered_by TEXT, answered_at REAL);
CREATE INDEX IF NOT EXISTS reports_from ON reports (from_sid, seq);
CREATE INDEX IF NOT EXISTS reports_to ON reports (to_sid, seq);
"""
REPORT_KINDS = ("blocker", "decision", "approval")  # approval: made by the hub, for an `approve` level or a managed start
REPORT_STATES = ("open", "answered", "forwarded")
YOU = "you"  # a report's addressee when no session above may decide it: a Needs-you decision


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

    def report(self, kind: str, from_name: str, from_sid: str, to_name: str, to_sid: str | None, evidence: str, proposal: str,
               chain: list[str], parent: str | None = None, action: dict | None = None) -> dict:
        """A report sent up the chain (FR-051): who sent it, to whom (a session, or YOU), what it says, the chain it came
        through, the report it forwards, and for one the hub made, what an approval does."""
        if kind not in REPORT_KINDS:
            raise LogError(f"a report is one of {', '.join(REPORT_KINDS)}")
        for value in (from_name, from_sid, to_name):
            if not isinstance(value, str) or not value:
                raise LogError("a report names who sent it and to whom")
        if not (isinstance(chain, list) and all(isinstance(c, str) for c in chain)):
            raise LogError("a report's chain is a list of names")
        report_id = f"rp-{secrets.token_hex(6)}"
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO reports (id, at, kind, from_name, from_sid, to_name, to_sid, evidence, proposal, chain, parent, action, state) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')",
                (report_id, self._clock(), kind, from_name, from_sid, to_name, to_sid, _clip(evidence), _clip(proposal),
                 json.dumps(chain), parent, json.dumps(action) if action is not None else None))
            self._prune("reports")
        return self.get_report(report_id)

    def get_report(self, report_id) -> dict | None:
        if not isinstance(report_id, str):
            return None
        with self.lock:
            row = self.db.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        return _report(row) if row else None

    def settle_report(self, report_id: str, state: str, decision: str | None = None, note: str | None = None,
                      answered_by: str | None = None) -> dict | None:
        """An open report answered or forwarded, or a forwarded one answered with the report it went on in. Nothing if it is
        answered already: the first answer stands."""
        if state not in REPORT_STATES[1:]:
            raise LogError("a report is answered or forwarded")
        with self.lock, self.db:
            done = self.db.execute("UPDATE reports SET state = ?, decision = ?, note = ?, answered_by = ?, answered_at = ? "
                                   "WHERE id = ? AND (state = 'open' OR (state = 'forwarded' AND ? = 'answered'))",
                                   (state, decision, _clip(note), _clip(answered_by, 64), self._clock(), report_id, state)).rowcount
        return self.get_report(report_id) if done else None

    def reports(self, *, from_sid: str | None = None, to_sid: str | None = None, state: str | None = None,
                to_name: str | None = None, limit: int = MAX_READ) -> list[dict]:
        """Reports, oldest first, by who sent them, who they're for, or their state."""
        where, args = [], []
        for column, value in (("from_sid", from_sid), ("to_sid", to_sid), ("state", state), ("to_name", to_name)):
            if value is not None:
                where.append(f"{column} = ?")
                args.append(value)
        sql = "SELECT * FROM reports" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY seq DESC LIMIT ?"
        with self.lock:
            rows = self.db.execute(sql, (*args, max(1, min(MAX_READ, limit)))).fetchall()
        return [_report(r) for r in reversed(rows)]

    def _prune(self, table: str) -> None:
        newest = self.db.execute(f"SELECT max(seq) AS n FROM {table}").fetchone()["n"] or 0
        if newest > KEEP_ROWS:
            self.db.execute(f"DELETE FROM {table} WHERE seq <= ?", (newest - KEEP_ROWS,))

    # --- reading -------------------------------------------------------------------
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
        with self.lock:
            reports = self.db.execute(
                "SELECT * FROM (SELECT * FROM reports WHERE from_sid = ? OR to_sid = ? ORDER BY seq DESC LIMIT ?) ORDER BY seq",
                (session_id, session_id, limit)).fetchall()
        return {"evaluations": [{**dict(r), "checks": json.loads(r["checks"]), "failed": bool(r["failed"])} for r in evaluations],
                "reports": [_report(r) for r in reports],
                "moves": [{**{k: r[k] for k in r.keys() if k not in ("from_state", "to_state")}, "from": r["from_state"],
                           "to": r["to_state"], "widening": bool(r["widening"]), "change": json.loads(r["change"])} for r in moves]}


def _report(row) -> dict:
    out = dict(row)
    out["chain"] = json.loads(out["chain"])
    out["action"] = json.loads(out["action"]) if out["action"] else None
    out.pop("seq", None)
    return out
