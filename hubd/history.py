"""What's left of a session after it ended: a small record, and Claude Code's own transcript.

Ending a session deletes its folder. The record here is what lets it be found and resumed later.
Transcripts are Claude Code's, and nothing in the hub deletes them.
"""
import json
import os
import re
import time
from pathlib import Path

MAX_RECORDS = 500
LAST_WORDS = 200
MAX_MESSAGES = 200
MAX_MESSAGE = 4000
MAX_SEARCH_BYTES = 200 * 1024 * 1024  # across all transcripts, so one search can't run for minutes
MAX_MATCHES = 50
_ID_RE = re.compile(r"[0-9a-fA-F-]{8,64}")


def valid_id(session_id) -> bool:
    return isinstance(session_id, str) and _ID_RE.fullmatch(session_id) is not None


def _messages(path: Path):
    """(role, text) in order. A line that isn't a message, or is cut, is skipped."""
    with path.open("rb") as f:
        for line in f:
            try:
                row = json.loads(line)
                if row.get("type") not in ("user", "assistant"):
                    continue
                content = row["message"]["content"]
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
            parts = [content] if isinstance(content, str) else [
                b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
            ] if isinstance(content, list) else []
            text = "\n".join(parts).strip()
            if text:
                yield row["type"], text


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


class History:
    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self._facts: dict[str, tuple] = {}  # transcript path -> (mtime, size, facts): listing reads every transcript

    def add(self, record: dict, how: str) -> None:
        """Called just before a session's folder goes."""
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        kept = {**record, "how": how, "ended": time.time()}
        path = self.folder / f"{record['session_id']}.json"
        scratch = path.with_suffix(".tmp")
        fd = os.open(scratch, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(kept, f)
        scratch.replace(path)
        self._prune()

    def _prune(self) -> None:
        records = sorted(self.folder.glob("*.json"), key=lambda p: p.stat().st_mtime)
        for path in records[:max(0, len(records) - MAX_RECORDS)]:
            path.unlink(missing_ok=True)

    def records(self) -> list[dict]:
        found = []
        if self.folder.is_dir():
            for path in self.folder.glob("*.json"):
                try:
                    found.append(json.loads(path.read_text()))
                except (OSError, ValueError):
                    continue
        return found

    def get(self, session_id) -> dict | None:
        if not valid_id(session_id):
            return None
        try:
            return json.loads((self.folder / f"{session_id}.json").read_text())
        except (OSError, ValueError):
            return None

    def drop(self, session_id) -> None:
        if valid_id(session_id):
            (self.folder / f"{session_id}.json").unlink(missing_ok=True)

    def has_name(self, name: str) -> bool:
        return any(r.get("name") == name for r in self.records())

    def facts(self, path: Path | None) -> dict:
        """Its last words and how many turns you took. Empty if the transcript is gone."""
        if path is None:
            return {"last": None, "turns": 0, "transcript": False}
        try:
            stat = path.stat()
        except OSError:
            return {"last": None, "turns": 0, "transcript": False}
        cached = self._facts.get(str(path))
        if cached and cached[:2] == (stat.st_mtime, stat.st_size):
            return cached[2]
        last, turns = None, 0
        for role, text in _messages(path):
            if role == "assistant":
                last = text
            else:
                turns += 1
        facts = {"last": _clip(last, LAST_WORDS) if last else None, "turns": turns, "transcript": True}
        self._facts[str(path)] = (stat.st_mtime, stat.st_size, facts)
        return facts

    @staticmethod
    def read(path: Path) -> dict:
        messages = list(_messages(path))
        return {"cut": max(0, len(messages) - MAX_MESSAGES),
                "messages": [{"role": r, "text": _clip(t, MAX_MESSAGE)} for r, t in messages[-MAX_MESSAGES:]]}

    @staticmethod
    def search(paths: dict[str, Path], words: str) -> dict:
        """Which transcripts hold these words, as you typed them, ignoring case. Reads newest first."""
        needle = words.casefold()
        matches, left, cut = {}, MAX_SEARCH_BYTES, False
        ordered = sorted(paths.items(), key=lambda kv: kv[1].stat().st_mtime if kv[1].exists() else 0, reverse=True)
        for session_id, path in ordered:
            if len(matches) >= MAX_MATCHES:
                cut = True
                break
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > left:  # this one is too long, the next may fit
                cut = True
                continue
            left -= size
            for _role, text in _messages(path):
                at = text.casefold().find(needle)
                if at >= 0:
                    matches[session_id] = _clip(text[max(0, at - 60):at + 140].replace("\n", " "), 200)
                    break
        return {"matches": matches, "cut": cut}
