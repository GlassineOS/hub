# SPDX-License-Identifier: GPL-2.0-or-later
"""Notes: `notes find` for a login and for a session that may search them, and the note operations a login applies, in the
words the tool answers.

The tool lives in the workspace and is run as a program, never imported: hubd stays standard
library, and the index stays the tool's own business, in its 0700 cache. Notes and the sources
behind the search never passed the safety scan, so server.py keeps the page's search behind the login check, and lets a
session's token have the tool only when its list has it, which the library gives an action that can't post, send or plan
work, and then without the archive's rows (SECURITY.md, Notes). Writing is a login's alone: a
closed list of operations, each one `notes add` or `notes set` built here from checked fields, none of them a delete
(009 FR-006, 005 FR-021).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

TOOL = Path("tools") / "notes"
FOLDER = "notes"
MAX_CHARS = 500
MAX_WORDS = 32
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
MAX_WARNINGS = 20
MAX_TEXT = 4000  # of one row. The tool cuts archive text itself, but a note's line is as long as it is
TIMEOUT = 60  # seconds. The first search builds the index, and how long that takes isn't measured
WRITE_TIMEOUT = 180  # seconds for one add or set: the tool edits, lints, runs the safety scan and commits under its lock
# The tool's own shapes (noteslib's _TOPIC and _ID): an operation names nothing else.
_TOPIC_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,59}/[A-Za-z0-9][A-Za-z0-9._+-]{0,59}")
_ID_RE = re.compile(r"c[0-9]{1,9}")
MAX_OPS = 30
MAX_IDS = 10
MAX_OP_WORDS = 2000
MAX_WHY = 500
# 009 FR-006: what a session may propose, each mapped to one invocation of the tool. merge and distil are a supersede by
# another name: the new text replaces the first note named and rests on the others, which stay in Current. It can't rest on
# the one it replaces, which goes to Log as it's written, so the tool's lint would refuse it; and with nothing else to rest
# on it would need seen or the person's word, which a session that only reads the notes has neither of. So each names at
# least two. An open item a session adds is its guess (the tool wants provenance for one). None of them deletes: what's
# replaced, retracted or closed goes to the topic's Log, marked, as the tool keeps it.
OPS = ("supersede", "merge", "distil", "retract", "answer", "add")
_REPLACING = ("supersede", "merge", "distil")
_OP_FIELDS = {"supersede": ({"op", "topic", "ids", "words"}, {"why"}), "merge": ({"op", "topic", "ids", "words"}, {"why"}),
              "distil": ({"op", "topic", "ids", "words"}, {"why"}), "retract": ({"op", "topic", "ids", "by", "why"}, set()),
              "answer": ({"op", "topic", "ids", "why"}, set()), "add": ({"op", "topic", "words"}, {"open", "why"})}
_ENV_KEEP = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR")
_TOTAL = re.compile(r"([0-9]+) rows? from (.+?)(?:, showing [0-9]+.*)?")
NO_STATE = "no state given"  # a row is never shown as if it were a fact
# What a session's search may show: the notes themselves. The archive's rows ("archive, unreviewed") are the old tree's docs, diaries,
# memory and transcripts, which never passed the scan and hold what tools were asked and answered. A state the tool doesn't name
# here is left out too, since hubd can't say what it is.
NOTE_STATES = ("current", "open", "history", "retracted")


class NotesError(Exception):
    pass


class NotesUnknown(NotesError):
    """A write that was stopped before the tool answered: it may or may not have gone in."""


def words_of(value) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        raise NotesError("say what to look for")
    try:
        value.encode("utf-8")  # it goes on a command line
    except UnicodeEncodeError:
        raise NotesError("what to look for has a character that can't be searched for") from None
    if len(value) > MAX_CHARS or "\0" in value:
        raise NotesError(f"what to look for has to be text of at most {MAX_CHARS} characters")
    words = value.split()
    if len(words) > MAX_WORDS:
        raise NotesError(f"that's more than {MAX_WORDS} words")
    return words


def limit_of(value) -> int:
    if value is None:
        return DEFAULT_LIMIT
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= MAX_LIMIT:
        raise NotesError(f"the limit is a number from 1 to {MAX_LIMIT}")
    return value


def _capped(text: str) -> str:
    return text if len(text) <= MAX_TEXT else f"{text[:MAX_TEXT]} ..."


def _row(line: str) -> dict:
    """One row as the page shows it. The state is always words, and text stays text."""
    try:
        row = json.loads(line)
    except ValueError:
        row = None
    if not isinstance(row, dict):
        raise NotesError("the notes tool answered with something that isn't a row, so nothing is shown. Does the tool match this hub?")
    def word(key: str) -> str:
        return row[key] if isinstance(row.get(key), str) else ""
    where = word("where")
    # 009 FR-003: a note's topic is where it lives, before the line number; a date only when the tool gives one.
    topic = where.rsplit(":", 1)[0] if _TOPIC_RE.fullmatch(where.rsplit(":", 1)[0]) else ""
    return {"state": word("state").strip() or NO_STATE, "where": _capped(where), "label": _capped(word("label")), "text": _capped(word("text")),
            "topic": topic, "date": word("date")[:40]}


class OpError(Exception):
    pass


def _one_line(value, what: str, limit: int) -> str:
    from .agents import _draws_nothing  # here, not at the top: agents imports results, which imports this module
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\0" in value:
        raise OpError(f"{what} is text of 1 to {limit} characters")
    # The card shows every op's words, and they go into the shared notes: nothing in them may be hidden from you. The same
    # test agents.py holds messages to, with the blanks no category gives away (U+2800, U+3164, variation selectors).
    if any(_draws_nothing(c) for c in value):
        raise OpError(f"{what} can't hold control characters or invisible ones")
    return " ".join(value.split())


def clean_op(op) -> dict:
    """One proposed operation, as the closed shape the hub shows and applies. A command isn't taken from it: hubd builds it."""
    if not isinstance(op, dict) or op.get("op") not in OPS:
        raise OpError(f"an operation is one of {', '.join(OPS)}; none deletes a note")
    required, optional = _OP_FIELDS[op["op"]]
    keys = set(op)
    if keys - required - optional or required - keys:
        raise OpError(f"{op['op']} has {', '.join(sorted(required))}{' and may have ' + ', '.join(sorted(optional)) if optional else ''}, "
                      f"not {', '.join(sorted(keys - required - optional)) or 'without ' + ', '.join(sorted(required - keys))}")
    if not isinstance(op["topic"], str) or not _TOPIC_RE.fullmatch(op["topic"]):
        raise OpError("a topic is AREA/TOPIC, as the notes tool names it")
    out = {"op": op["op"], "topic": op["topic"]}
    if "ids" in required:
        ids = op["ids"]
        if not isinstance(ids, list) or not 0 < len(ids) <= MAX_IDS or not all(isinstance(i, str) and _ID_RE.fullmatch(i) for i in ids) \
                or len(set(ids)) != len(ids):
            raise OpError(f"ids are 1 to {MAX_IDS} different note ids, as cN")
        if op["op"] in ("retract", "answer") and len(ids) != 1:
            raise OpError(f"{op['op']} is about one note")
        if op["op"] in _REPLACING and len(ids) < 2:
            raise OpError(f"{op['op']} names the note it replaces, then at least one current note the new words rest on: "
                          "a note can't rest on the one it replaces")
        out["ids"] = list(ids)
    if "by" in required:
        if not isinstance(op["by"], str) or not _ID_RE.fullmatch(op["by"]) or op["by"] in out["ids"]:
            raise OpError("by is the id of the note that shows it wrong")
        out["by"] = op["by"]
    if "words" in keys:
        out["words"] = _one_line(op["words"], "the words", MAX_OP_WORDS)
    if "why" in keys:
        out["why"] = _one_line(op["why"], "why", MAX_WHY)
    if "open" in keys:
        if not isinstance(op["open"], bool):
            raise OpError("open is true or false")
        out["open"] = op["open"]
    return out


