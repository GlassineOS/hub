# SPDX-License-Identifier: GPL-2.0-or-later
"""What the hub knows about the organization's work: issues, pull requests and runs.

One row per thing, whatever the number of times it was seen, in its own SQLite file. Views
and agent tools read here. Passages of issues and pull requests carry embeddings, so they can
be searched by meaning. This has nothing to do with the docs search and shares no data with it.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path

import numpy as np

CHUNK = 1000
OVERLAP = 120
MAX_PASSAGES = 40
FUSION = 60  # reciprocal rank fusion's usual constant
VERSION = 1  # of this file. It's a cache: an older one is dropped, not converted
KEEP_ANSWERS = 30 * 86400
KEEP_RUNS = 90 * 86400

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    kind TEXT NOT NULL, repo TEXT NOT NULL, number INTEGER NOT NULL,
    state TEXT, updated_at TEXT NOT NULL, data TEXT NOT NULL,
    PRIMARY KEY (kind, repo, number));
CREATE TABLE IF NOT EXISTS comments (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, repo TEXT NOT NULL, number INTEGER NOT NULL,
    created_at TEXT, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS comments_of ON comments (kind, repo, number);
CREATE TABLE IF NOT EXISTS passages (
    kind TEXT NOT NULL, repo TEXT NOT NULL, number INTEGER NOT NULL, seq INTEGER NOT NULL,
    text TEXT NOT NULL, hash TEXT NOT NULL,
    PRIMARY KEY (kind, repo, number, seq));
CREATE TABLE IF NOT EXISTS vectors (
    hash TEXT NOT NULL, model TEXT NOT NULL, vector BLOB NOT NULL,
    PRIMARY KEY (hash, model));
CREATE TABLE IF NOT EXISTS answers (key TEXT PRIMARY KEY, stamp TEXT, value TEXT NOT NULL, kept_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sync (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL);
"""
# Changes waiting to be sent to hubd are rows of `outbox`, written in the transaction of the upsert that saw them, so a tick that
# fails afterwards or an app that restarts loses none. This file is a cache: a VERSION change drops the outbox with the rest, and
# what was waiting in it is lost, so a bump should wait for it to be empty (`feed_waiting` in the work status says).
MAX_EVENTS = 5000  # waiting to be sent to hubd: a feed that never drains mustn't grow this without end. The oldest go, and are counted.
FRESH_RUN = 2 * 86400  # a run first seen finishing longer ago than this isn't news: it's one the window returns again after a prune
_DECIDED = {"SUCCESS": "passing", "FAILURE": "failing", "ERROR": "failing", "PENDING": "pending", "EXPECTED": "pending"}


_PART_OF_RE = re.compile(r"^Part of\s+(?:https://github\.com/)?(?:GlassineOS/)?([A-Za-z0-9._-]+)?(?:#|/issues/)([1-9][0-9]{0,9})\b", re.M | re.I)


def part_of(body, repo=None) -> str | None:
    """The item a body names on a line that starts "Part of", as repo#N (#N: of the body's own repository, given as repo):
    the line the hub's own filing writes. A quoted line ("> Part of …") doesn't start with it, so it doesn't count."""
    m = _PART_OF_RE.search(body) if isinstance(body, str) else None
    if not m or not (m.group(1) or repo):
        return None
    return f"{m.group(1) or repo}#{m.group(2)}"


def normalize(node: dict) -> tuple[str, dict, list[dict], int]:
    """A GraphQL issue or pull request as (kind, row, comments, comment total): rows look like gh's."""
    row = {k: v for k, v in node.items() if k not in ("__typename", "repository", "comments", "commits", "labels", "assignees")}
    row["repo"] = node["repository"]["name"]
    row["labels"] = (node.get("labels") or {}).get("nodes") or []
    row["assignees"] = (node.get("assignees") or {}).get("nodes") or []
    comments = node.get("comments") or {}
    kind = "pr" if node["__typename"] == "PullRequest" else "issue"
    if kind == "pr":
        commits = (node.get("commits") or {}).get("nodes") or []
        rollup = commits[-1]["commit"].get("statusCheckRollup") if commits else None
        row["checks"] = _DECIDED.get((rollup or {}).get("state"), "none")
    else:
        row["comments"] = comments.get("totalCount") or 0
    return kind, row, comments.get("nodes") or [], comments.get("totalCount") or 0


