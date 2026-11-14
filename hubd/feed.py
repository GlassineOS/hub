# SPDX-License-Identifier: GPL-2.0-or-later
"""The change feed: facts about what changed in the project, and a cursor for each Steward.

The app's work sync sees an issue, a pull request or a run change and records the facts here: which item, what
changed, the old and new state and head commit, when, who, and a link. Never a title, a body, review text or a log
line: those can be an outsider's, and the Steward reads them through its own tools, which treat them as data. Anything
that doesn't fit this shape is dropped, so the app can't smuggle text through.

Nothing here wakes a Steward on a timer or with counts (spec 012 FR-056): what changes in an item it named is passed to
stewardwake.py as it is recorded, and the rest waits until the Steward reads it (FR-057): from its cursor, by item or
repository, or as a short digest per repository. What a Steward may read is decided at read time, and a repository that
can't be told apart as public is treated as private.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
from collections import Counter
from pathlib import Path

ORG = "GlassineOS"
log = logging.getLogger("hubd.feed")

KEEP_SECONDS = 14 * 86400
KEEP_ROWS = 20000
MAX_BATCH = 500        # events in one record
MAX_READ = 500
DEFAULT_READ = 100
OWN_WINDOW = 900       # seconds: a change to an item this soon after a session's write to it is marked that session's own
MAX_MARKS = 2000
MAX_NUMBER = 2**53 - 1  # an issue, pull request or run number: below what SQLite stores as an integer, and what JSON carries exactly

WHATS = ("opened", "state", "head", "review", "checks", "labels", "comments", "run")
_REPO_RE = re.compile(r"\.?[A-Za-z0-9_][A-Za-z0-9._-]{0,99}")
_HEAD_RE = re.compile(r"[0-9a-f]{40}|")
_LOGIN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:\[bot\])?")
_TIME_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")  # [0-9]: \d takes every script's digits
# One observation: the work store's own random name and the number of the outbox row that held it. A retry sends the same id.
_ID_RE = re.compile(r"[0-9a-f]{8,32}-[0-9]{1,18}")
_URL_RE = re.compile(rf"https://github\.com/{ORG}/(?P<repo>[A-Za-z0-9._-]+)/(?:issues|pull|actions/runs)/(?P<n>[0-9]{{1,15}})")
_NUMBER = re.compile(r"[0-9]{1,15}")  # ASCII digits and short: str.isdigit() takes "²", which int() refuses, and a long run is no number here
_LINKS = {"issue": "issues", "pr": "pull", "run": "actions/runs"}
_FAILED_RUN = {"failure", "timed_out", "startup_failure", "cancelled_by_failure"}


def _one_of(*words: str) -> re.Pattern:
    return re.compile("|".join(map(re.escape, ("", *words))))


# What `old` and `new` may be, for each kind of change: the values GitHub's own enums have, or a count, and nothing else.
# A field that took any short word would let an outsider's choice of words in.
_ITEM_STATE = _one_of("OPEN", "CLOSED", "MERGED")
_REVIEW = _one_of("APPROVED", "CHANGES_REQUESTED", "REVIEW_REQUIRED")
_CHECKS = _one_of("passing", "failing", "pending", "none")
_COUNT = re.compile(r"[0-9]{0,4}")
_NOTHING = re.compile("")
_RUN_STATUS = _one_of("queued", "in_progress", "waiting", "requested", "pending", "completed")
_RUN_RESULT = _one_of("success", "failure", "cancelled", "skipped", "timed_out", "neutral", "action_required", "startup_failure", "stale")
_VALUES = {"opened": (_NOTHING, _ITEM_STATE), "state": (_ITEM_STATE, _ITEM_STATE), "head": (_NOTHING, _NOTHING),
           "review": (_REVIEW, _REVIEW), "checks": (_CHECKS, _CHECKS), "labels": (_COUNT, _COUNT),
           "comments": (_NOTHING, _NOTHING), "run": (_RUN_STATUS, _RUN_RESULT)}
_PR_ONLY = ("head", "review", "checks")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL UNIQUE, at TEXT NOT NULL, recorded REAL NOT NULL,
    kind TEXT NOT NULL, repo TEXT NOT NULL, number INTEGER NOT NULL, what TEXT NOT NULL,
    old TEXT NOT NULL, new TEXT NOT NULL, old_head TEXT NOT NULL, new_head TEXT NOT NULL, actor TEXT, own TEXT NOT NULL);
-- pinged_seq and pinged_at are kept for feeds made before the Steward stopped being pinged: nothing reads them.
CREATE TABLE IF NOT EXISTS cursors (
    session TEXT PRIMARY KEY, read_seq INTEGER NOT NULL, pinged_seq INTEGER NOT NULL, pinged_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS marks (session TEXT NOT NULL, repo TEXT NOT NULL, number INTEGER NOT NULL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class FeedError(Exception):
    """A request the feed can't serve; the message goes back to the caller."""


