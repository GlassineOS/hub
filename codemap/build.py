# SPDX-License-Identifier: GPL-2.0-or-later
"""Build one repository's map from a frozen tree, as one SQLite file that replaces the last one only when it's complete.

It reads the tree through git, by object, so a link in a repository can't lead a read anywhere else and only what's
committed is mapped. A file whose blob the last map already read is copied from it rather than parsed again.
hubd runs this in a sandbox: `python -P -m codemap.build TREE OUT [--previous MAP]`. Nothing here talks to a network.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.parse

from .extract import EXTRACTOR, LANGUAGES, extract, language_of, needs_a_look, suffix

MAX_FILE = 2_000_000  # bytes: larger ones are generated tables, not code to find your way in, and the map says how many
MAX_FILES = 20_000  # to read in one repository: past this it's refused rather than taking the host's memory and hours of its time
_GIT_ENV = {"GIT_NO_LAZY_FETCH": "1", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0"}

SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT) WITHOUT ROWID;
CREATE TABLE files(id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, blob TEXT NOT NULL, language TEXT NOT NULL, lines INTEGER NOT NULL, errors INTEGER NOT NULL, score REAL NOT NULL DEFAULT 0);
CREATE TABLE names(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE defs(name_id INTEGER NOT NULL, file_id INTEGER NOT NULL, kind TEXT NOT NULL, line INTEGER NOT NULL, end_line INTEGER NOT NULL);
CREATE TABLE refs(name_id INTEGER NOT NULL, file_id INTEGER NOT NULL, count INTEGER NOT NULL, lines TEXT NOT NULL, PRIMARY KEY(name_id, file_id)) WITHOUT ROWID;
CREATE TABLE strings(value TEXT NOT NULL, shape TEXT NOT NULL, file_id INTEGER NOT NULL, line INTEGER NOT NULL, role TEXT NOT NULL, constant TEXT, function TEXT, call TEXT, access TEXT);
CREATE TABLE flows(name_id INTEGER NOT NULL, file_id INTEGER NOT NULL, line INTEGER NOT NULL, function TEXT, call TEXT, access TEXT NOT NULL);
CREATE TABLE symbols(name_id INTEGER PRIMARY KEY, def_files INTEGER NOT NULL, used_files INTEGER NOT NULL, uses INTEGER NOT NULL);
CREATE TABLE uncovered(suffix TEXT PRIMARY KEY, files INTEGER NOT NULL) WITHOUT ROWID;
"""
INDEXES = """
CREATE INDEX defs_by_name ON defs(name_id);
CREATE INDEX defs_by_file ON defs(file_id);
CREATE INDEX strings_by_value ON strings(value);
CREATE INDEX strings_by_file ON strings(file_id);
CREATE INDEX flows_by_name ON flows(name_id);
CREATE INDEX files_by_score ON files(score DESC);
"""


def _git(tree: str, *args: str) -> bytes:
    return subprocess.run(["git", "-C", tree, *args], check=True, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, env={**os.environ, **_GIT_ENV}).stdout