def run_row(repo: str, run: dict) -> dict:
    """A run from the REST API, shaped like `gh run list --json`."""
    return {"repo": repo, "databaseId": run["id"], "displayTitle": run.get("display_title") or run.get("name") or "",
            "workflowName": run.get("name") or "", "status": run.get("status"), "conclusion": run.get("conclusion"),
            "event": run.get("event"), "headBranch": run.get("head_branch"), "headSha": run.get("head_sha"),
            "createdAt": run.get("created_at"), "updatedAt": run.get("updated_at"), "url": run.get("html_url")}


def _login(who) -> str | None:
    return (who or {}).get("login") if isinstance(who, dict) else None


def item_events(kind: str, old: dict | None, new: dict, old_comment: tuple | None, comments: list[dict]) -> list[dict]:
    """The facts of what changed between two rows of one issue or pull request, for hubd's feed. Facts only: states, head
    commits, counts and logins. A title, a body or a comment's text never goes in, as they can be an outsider's."""
    base = {"kind": kind, "repo": new["repo"], "number": new["number"], "at": new["updatedAt"]}
    heads = {}
    if kind == "pr":
        heads = {"old_head": (old or {}).get("headRefOid") or "", "new_head": new.get("headRefOid") or ""}
    if old is None:
        return [{**base, "what": "opened", "new": new["state"], "actor": _login(new.get("author")), **heads}]
    out = []
    if old["state"] != new["state"]:
        out.append({**base, "what": "state", "old": old["state"], "new": new["state"], **heads})
    if kind == "pr":
        if heads["old_head"] != heads["new_head"]:
            out.append({**base, "what": "head", **heads})
        for what, field in (("review", "reviewDecision"), ("checks", "checks")):
            if old.get(field) != new.get(field):
                out.append({**base, "what": what, "old": old.get(field) or "", "new": new.get(field) or ""})
    if {x["name"] for x in old.get("labels") or []} != {x["name"] for x in new.get("labels") or []}:
        out.append({**base, "what": "labels", "old": str(len(old.get("labels") or [])), "new": str(len(new.get("labels") or []))})
    newest = max(comments, key=lambda c: c.get("createdAt") or "", default=None)
    # No comment kept before is "": the first one on an item is a new one. (An item seen for the first time returned above.)
    if newest and (newest.get("createdAt") or "") > ((old_comment or ("", ""))[1] or ""):
        out.append({**base, "what": "comments", "actor": _login(newest.get("author"))})
    return out


def run_events(old: dict | None, new: dict, now: float) -> list[dict]:
    """A run that has finished: its conclusion, once. One still going says nothing, and neither does one this hub sees for
    the first time that finished long ago: a pruned run the latest-runs window returns again isn't a new result."""
    if new.get("status") != "completed" or (old is not None and old.get("status") == "completed"):
        return []
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    if old is None and new.get("updatedAt") and new["updatedAt"] < time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - FRESH_RUN)):
        return []
    return [{"kind": "run", "repo": new["repo"], "number": new["databaseId"], "what": "run", "at": new.get("updatedAt") or stamp,
             "old": (old or {}).get("status") or "", "new": new.get("conclusion") or ""}]


def chunks(text: str) -> list[str]:
    """Pieces of about CHUNK characters, overlapping, broken at a paragraph or space where one is near."""
    text = (text or "").strip()
    out = []
    while len(text) > CHUNK:
        window = text[:CHUNK]
        cut = max(window.rfind("\n\n"), window.rfind(". "), window.rfind(" "))
        cut = cut if cut > CHUNK // 2 else CHUNK
        out.append(text[:cut].strip())
        text = text[max(cut - OVERLAP, 1):].strip()
    if text:
        out.append(text)
    return out