def argv_of(op: dict) -> list[str]:
    """The tool's arguments for a clean op. Values follow `=` or `--`, so no text the session wrote can be read as a flag."""
    kind, topic = op["op"], op["topic"]
    if kind in _REPLACING:
        return ["set", f"--replaces={op['ids'][0]}", f"--inferred={','.join(op['ids'][1:])}", "--", topic, op["words"]]
    if kind == "retract":
        return ["set", f"--retract={op['ids'][0]}", f"--by={op['by']}", f"--why={op['why']}", "--", topic]
    if kind == "answer":
        return ["set", f"--close={op['ids'][0]}", f"--why={op['why']}", "--", topic]
    return ["add", *(["--open", "--guess"] if op.get("open") else []), "--", topic, op["words"]]


def command_of(op: dict) -> str:
    """What the card shows for an op: exactly what hubd runs, from the workspace."""
    return " ".join(["notes", *(_quote(a) for a in argv_of(op))])


def _quote(arg: str) -> str:
    return arg if re.fullmatch(r"[A-Za-z0-9_./=,:+-]+", arg) else "'" + arg.replace("'", "'\\''") + "'"


class Notes:
    def __init__(self, workspace: Path, timeout: float = TIMEOUT, write_timeout: float = WRITE_TIMEOUT):
        self.workspace = Path(workspace)
        self.timeout = timeout
        self.write_timeout = write_timeout
        self.finding = 0  # searches under way: each brings the tool's index up to date first (009 FR-004)
        self.last: dict | None = None  # totals of a login's last search's rows, counts only (009 FR-005); never a session's

    def missing(self) -> str | None:
        """Words for what isn't there yet, as neither has to be, and this creates neither."""
        tool, folder = self.workspace / TOOL, self.workspace / FOLDER
        if not tool.is_file():
            return f"The notes tool isn't in this workspace yet: there's no {tool}. Nothing was searched."
        if not folder.is_dir():
            return f"There are no notes yet: there's no {folder}. Nothing was searched."
        return None

    def status(self) -> dict:
        missing = self.missing()
        return {"here": missing is None, "says": missing, "indexing": self.finding > 0}

    async def find(self, words, limit=None, counted: bool = False, archive: bool = True) -> dict:
        """`counted` is for a login's search: its counts become the totals. A session's search leaves them as they are, so the
        flyout never counts what an Archivist looked for. `archive=False` is for a locked session: it gets the notes' rows and
        none of the archive's, and nothing of the sources the tool names, which are paths on this host (SECURITY.md, Notes)."""
        words, limit = words_of(words), limit_of(limit)
        if missing := self.missing():
            return {"here": False, "says": missing, "rows": [], "total": 0, "warnings": []}
        self.finding += 1
        try:
            out, err = await self._run(["find", "--json", "--limit", str(limit), "--", *words], self.timeout)
        finally:
            self.finding -= 1
        said = err.split("\n")
        # Only on a newline: JSON can hold U+2028 and the like unescaped, and splitlines() would break a row on them.
        rows = [_row(line) for line in out.split("\n") if line.strip()]
        summary = next((m for m in map(_TOTAL.fullmatch, said) if m), None)
        if not archive:
            # The tool ranks the archive after every note, so cutting its rows from the first `limit` leaves every note it found.
            kept = [row for row in rows if row["state"] in NOTE_STATES][:limit]
            everything = len(kept) < len(rows) or not summary or int(summary[1]) <= len(rows)  # no more notes beyond these rows
            if everything:
                return {"here": True, "says": f"{count(len(kept))} in the notes", "rows": kept, "total": len(kept), "warnings": []}
            return {"here": True, "says": f"{count(len(kept))} shown, and more match: ask for a larger limit", "rows": kept,
                    "total": int(summary[1]), "warnings": []}
        by_label: dict[str, int] = {}
        by_topic: dict[str, int] = {}
        for row in rows[:limit]:
            by_label[row["state"]] = by_label.get(row["state"], 0) + 1
            if row["topic"]:
                by_topic[row["topic"]] = by_topic.get(row["topic"], 0) + 1
        if counted:
            self.last = {"by_label": by_label, "by_topic": by_topic, "rows": len(rows[:limit])}
        return {"here": True, "says": f"{count(int(summary[1]))} from {summary[2]}" if summary else f"{count(len(rows))}",
                "rows": rows[:limit], "total": int(summary[1]) if summary else len(rows),
                "warnings": [_capped(line.removeprefix("notes: ")) for line in said if line.startswith("notes: ")][:MAX_WARNINGS]}

    async def totals(self) -> dict:
        """009 FR-005: totals per label and per topic. The tool has no stats command yet, so they're counted from your last
        search's rows here, and `source` says so."""
        if missing := self.missing():
            return {"here": False, "says": missing, "by_label": {}, "by_topic": {}, "source": None, "rows": 0}
        last = self.last or {"by_label": {}, "by_topic": {}, "rows": 0}
        return {"here": True, "says": None, "source": "last-search" if self.last else None, **last}

    async def apply(self, ops: list[dict], progress=None) -> list[dict]:
        """A login's press: each op in order, one tool run each. `progress(n, outcome)` hears each op as it starts (running)
        and as it ends, so whoever keeps the record has it on disk before the next one runs. The first that fails stops the
        rest, which stay to retry, since a later op may rest on an earlier one; so does one whose outcome is unknown."""
        if missing := self.missing():
            raise NotesError(missing)
        done = []
        for n, op in enumerate(ops):
            if progress:
                progress(n, {"state": "running", "said": None})
            try:
                out, err = await self._run(argv_of(op), self.write_timeout)
            except NotesUnknown as e:
                outcome = {"state": "unknown", "said": str(e)[-600:]}
            except NotesError as e:
                outcome = {"state": "failed", "said": str(e)[-600:]}
            else:
                outcome = {"state": "applied", "said": (out.strip() or err.strip())[-600:]}
            if progress:
                progress(n, outcome)
            done.append(outcome)
            if outcome["state"] != "applied":
                break
        return done

    async def _run(self, args: list[str], timeout: float) -> tuple[str, str]:
        env = {k: os.environ[k] for k in _ENV_KEEP if k in os.environ}
        env["GLASSINE_WORKSPACE"] = str(self.workspace)  # the tool's own way of finding its workspace
        try:
            # -I: nothing from hubd's environment or user site. "--": what you typed is only ever words.
            proc = await asyncio.create_subprocess_exec(
                sys.executable or "python3", "-I", str(self.workspace / TOOL), *args,
                cwd=self.workspace, env=env, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        except OSError as e:
            raise NotesError(f"the notes tool didn't start: {e}") from None
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except TimeoutError:
            if args[0] != "find":  # it may have committed just before: only a look at the topic tells
                raise NotesUnknown(f"the notes tool gave no answer in {timeout:g} seconds and was stopped, so this may or may "
                                   "not be in the notes: look at its topic, then say which") from None
            raise NotesError(f"the search gave no answer in {timeout:g} seconds and was stopped. "
                             "The first one builds the index: `notes find` in a terminal has no limit.") from None
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
        said = err.decode(errors="replace").strip()
        if proc.returncode != 0:
            raise NotesError(said.removeprefix("notes: ")[-600:] or f"the notes tool stopped with status {proc.returncode}")
        return out.decode(errors="replace"), said


def count(n: int) -> str:
    return f"{n} row" if n == 1 else f"{n} rows"