def clean(event) -> dict | None:
    """One event as it may be kept, or None. Every field is checked against a closed shape: nothing free-form gets in."""
    if not isinstance(event, dict):
        return None
    try:
        kind, repo, number, what = event["kind"], event["repo"], event["number"], event["what"]
        at, event_id = event["at"], event["id"]
        old, new = event.get("old") or "", event.get("new") or ""
        old_head, new_head = event.get("old_head") or "", event.get("new_head") or ""
        actor = event.get("actor")
    except KeyError:
        return None
    if kind not in _LINKS or what not in WHATS or not isinstance(repo, str) or not _REPO_RE.fullmatch(repo):
        return None
    if not isinstance(number, int) or isinstance(number, bool) or not 0 <= number <= MAX_NUMBER:
        return None
    if not isinstance(at, str) or not _TIME_RE.fullmatch(at):
        return None
    if not isinstance(event_id, str) or not _ID_RE.fullmatch(event_id):
        return None
    if (kind == "run") != (what == "run") or (what in _PR_ONLY and kind != "pr"):
        return None
    for value, allowed in zip((old, new), _VALUES[what]):
        if not isinstance(value, str) or not allowed.fullmatch(value):
            return None
    for head in (old_head, new_head):
        if not isinstance(head, str) or not _HEAD_RE.fullmatch(head):
            return None
    if actor is not None and (not isinstance(actor, str) or not _LOGIN_RE.fullmatch(actor)):
        return None
    return {"id": event_id, "kind": kind, "repo": repo, "number": number, "what": what, "at": at, "old": old, "new": new,
            "old_head": old_head, "new_head": new_head, "actor": actor}


def link(kind: str, repo: str, number: int) -> str:
    return f"https://github.com/{ORG}/{repo}/{_LINKS[kind]}/{number}"


def importance(row: dict) -> str:
    """high, normal or low. Only the order of the digest: nothing is left out for being low."""
    what, new = row["what"], row["new"]
    if what == "state" and new == "MERGED" or what == "head" or (what == "checks" and new == "failing"):
        return "high"
    if what == "run" and new in _FAILED_RUN or what == "review" and new == "CHANGES_REQUESTED":
        return "high"
    if what in ("labels", "comments"):
        return "low"
    return "normal"


def _phrase(row: dict) -> str:
    """A fixed vocabulary for the digest: nothing of the item goes into it."""
    what, new = row["what"], row["new"]
    if what == "state":
        return {"MERGED": "merged", "CLOSED": "closed", "OPEN": "reopened"}.get(new, "state changes")
    if what == "run":
        return "runs failed" if new in _FAILED_RUN else "runs finished"
    return {"opened": "opened", "head": "head changes", "review": "reviews", "checks": "check changes",
            "labels": "label changes", "comments": "commented items"}[what]