class _Blobs:
    """A long-running `git cat-file --batch`, as starting git for each file is most of the time on a large tree."""

    def __init__(self, tree: str):
        self.proc = subprocess.Popen(["git", "-C", tree, "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env={**os.environ, **_GIT_ENV})

    def read(self, sha: str) -> bytes | None:
        self.proc.stdin.write(sha.encode() + b"\n")
        self.proc.stdin.flush()
        header = self.proc.stdout.readline().split()
        if len(header) != 3:  # "<sha> missing"
            return None
        data = self.proc.stdout.read(int(header[2]))
        self.proc.stdout.read(1)
        return data

    def close(self) -> None:
        self.proc.stdin.close()
        self.proc.wait()


def _entries(tree: str) -> list[tuple[str, str, int]]:
    """(path, blob, size) of each regular file at HEAD. No links and no submodules."""
    found = []
    for row in _git(tree, "ls-tree", "-r", "-z", "-l", "HEAD").split(b"\0"):
        if not row:
            continue
        head, _tab, path = row.partition(b"\t")
        mode, kind, sha, size = head.split()
        if kind == b"blob" and mode != b"120000":
            found.append((path.decode("utf-8", "backslashreplace"), sha.decode(), int(size)))
    return found


def _classify(tree: str, entries: list[tuple[str, str, int]]) -> tuple[list[tuple[str, str, str]], dict[str, int], int]:
    """What to read, what the map doesn't cover by suffix, and how many files are too large."""
    covered, uncovered, too_large = [], {}, 0
    blobs = None
    for path, sha, size in entries:
        language = language_of(path)
        if language is None and needs_a_look(path) and 0 < size <= MAX_FILE:
            blobs = blobs or _Blobs(tree)
            language = language_of(path, (blobs.read(sha) or b"")[:200])
        if language is None:
            uncovered[suffix(path)] = uncovered.get(suffix(path), 0) + 1
        elif size > MAX_FILE:
            too_large += 1
        else:
            covered.append((path, sha, language))
    if blobs:
        blobs.close()
    return covered, uncovered, too_large


class _Writer:
    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.names = {name: i for i, name in db.execute("SELECT id, name FROM names")}
        self.next = max(self.names.values(), default=0) + 1

    def name(self, name: str) -> int:
        found = self.names.get(name)
        if found is None:
            found = self.names[name] = self.next
            self.next += 1
            self.db.execute("INSERT INTO names(id, name) VALUES (?, ?)", (found, name))
        return found

    def file(self, path: str, sha: str, language: str, facts) -> None:
        defs, refs, strings, flows = facts.defs, facts.refs, facts.strings, facts.flows
        file_id = self.db.execute("INSERT INTO files(path, blob, language, lines, errors) VALUES (?, ?, ?, ?, ?)", (path, sha, language, facts.lines, int(facts.errors))).lastrowid
        self.db.executemany("INSERT INTO defs VALUES (?, ?, ?, ?, ?)", [(self.name(n), file_id, kind, line, end) for n, kind, line, end in defs])
        self.db.executemany("INSERT INTO refs VALUES (?, ?, ?, ?)", [(self.name(n), file_id, count, ",".join(map(str, sorted(lines_of)))) for n, (count, lines_of) in refs.items()])
        self.db.executemany("INSERT INTO strings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [(value, shape, file_id, line, role, constant, function, call, access)
                                                                                       for value, shape, line, role, constant, function, call, access in strings])
        self.db.executemany("INSERT INTO flows VALUES (?, ?, ?, ?, ?, ?)", [(self.name(n), file_id, line, function, call, access) for n, line, function, call, access in flows])


def _carry(db: sqlite3.Connection, previous: str, covered: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """Copy what the last map knows about any blob still here, and return what's left to read. Names keep their ids.
    A last map that can't be read is only a slower build."""
    attached = False
    try:
        db.execute("ATTACH DATABASE ? AS old", (f"file:{urllib.parse.quote(previous)}?mode=ro&immutable=1",))
        attached = True
        if db.execute("SELECT value FROM old.meta WHERE key='extractor'").fetchone() != (str(EXTRACTOR),):
            return covered
        known = {(sha, language): file_id for file_id, sha, language in db.execute("SELECT id, blob, language FROM old.files")}
        db.execute("INSERT INTO names SELECT id, name FROM old.names")
        db.execute("CREATE TEMP TABLE carried(old_id INTEGER NOT NULL, new_id INTEGER NOT NULL)")
        left = []
        for path, sha, language in covered:
            old_id = known.get((sha, language))
            if old_id is None:
                left.append((path, sha, language))
                continue
            new_id = db.execute("INSERT INTO files(path, blob, language, lines, errors) SELECT ?, blob, language, lines, errors FROM old.files WHERE id=?", (path, old_id)).lastrowid
            db.execute("INSERT INTO carried VALUES (?, ?)", (old_id, new_id))
        for table, columns in (("defs", "name_id, c.new_id, kind, line, end_line"), ("refs", "name_id, c.new_id, count, lines"),
                               ("strings", "value, shape, c.new_id, line, role, constant, function, call, access"), ("flows", "name_id, c.new_id, line, function, call, access")):
            db.execute(f"INSERT INTO {table} SELECT {columns} FROM old.{table} t JOIN carried c ON t.file_id = c.old_id")
        return left
    except sqlite3.DatabaseError as e:
        print(f"the last map couldn't be read, so everything is read again: {e}", file=sys.stderr)
        db.rollback()
        for table in ("defs", "refs", "strings", "flows", "files", "names"):
            db.execute(f"DELETE FROM {table}")
        return covered
    finally:
        db.commit()
        db.execute("DROP TABLE IF EXISTS temp.carried")
        if attached:
            db.execute("DETACH DATABASE old")


def _rank(db: sqlite3.Connection) -> None:
    """What's most used: by how many other files name it, shared between everything that has that name. Then files by what they define."""
    db.executescript("""
        INSERT INTO symbols(name_id, def_files, used_files, uses)
        SELECT d.name_id, d.def_files, COALESCE(u.files, 0), COALESCE(u.uses, 0)
        FROM (SELECT name_id, COUNT(DISTINCT file_id) AS def_files FROM defs GROUP BY name_id) d
        LEFT JOIN (SELECT r.name_id, COUNT(*) AS files, SUM(r.count) AS uses FROM refs r
                   WHERE r.name_id IN (SELECT name_id FROM defs)
                     AND NOT EXISTS (SELECT 1 FROM defs x WHERE x.name_id = r.name_id AND x.file_id = r.file_id)
                   GROUP BY r.name_id) u ON u.name_id = d.name_id;
        UPDATE files SET score = COALESCE((SELECT SUM(s.used_files * 1.0 / s.def_files)
                                           FROM (SELECT DISTINCT name_id FROM defs WHERE file_id = files.id) d
                                           JOIN symbols s ON s.name_id = d.name_id), 0);
        DELETE FROM names WHERE id NOT IN (SELECT name_id FROM defs UNION SELECT name_id FROM refs UNION SELECT name_id FROM flows);
    """)


def build(tree: str, out: str, previous: str | None = None) -> dict:
    started = time.monotonic()
    commit = _git(tree, "rev-parse", "HEAD").decode().strip()
    covered, uncovered, too_large = _classify(tree, _entries(tree))
    scratch = f"{out}.new"
    for leftover in (scratch, f"{scratch}-journal"):
        if os.path.exists(leftover):
            os.unlink(leftover)
    db = sqlite3.connect(scratch, uri=True)  # for the ATTACH: a plain path stays a plain path
    db.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;")
    db.executescript(SCHEMA)
    total = len(covered)
    to_read = _carry(db, previous, covered) if previous and os.path.exists(previous) else covered
    if len(to_read) > MAX_FILES:
        raise SystemExit(f"{len(to_read)} files to read, and the limit is {MAX_FILES}")
    writer = _Writer(db)
    blobs = _Blobs(tree)
    for path, sha, language in to_read:  # one at a time, and written as it goes: nothing waits in memory
        source = blobs.read(sha)
        if source is not None:
            writer.file(path, sha, language, extract(language, source))
    blobs.close()
    db.executemany("INSERT INTO uncovered VALUES (?, ?)", sorted(uncovered.items()))
    db.executescript(INDEXES)
    _rank(db)
    stats = {"commit": commit, "extractor": EXTRACTOR, "files": total, "parsed": len(to_read), "reused": total - len(to_read), "too_large": too_large,
             "seconds": round(time.monotonic() - started, 2), "built": int(time.time()),
             "languages": dict(db.execute("SELECT language, COUNT(*) FROM files GROUP BY language").fetchall()), "with_errors": db.execute("SELECT COUNT(*) FROM files WHERE errors").fetchone()[0]}
    db.executemany("INSERT INTO meta VALUES (?, ?)", [(k, json.dumps(v) if not isinstance(v, str) else v) for k, v in stats.items()])
    db.commit()
    db.close()
    with open(scratch, "rb") as written:
        os.fsync(written.fileno())
    os.replace(scratch, out)
    return {**stats, "bytes": os.path.getsize(out)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tree")
    parser.add_argument("out")
    parser.add_argument("--previous")
    args = parser.parse_args()
    print(json.dumps(build(args.tree, args.out, args.previous)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