class WorkStore:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        if self.db.execute("PRAGMA user_version").fetchone()[0] != VERSION:
            for (table,) in self.db.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
                self.db.execute(f'DROP TABLE "{table}"')
        self.db.executescript(_SCHEMA)
        self.db.execute(f"PRAGMA user_version = {VERSION}")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.lock = threading.RLock()
        self._loaded = None  # the passages with vectors, in memory until they change
        self.clock = time.time
        self.emit = True  # off for the first pass: everything is new then, and that's no change
        self._generation = 0

    # --- small answers ------------------------------------------------------
    def get(self, key: str) -> str | None:
        with self.lock:
            row = self.db.execute("SELECT value FROM sync WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def put(self, key: str, value: str) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO sync (key, value) VALUES (?, ?)", (key, value))

    def answer(self, key: str, stamp: str):
        """A kept answer of gh, if it was kept for this stamp: anything else in the stamp means stale."""
        with self.lock:
            row = self.db.execute("SELECT value FROM answers WHERE key = ? AND stamp = ?", (key, stamp)).fetchone()
        return json.loads(row["value"]) if row else None

    def keep(self, key: str, stamp: str, value) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO answers (key, stamp, value, kept_at) VALUES (?, ?, ?, ?)",
                            (key, stamp, json.dumps(value), time.time()))

    def forget(self, key: str) -> None:
        with self.lock, self.db:
            self.db.execute("DELETE FROM answers WHERE key = ?", (key,))

    # --- issues and pull requests -------------------------------------------
    def upsert(self, node: dict) -> bool:
        """Stores one issue or pull request. True if it's new or differs from what was here."""
        kind, row, comments, total = normalize(node)
        key = (kind, row["repo"], row["number"])
        data = json.dumps(row, sort_keys=True)
        with self.lock, self.db:
            old = self.db.execute("SELECT data FROM items WHERE kind = ? AND repo = ? AND number = ?", key).fetchone()
            if self.emit and (old is None or old["data"] != data):
                last = self.db.execute("SELECT id, created_at FROM comments WHERE kind = ? AND repo = ? AND number = ? "
                                       "ORDER BY created_at DESC LIMIT 1", key).fetchone()
                self._note(item_events(kind, json.loads(old["data"]) if old else None, row, tuple(last) if last else ("", ""), comments))
            self.db.execute("INSERT OR REPLACE INTO items (kind, repo, number, state, updated_at, data) VALUES (?, ?, ?, ?, ?, ?)",
                            (*key, row["state"], row["updatedAt"], data))
            if total <= len(comments):  # all of them: this also drops the deleted ones
                self.db.execute("DELETE FROM comments WHERE kind = ? AND repo = ? AND number = ?", key)
            for c in comments:
                self.db.execute("INSERT OR REPLACE INTO comments (id, kind, repo, number, created_at, data) VALUES (?, ?, ?, ?, ?, ?)",
                                (c["id"], *key, c.get("createdAt"), json.dumps(c)))
            self._set_passages(key, row)
        return old is None or old["data"] != data

    def _note(self, events: list[dict]) -> None:
        """Into the outbox, inside the transaction of the upsert that saw them (the caller holds it open)."""
        for event in events:
            self.db.execute("INSERT INTO outbox (event) VALUES (?)", (json.dumps(event),))
        over = self.db.execute("SELECT count(*) FROM outbox").fetchone()[0] - MAX_EVENTS
        if over > 0:
            self.db.execute("DELETE FROM outbox WHERE id IN (SELECT id FROM outbox ORDER BY id LIMIT ?)", (over,))
            self._count("feed_dropped", over)

    def _count(self, key: str, n: int) -> None:
        """A running total in the sync table, kept in whatever transaction is open."""
        self.db.execute("INSERT INTO sync (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + ?",
                        (key, str(n), n))

    def event_id(self, row_id: int) -> str:
        """Names one waiting change for hubd's feed, the same on every retry. The store's own random name is in it: this file is
        dropped on a version change and its row numbers start again, and those must not meet an older change's."""
        with self.lock:
            origin = self.get("feed_origin")
            if not origin:
                origin = secrets.token_hex(8)
                self.put("feed_origin", origin)
        return f"{origin}-{row_id}"

    def waiting(self, limit: int) -> list[tuple[int, dict]]:
        """The oldest changes not yet sent, with their ids. One that doesn't read back as a change is dropped, and counted."""
        with self.lock, self.db:
            rows = self.db.execute("SELECT id, event FROM outbox ORDER BY id LIMIT ?", (limit,)).fetchall()
            out, bad = [], []
            for r in rows:
                try:
                    event = json.loads(r["event"])
                except ValueError:
                    event = None
                if isinstance(event, dict):
                    out.append((r["id"], event))
                else:
                    bad.append(r["id"])
            if bad:
                self.db.executemany("DELETE FROM outbox WHERE id = ?", [(i,) for i in bad])
                self._count("feed_dropped", len(bad))
        return out

    def sent(self, ids: list[int], refused: int = 0) -> None:
        with self.lock, self.db:
            self.db.executemany("DELETE FROM outbox WHERE id = ?", [(i,) for i in ids])
            if refused:
                self._count("feed_refused", refused)

    def outbox_size(self) -> int:
        with self.lock:
            return self.db.execute("SELECT count(*) FROM outbox").fetchone()[0]

    def _set_passages(self, key: tuple, row: dict) -> None:
        rows = self.db.execute("SELECT data FROM comments WHERE kind = ? AND repo = ? AND number = ? ORDER BY created_at", key).fetchall()
        head = f"{key[1]}#{key[2]} {row['title']}\n"
        body = chunks(row.get("body") or "") or [""]
        said = [p for c in rows for p in chunks(json.loads(c["data"]).get("body") or "")]
        # On a long thread: the start of the body, and the newest of what was said.
        body = body[:max(MAX_PASSAGES // 2, MAX_PASSAGES - len(said))]
        said = said[-(MAX_PASSAGES - len(body)):]
        texts = [head + p for p in body + said]
        wanted = [(hashlib.sha256(t.encode()).hexdigest(), t) for t in texts]
        have = self.db.execute("SELECT hash FROM passages WHERE kind = ? AND repo = ? AND number = ? ORDER BY seq", key).fetchall()
        if [r["hash"] for r in have] == [h for h, _ in wanted]:
            return
        self.db.execute("DELETE FROM passages WHERE kind = ? AND repo = ? AND number = ?", key)
        for seq, (digest, text) in enumerate(wanted):
            self.db.execute("INSERT INTO passages (kind, repo, number, seq, text, hash) VALUES (?, ?, ?, ?, ?, ?)",
                            (*key, seq, text, digest))
        self._generation += 1

    def remove_missing(self, seen: set[tuple]) -> int:
        """After a complete pass: drops issues and pull requests GitHub no longer returned."""
        with self.lock, self.db:
            rows = self.db.execute("SELECT kind, repo, number FROM items WHERE kind IN ('issue', 'pr')").fetchall()
            gone = [tuple(r) for r in rows if tuple(r) not in seen]
            for key in gone:
                for table in ("items", "comments", "passages"):
                    self.db.execute(f"DELETE FROM {table} WHERE kind = ? AND repo = ? AND number = ?", key)
                # The kept answers hold the same text.
                for name in (key[0], "diff") if key[0] == "pr" else (key[0],):
                    self.db.execute("DELETE FROM answers WHERE key = ?", (f"{name}/{key[1]}/{key[2]}",))
            self.db.execute("DELETE FROM vectors WHERE hash NOT IN (SELECT hash FROM passages)")
            if gone:
                self._generation += 1
        return len(gone)

    def prune(self, now: float) -> None:
        """Old answers and runs, or this file only ever grows."""
        cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - KEEP_RUNS))
        with self.lock, self.db:
            self.db.execute("DELETE FROM answers WHERE kept_at < ?", (now - KEEP_ANSWERS,))
            self.db.execute("DELETE FROM items WHERE kind = 'run' AND updated_at < ?", (cutoff,))

    def item(self, kind: str, repo: str, number: int) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT data FROM items WHERE kind = ? AND repo = ? AND number = ?", (kind, repo, number)).fetchone()
        return json.loads(row["data"]) if row else None

    def comments(self, kind: str, repo: str, number: int) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT data FROM comments WHERE kind = ? AND repo = ? AND number = ? ORDER BY created_at",
                                   (kind, repo, number)).fetchall()
        return [json.loads(r["data"]) for r in rows]

    def _rows(self, kind: str, repo: str | None) -> list[dict]:
        sql, args = "SELECT data FROM items WHERE kind = ?", [kind]
        if repo:
            sql, args = sql + " AND repo = ?", [kind, repo]
        with self.lock:
            return [json.loads(r["data"]) for r in self.db.execute(sql, args).fetchall()]

    def latest_activity(self) -> dict[str, str]:
        """Each repository's newest change the store has seen: an issue, a pull request or a run (007 FR-007)."""
        with self.lock:
            rows = self.db.execute("SELECT repo, max(updated_at) AS at FROM items GROUP BY repo").fetchall()
        return {r["repo"]: r["at"] for r in rows if r["at"]}

    def failing_workflows(self, branches: dict[str, str]) -> dict[str, int]:
        """How many workflows' newest finished run on each repository's default branch failed (007 FR-004)."""
        newest: dict[tuple[str, str], dict] = {}
        for run in self._rows("run", None):
            if run.get("status") != "completed" or run.get("headBranch") != branches.get(run["repo"]):
                continue
            key = (run["repo"], run.get("workflowName") or "")
            if key not in newest or (run.get("createdAt") or "") > (newest[key].get("createdAt") or ""):
                newest[key] = run
        out = {repo: 0 for repo in branches}
        for (repo, _workflow), run in newest.items():
            out[repo] = out.get(repo, 0) + (run.get("conclusion") in ("failure", "timed_out", "startup_failure"))
        return out

    def open_pr_checks(self) -> dict[str, int]:
        """Open pull requests whose checks fail, by repository."""
        out: dict[str, int] = {}
        for pr in self._rows("pr", None):
            if pr.get("state") == "OPEN" and pr.get("checks") == "failing":
                out[pr["repo"]] = out.get(pr["repo"], 0) + 1
        return out

    def issues(self, repo=None, state="open", label=None, assignee=None, search=None, limit=50) -> list[dict]:
        rows = self._listed("issue", repo, state, search)
        if label:
            rows = [r for r in rows if any(x["name"] == label for x in r["labels"])]
        if assignee == "none":
            rows = [r for r in rows if not r["assignees"]]
        elif assignee:
            rows = [r for r in rows if any(x["login"] == assignee for x in r["assignees"])]
        return rows[:limit]

    def prs(self, repo=None, state="open", limit=50) -> list[dict]:
        return self._listed("pr", repo, state, None)[:limit]

    def with_bodies(self, kind: str, state: str) -> list[dict]:
        """Rows with their text, which the lists leave out, for the one view that reads lines in it."""
        return [r for r in self._rows(kind, None) if r["state"] == state]

    def _listed(self, kind, repo, state, search) -> list[dict]:
        rows = self._rows(kind, repo)
        if state != "all":
            rows = [r for r in rows if r["state"] == state.upper()]
        if search:
            words = search.lower().split()
            rows = [r for r in rows if all(w in f"{r['title']} {r.get('body') or ''}".lower() for w in words)]
        rows.sort(key=lambda r: r["updatedAt"], reverse=True)
        # The body stays out of a list; its "Part of" line is what a row shows of it (006 FR-006).
        return [{**{k: v for k, v in r.items() if k != "body"}, "part_of": part_of(r.get("body"), r.get("repo"))} for r in rows]

    def counts(self) -> dict:
        with self.lock:
            rows = self.db.execute("SELECT kind, count(*) AS n FROM items GROUP BY kind").fetchall()
            passages = self.db.execute("SELECT count(*) AS n FROM passages").fetchone()["n"]
        return {**{r["kind"]: r["n"] for r in rows}, "passages": passages}

    # --- runs -----------------------------------------------------------------
    def upsert_run(self, row: dict) -> bool:
        key = ("run", row["repo"], row["databaseId"])
        data = json.dumps(row, sort_keys=True)
        with self.lock, self.db:
            old = self.db.execute("SELECT data FROM items WHERE kind = ? AND repo = ? AND number = ?", key).fetchone()
            if self.emit and (old is None or old["data"] != data):
                self._note(run_events(json.loads(old["data"]) if old else None, row, self.clock()))
            self.db.execute("INSERT OR REPLACE INTO items (kind, repo, number, state, updated_at, data) VALUES (?, ?, ?, ?, ?, ?)",
                            (*key, row["conclusion"] or row["status"], row["updatedAt"] or "", data))
        return old is None or old["data"] != data

    def runs(self, repo=None, status=None, workflow=None, branch=None, limit=20) -> list[dict]:
        rows = self._rows("run", repo)
        if status:
            rows = [r for r in rows if status in (r["status"], r["conclusion"])]
        if workflow:
            rows = [r for r in rows if r["workflowName"] == workflow]
        if branch:
            rows = [r for r in rows if r["headBranch"] == branch]
        rows.sort(key=lambda r: r["createdAt"] or "", reverse=True)
        return rows[:limit]

    # --- by meaning -------------------------------------------------------------
    def unembedded(self, model: str, limit: int = 256) -> list[tuple[str, str]]:
        with self.lock:
            rows = self.db.execute(
                "SELECT DISTINCT p.hash, p.text FROM passages p LEFT JOIN vectors v ON v.hash = p.hash AND v.model = ? "
                "WHERE v.hash IS NULL LIMIT ?", (model, limit)).fetchall()
        return [(r["hash"], r["text"]) for r in rows]

    def add_vectors(self, model: str, digests: list[str], vectors: np.ndarray) -> None:
        with self.lock, self.db:
            for digest, vector in zip(digests, np.asarray(vectors, dtype=np.float32)):
                self.db.execute("INSERT OR REPLACE INTO vectors (hash, model, vector) VALUES (?, ?, ?)",
                                (digest, model, vector.tobytes()))
            self._generation += 1

    def _passages(self, model: str | None) -> tuple[list, np.ndarray | None]:
        with self.lock:
            if self._loaded and self._loaded[0] == (self._generation, model):
                return self._loaded[1:]
            rows = self.db.execute(
                "SELECT p.kind, p.repo, p.number, p.text, v.vector FROM passages p "
                "LEFT JOIN vectors v ON v.hash = p.hash AND v.model = ?", (model,)).fetchall()
            meta = [(r["kind"], r["repo"], r["number"], r["text"]) for r in rows]
            vectors = None
            present = [r["vector"] for r in rows if r["vector"] is not None]
            if present:
                width = len(present[0]) // 4
                vectors = np.zeros((len(rows), width), dtype=np.float32)
                for i, r in enumerate(rows):
                    if r["vector"] is not None:
                        vectors[i] = np.frombuffer(r["vector"], dtype=np.float32)
            self._loaded = ((self._generation, model), meta, vectors)
            return meta, vectors

    def search(self, query: str, query_vector=None, model: str | None = None, kind=None, repo=None, state=None, k=8,
               only_repos=None) -> list[dict]:
        """Best passage per item, ranking by meaning and by the words of the query together."""
        meta, vectors = self._passages(model)
        wanted = [i for i, (kd, rp, _n, _t) in enumerate(meta) if (not kind or kd == kind) and (not repo or rp == repo)
                  and (only_repos is None or rp in only_repos)]
        if not wanted:
            return []
        # A long word anywhere, a short one ("CI") only as a word: it's inside too many others.
        words = [w if len(w) > 2 else re.compile(rf"\b{w}\b") for w in re.findall(r"\w+", query.lower()) if len(w) > 1]
        found = lambda w, text: w in text if isinstance(w, str) else bool(w.search(text))
        keyword = np.array([sum(found(w, meta[i][3].lower()) for w in words) / max(len(words), 1) for i in wanted])
        fused = _ranks(keyword, keyword > 0)
        meaning = None
        if query_vector is not None and vectors is not None:
            meaning = vectors[wanted] @ np.asarray(query_vector, dtype=np.float32)
            fused = fused + _ranks(meaning, meaning != 0)
        best: dict[tuple, int] = {}
        for pos, i in enumerate(wanted):
            key = meta[i][:3]
            if fused[pos] > 0 and (key not in best or fused[pos] > fused[best[key]]):
                best[key] = pos
        results = []
        for key, pos in sorted(best.items(), key=lambda x: -fused[x[1]]):
            row = self.item(*key)
            if row is None or (state and state != "all" and row["state"] != state.upper()):
                continue
            text = meta[wanted[pos]][3].split("\n", 1)[-1]
            results.append({"kind": key[0], "repo": key[1], "number": key[2], "title": row["title"], "state": row["state"],
                            "url": row["url"], "updatedAt": row["updatedAt"], "passage": text[:400],
                            "meaning": round(float(meaning[pos]), 3) if meaning is not None else None,
                            "words": round(float(keyword[pos]), 3),
                            "row": {k: v for k, v in row.items() if k != "body"}})
            if len(results) >= k:
                break
        return results


def _ranks(scores: np.ndarray, usable: np.ndarray) -> np.ndarray:
    """Reciprocal ranks: 1/(FUSION + rank), 0 for what didn't match at all."""
    order = np.argsort(-scores, kind="stable")
    out = np.zeros(len(scores))
    for rank, i in enumerate(order):
        if usable[i]:
            out[i] = 1.0 / (FUSION + rank + 1)
    return out