def target_of(argv) -> tuple[str, int] | None:
    """The repository and number a gh write names, if it names one: for marking a session's own changes."""
    if not isinstance(argv, list) or len(argv) < 3 or not all(isinstance(a, str) for a in argv):
        return None
    repo, number = None, None
    rest = argv[2:]
    for i, arg in enumerate(rest):
        if arg in ("-R", "--repo") and i + 1 < len(rest):
            name = rest[i + 1].removeprefix(f"{ORG}/")
            repo = name if _REPO_RE.fullmatch(name) else None
        elif (found := _URL_RE.fullmatch(arg)):
            repo, number = found["repo"], int(found["n"])
        elif _NUMBER.fullmatch(arg) and number is None and (i == 0 or not rest[i - 1].startswith("-")):
            number = int(arg)
    return (repo, number) if repo and number is not None else None


class Feed:
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
    def mark(self, session: str, repo: str, number: int) -> None:
        """A session wrote to this item: what changes in it soon after is that session's own doing, as far as it can tell."""
        with self.lock, self.db:
            now = self._clock()
            self.db.execute("DELETE FROM marks WHERE at < ?", (now - OWN_WINDOW,))
            self.db.execute("INSERT INTO marks (session, repo, number, at) VALUES (?, ?, ?, ?)", (session, repo, number, now))
            self.db.execute("DELETE FROM marks WHERE rowid IN (SELECT rowid FROM marks ORDER BY at DESC LIMIT -1 OFFSET ?)", (MAX_MARKS,))

    def record(self, events) -> tuple[int, int]:
        """(kept, refused). What isn't of the shape is refused whole, and what was seen before is kept once."""
        if not isinstance(events, list) or len(events) > MAX_BATCH:
            raise FeedError(f"send a list of at most {MAX_BATCH} events")
        kept = refused = 0
        with self.lock, self.db:
            now = self._clock()
            for raw in events:
                e = clean(raw)
                if e is None:
                    refused += 1
                    continue
                try:
                    own = [r["session"] for r in self.db.execute(
                        "SELECT DISTINCT session FROM marks WHERE repo = ? AND number = ? AND at >= ?", (e["repo"], e["number"], now - OWN_WINDOW))]
                    cursor = self.db.execute(
                        "INSERT OR IGNORE INTO events (key, at, recorded, kind, repo, number, what, old, new, old_head, new_head, actor, own) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (e["id"], e["at"], now, e["kind"], e["repo"], e["number"], e["what"], e["old"], e["new"],
                         e["old_head"], e["new_head"], e["actor"], json.dumps(sorted(own))))
                except (OverflowError, sqlite3.DataError, sqlite3.InterfaceError):
                    # One event SQLite can't take is that event's loss. If it failed the batch, the app would send the same oldest
                    # events again on every tick and nothing behind them would ever get in.
                    refused += 1
                    continue
                kept += cursor.rowcount
            self._prune(now)
        return kept, refused

    def _prune(self, now: float) -> None:
        newest = self.db.execute("SELECT max(seq) AS n FROM events").fetchone()["n"] or 0
        cutoff = max(0, newest - KEEP_ROWS)
        gone = self.db.execute("SELECT max(seq) AS n FROM events WHERE recorded < ? OR seq <= ?", (now - KEEP_SECONDS, cutoff)).fetchone()["n"]
        if gone:
            self.db.execute("DELETE FROM events WHERE seq <= ?", (gone,))
            self.db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('pruned_to', ?)", (str(gone),))

    # --- reading -------------------------------------------------------------------
    def newest(self) -> int:
        with self.lock:
            return self.db.execute("SELECT max(seq) AS n FROM events").fetchone()["n"] or 0

    def issued(self) -> int:
        """The highest seq ever handed out. Not max(seq): once every row is pruned that is 0, and a cursor is still past it."""
        with self.lock:
            row = self.db.execute("SELECT seq FROM sqlite_sequence WHERE name = 'events'").fetchone()
        return row["seq"] if row else 0

    def latest(self, kind: str, repo: str, number: int) -> dict:
        """What the feed last saw of one item: its state, and of a pull request whether its head moved and its checks and
        review since the newest head. What it hasn't seen since then is missing, not a guess."""
        with self.lock:
            rows = self.db.execute("SELECT what, new FROM events WHERE kind = ? AND repo = ? COLLATE NOCASE AND number = ? ORDER BY seq",
                                   (kind, repo, number)).fetchall()
        out: dict = {}
        for row in rows:
            what, new = row["what"], row["new"]
            if what in ("opened", "state") and new:
                out["state"] = new
            elif what == "head":
                out["head"] = True
                out.pop("checks", None)
                out.pop("review", None)
            elif what in ("checks", "review"):
                out[what] = new
        return out

    def repos(self) -> set[str]:
        with self.lock:
            return {r["repo"] for r in self.db.execute("SELECT DISTINCT repo FROM events")}

    def _pruned_to(self) -> int:
        row = self.db.execute("SELECT value FROM meta WHERE key = 'pruned_to'").fetchone()
        return int(row["value"]) if row else 0

    @staticmethod
    def _where(public: set[str] | None) -> tuple[str, list]:
        """None is every repository. Otherwise only these: the rest isn't counted, listed or hinted at."""
        if public is None:
            return "", []
        if not public:
            return " AND 0", []
        return f" AND repo IN ({','.join('?' * len(public))})", sorted(public)

    def _view(self, row: sqlite3.Row, session: str | None) -> dict:
        return {"id": row["seq"], "at": row["at"], "kind": row["kind"], "repo": row["repo"], "number": row["number"],
                "what": row["what"], "old": row["old"] or None, "new": row["new"] or None,
                "old_head": row["old_head"] or None, "new_head": row["new_head"] or None, "actor": row["actor"],
                "own": session is not None and session in json.loads(row["own"]),
                "link": link(row["kind"], row["repo"], row["number"]), "importance": importance(row)}

    def _start(self, session: str | None, cursor: int | None) -> int:
        if cursor is not None and cursor > self.issued():
            # One cursor past the end would be kept, as it only moves forward, and blind the reader to everything after it.
            raise FeedError("that cursor is past the newest change: use the cursor an answer gave, or none to go on from your own")
        if cursor is not None:
            return cursor
        kept = self.db.execute("SELECT read_seq FROM cursors WHERE session = ?", (session,)).fetchone() if session else None
        return kept["read_seq"] if kept else 0

    def changes(self, session: str | None, cursor: int | None, limit: int, public: set[str] | None,
                repo: str | None = None, number: int | None = None) -> dict:
        """What came after the cursor that this reader may see, in order, with the cursor to ask from next. A reader that
        is a session has its cursor kept: it only moves forward, so a Steward re-reading older changes loses nothing.

        Narrowed to a repository, or to one item of it (`repo` and `number`), the answer's cursor is for going on with that
        narrowed read, and the kept cursor doesn't move: the rest of what came after it is still unread."""
        limit = max(1, min(int(limit), MAX_READ))
        if number is not None and repo is None:
            raise FeedError("an item is named with its repository")
        with self.lock, self.db:
            start = self._start(session, cursor)
            where, args = self._where(public)
            if repo is not None:
                where, args = where + " AND repo = ? COLLATE NOCASE", [*args, repo]
            if number is not None:
                where, args = where + " AND number = ?", [*args, number]
            rows = self.db.execute(f"SELECT * FROM events WHERE seq > ?{where} ORDER BY seq LIMIT ?", (start, *args, limit + 1)).fetchall()
            more = len(rows) > limit
            rows = rows[:limit]
            # Past the rows it returned, or past everything when it saw them all: what it may not see has no place in the answer.
            last = rows[-1]["seq"] if rows else (start if more else max(start, self.newest()))
            gap = start < self._pruned_to()
            if session and repo is None:
                self._keep_cursor(session, last)
            changes = [self._view(r, session) for r in rows]
        order = {"high": 0, "normal": 1, "low": 2}
        changes.sort(key=lambda c: (order[c["importance"]], c["id"]))
        counts = Counter(c["what"] for c in changes)
        out = {"changes": changes, "cursor": str(last), "more": more, "counts": dict(counts), "gap": gap,
               "order": "most important first, then oldest first; the cursor covers all of them"}
        if repo is not None:
            out["narrowed"] = {"repo": repo, "number": number, "kept_cursor": "unchanged: read without repo or item, or a digest, to move it"}
        return out

    def digest(self, session: str | None, cursor: int | None, public: set[str] | None) -> dict:
        """One short line per repository of what came after the cursor that this reader may see: how many changes, how many
        of them important, how many items, and what kinds in the digest's fixed words; changes of the reader's own doing are
        only counted. A session's kept cursor moves past all of it, as a full read does; `from` is where it started, to read
        one repository's rows with a narrowed read from there."""
        with self.lock, self.db:
            start = self._start(session, cursor)
            where, args = self._where(public)
            rows = self.db.execute(f"SELECT * FROM events WHERE seq > ?{where} ORDER BY seq", (start, *args)).fetchall()
            last = max(start, self.newest())
            gap = start < self._pruned_to()
            if session:
                self._keep_cursor(session, last)
        lines: dict[str, dict] = {}
        for row in rows:
            line = lines.setdefault(row["repo"], {"repo": row["repo"], "changes": 0, "important": 0, "own": 0, "items": set(), "what": Counter()})
            line["changes"] += 1
            line["items"].add((row["kind"], row["number"]))
            if session is not None and session in json.loads(row["own"]):
                line["own"] += 1
                continue
            line["important"] += importance(row) == "high"
            line["what"][_phrase(row)] += 1
        digest = [{**line, "items": len(line["items"]), "what": dict(sorted(line["what"].items(), key=lambda p: (-p[1], p[0])))}
                  for line in sorted(lines.values(), key=lambda x: (-x["important"], -x["changes"], x["repo"]))]
        return {"digest": digest, "cursor": str(last), "from": str(start), "gap": gap,
                "order": "repositories with the most important changes first; read one with changes_since, its repo and cursor = from"}

    def rows_after(self, seq: int, session: str) -> list[dict]:
        """What was recorded after seq, as `session` would read it (its own doing marked), without moving any cursor."""
        with self.lock:
            rows = self.db.execute("SELECT * FROM events WHERE seq > ? ORDER BY seq LIMIT ?", (seq, MAX_BATCH)).fetchall()
        return [self._view(r, session) for r in rows]

    def _keep_cursor(self, session: str, seq: int) -> None:
        self.db.execute(
            "INSERT INTO cursors (session, read_seq, pinged_seq, pinged_at) VALUES (?, ?, ?, 0) "
            "ON CONFLICT(session) DO UPDATE SET read_seq = max(read_seq, excluded.read_seq)", (session, seq, seq))

    def known(self, session: str) -> bool:
        with self.lock:
            return self.db.execute("SELECT 1 FROM cursors WHERE session = ?", (session,)).fetchone() is not None

    def begin(self, session: str) -> None:
        """A Steward seen for the first time starts from now: what happened before it existed isn't news to it."""
        with self.lock, self.db:
            newest = self.issued()
            self.db.execute("INSERT OR IGNORE INTO cursors (session, read_seq, pinged_seq, pinged_at) VALUES (?, ?, ?, 0)",
                            (session, newest, newest))


def parse_cursor(value) -> int | None:
    if value is None or value == "":
        return None
    # ASCII digits only: str.isdigit() takes "²" too, which int() then refuses.
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not re.fullmatch(r"[0-9]{1,18}", str(value)):
        raise FeedError("a cursor is the number a previous answer gave")
    return int(value)

