# SPDX-License-Identifier: GPL-2.0-or-later
"""The Notes tab's one query: `notes find`, by a login, in the words the tool answers.

The tool lives in the workspace and is run as a program, never imported: hubd stays standard
library, and the index stays the tool's own business, in its 0700 cache. Notes and the sources
behind the search never passed the safety scan, so this is the only way out of them that hubd has,
and server.py keeps it behind the login check. No token has it.
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
_ENV_KEEP = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR")
_TOTAL = re.compile(r"([0-9]+) rows? from (.+?)(?:, showing [0-9]+.*)?")
NO_STATE = "no state given"  # a row is never shown as if it were a fact


class NotesError(Exception):
    pass


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
    return {"state": word("state").strip() or NO_STATE, "where": _capped(word("where")), "label": _capped(word("label")), "text": _capped(word("text"))}


class Notes:
    def __init__(self, workspace: Path, timeout: float = TIMEOUT):
        self.workspace = Path(workspace)
        self.timeout = timeout

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
        return {"here": missing is None, "says": missing}

    async def find(self, words, limit=None) -> dict:
        words, limit = words_of(words), limit_of(limit)
        if missing := self.missing():
            return {"here": False, "says": missing, "rows": [], "total": 0, "warnings": []}
        out, err = await self._run(words, limit)
        said = err.split("\n")
        # Only on a newline: JSON can hold U+2028 and the like unescaped, and splitlines() would break a row on them.
        rows = [_row(line) for line in out.split("\n") if line.strip()]
        summary = next((m for m in map(_TOTAL.fullmatch, said) if m), None)
        return {"here": True, "says": f"{count(int(summary[1]))} from {summary[2]}" if summary else f"{count(len(rows))}",
                "rows": rows[:limit], "total": int(summary[1]) if summary else len(rows),
                "warnings": [_capped(line.removeprefix("notes: ")) for line in said if line.startswith("notes: ")][:MAX_WARNINGS]}

    async def _run(self, words: list[str], limit: int) -> tuple[str, str]:
        env = {k: os.environ[k] for k in _ENV_KEEP if k in os.environ}
        env["GLASSINE_WORKSPACE"] = str(self.workspace)  # the tool's own way of finding its workspace
        try:
            # -I: nothing from hubd's environment or user site. "--": what you typed is only ever words.
            proc = await asyncio.create_subprocess_exec(
                sys.executable or "python3", "-I", str(self.workspace / TOOL), "find", "--json", "--limit", str(limit), "--", *words,
                cwd=self.workspace, env=env, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        except OSError as e:
            raise NotesError(f"the notes tool didn't start: {e}") from None
        try:
            out, err = await asyncio.wait_for(proc.communicate(), self.timeout)
        except TimeoutError:
            raise NotesError(f"the search gave no answer in {self.timeout:g} seconds and was stopped. "
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
