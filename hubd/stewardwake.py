# SPDX-License-Identifier: GPL-2.0-or-later
"""What wakes the Steward (spec 012 FR-056): events about its own work, never a timer or a count.

An event is one line in the hub's words that names an item and says what happened to it:

- a suggestion it made being started, set aside or its result applied (from the new work and results stores);
- a session it started finishing its turn (handing back), handing in a result, or ending; a session it manages handing
  back, reporting or ending, and the maintainer's answer to its reports and cards (these come as the sentences
  managed.py wakes any owner with);
- for an item it named (in a suggestion, a report, or as the item of a session it started): a merge, a close, failing
  checks, a review or a new comment, from the change feed as it is recorded, leaving out its own doing.

Events wait here, on disk, until the Steward is at its prompt, and what came together goes in one turn: a batch is sent once
no new event has come for QUIET seconds, as one block marked as data. Nothing is sent on a timer, and nothing counts the
rest of the feed: that waits until the Steward reads it (FR-057). The items it named are kept on disk too, so a restart of
the hub keeps watching them, and are forgotten WATCH_FOR after they were last named.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path

log = logging.getLogger("hubd.stewardwake")

STEWARD = "steward"     # the Steward's fixed session name
QUIET = 3.0             # seconds with no new event before what came together is sent
TICK = 10.0             # seconds between looks at the sessions it started, and tries at a batch that couldn't go
MAX_PENDING = 100       # events waiting at once: the oldest give way, and the batch says how many did
MAX_AGE = 2 * 86400     # seconds an event waits for a Steward that isn't running, before it is dropped
MAX_WATCH = 500         # items it named, kept at once
WATCH_FOR = 14 * 86400  # seconds an item it named is watched after it last named it
MAX_WHY = 3             # where it named an item, kept per item: the latest few
MAX_TEXT = 400          # characters of one event

_REPO = r"\.?[A-Za-z0-9_][A-Za-z0-9._-]{0,99}"
_REPO_RE = re.compile(_REPO)
# An item as the Steward writes it in a report: repo#N, or a link to an issue or pull request of the organization.
_REF_RE = re.compile(rf"(?<![\w/.#-])({_REPO})#([1-9][0-9]{{0,14}})(?![\w#])")
_LINK_RE = re.compile(rf"https://github\.com/GlassineOS/({_REPO})/(?:issues|pull)/([1-9][0-9]{{0,14}})(?![0-9])")
_KIND_WORD = {"pr": "pull request", "issue": "issue"}
# What changes in an item it named wake it, in the hub's own words.
_REVIEW_WORDS = {"APPROVED": "reviewed: approved", "CHANGES_REQUESTED": "reviewed: changes requested"}


def feed_phrase(row: dict) -> str | None:
    """The words for a change in the feed that wakes the Steward about an item it named, or None for one that waits."""
    what, new = row.get("what"), row.get("new")
    if what == "state":
        return {"MERGED": "merged", "CLOSED": "closed"}.get(new)
    if what == "checks":
        return "its checks are failing" if new == "failing" else None
    if what == "review":
        return _REVIEW_WORDS.get(new)
    if what == "comments":
        return "a new comment"
    return None


def refs_in(text: str) -> list[tuple[str, int]]:
    """The items a text names, as repo#N or as a link, in order and once each."""
    found: list[tuple[str, int]] = []
    if not isinstance(text, str):
        return found
    for match in [*_REF_RE.finditer(text), *_LINK_RE.finditer(text)]:
        item = (match.group(1), int(match.group(2)))
        if item not in found:
            found.append(item)
    return found


def _key(repo: str, number: int) -> str:
    return f"{repo.lower()}#{number}"


class StewardEvents:
    """The Steward's events and the items it named. `agents` sends (`hub_events`) and says who is running; `feed` is the
    change feed, for the Steward's cursor; `public_of` tells, of some repositories, which are public, for a Steward that
    may not read private ones."""

    def __init__(self, path: Path | str | None, agents=None, feed=None, public_of=None, name: str = STEWARD,
                 clock=time.time, quiet: float = QUIET):
        self.path = Path(path) if path else None
        self.agents = agents
        self.feed = feed
        self.public_of = public_of
        self.name = name
        self._clock = clock
        self.quiet = quiet
        self.watched: dict[str, dict] = {}   # repo#n (lower case) -> {repo, number, kind, why: [..], at}
        self.pending: list[dict] = []        # {key, text, repo, at}
        self.seen: dict[str, str] = {}       # a session it started -> its state when last looked at
        self.dropped = 0                     # events that gave way since the last batch
        self._last = 0.0                     # when the newest event came
        self._soon: asyncio.Task | None = None
        self._load()

    # --- on disk ------------------------------------------------------------------------------
    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            log.warning("the Steward's events in %s can't be read: starting with none", self.path)
            return
        if not isinstance(data, dict):
            return
        watched, pending, seen = data.get("watched"), data.get("pending"), data.get("seen")
        if isinstance(watched, dict):
            self.watched = {k: v for k, v in watched.items() if isinstance(v, dict) and isinstance(v.get("repo"), str)
                            and isinstance(v.get("number"), int) and isinstance(v.get("why"), list)}
        if isinstance(pending, list):
            self.pending = [e for e in pending if isinstance(e, dict) and isinstance(e.get("text"), str)
                            and isinstance(e.get("key"), str) and isinstance(e.get("at"), (int, float))][-MAX_PENDING:]
        if isinstance(seen, dict):
            self.seen = {k: v for k, v in seen.items() if isinstance(k, str) and isinstance(v, str)}
        if isinstance(data.get("dropped"), int):
            self.dropped = data["dropped"]

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            scratch = self.path.with_suffix(".tmp")
            fd = os.open(scratch, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump({"watched": self.watched, "pending": self.pending, "seen": self.seen, "dropped": self.dropped}, f)
            scratch.replace(self.path)
        except OSError:
            log.exception("the Steward's events weren't saved")

    # --- the items it named ------------------------------------------------------------------
    def watch(self, repo, number, why: str, kind: str | None = None) -> None:
        """The Steward named this item: what happens to it from now on wakes it. `why` says where it named it."""
        if not isinstance(repo, str) or not _REPO_RE.fullmatch(repo) or not isinstance(number, int) or isinstance(number, bool) \
                or number <= 0:
            return
        now = self._clock()
        key = _key(repo, number)
        entry = self.watched.get(key) or {"repo": repo, "number": number, "kind": None, "why": []}
        entry["kind"] = kind if kind in _KIND_WORD else entry.get("kind")
        entry["why"] = [w for w in entry["why"] if w != why][-(MAX_WHY - 1):] + [why]
        entry["at"] = now
        self.watched[key] = entry
        self._prune_watch(now)
        self._save()

    def named_in(self, text: str, why: str) -> None:
        """Every item a text of the Steward's names, as repo#N or as a link, is watched."""
        for repo, number in refs_in(text):
            self.watch(repo, number, why)

    def _prune_watch(self, now: float) -> None:
        for key in [k for k, v in self.watched.items() if now - v.get("at", 0) > WATCH_FOR]:
            del self.watched[key]
        if len(self.watched) > MAX_WATCH:
            for key in sorted(self.watched, key=lambda k: self.watched[k].get("at", 0))[:len(self.watched) - MAX_WATCH]:
                del self.watched[key]

    def watching(self, repo: str, number: int) -> dict | None:
        entry = self.watched.get(_key(repo, number)) if isinstance(repo, str) and isinstance(number, int) else None
        if entry is None or self._clock() - entry.get("at", 0) > WATCH_FOR:
            return None
        return entry

    # --- events ------------------------------------------------------------------------------
    def add(self, text: str, key: str | None = None, repo: str | None = None) -> None:
        """One event for the Steward's next batch. One with the key of an event still waiting takes its place: the batch
        says the latest about it once."""
        if not isinstance(text, str) or not text.strip():
            return
        text = " ".join(text.split())[:MAX_TEXT]
        key = key or text
        now = self._clock()
        self.pending = [e for e in self.pending if e["key"] != key]
        self.pending.append({"key": key, "text": text, "repo": repo, "at": now})
        if len(self.pending) > MAX_PENDING:
            self.dropped += len(self.pending) - MAX_PENDING
            self.pending = self.pending[-MAX_PENDING:]
        self._last = now
        self._save()
        self._kick()

    def from_feed(self, rows: list[dict]) -> int:
        """Changes just recorded: those in an item it named that wake it, as events. Its own doing doesn't wake it."""
        added = 0
        for row in rows:
            phrase = feed_phrase(row)
            entry = self.watching(row.get("repo"), row.get("number")) if phrase else None
            if entry is None or row.get("own") or row.get("kind") not in _KIND_WORD:
                continue
            ref = f"{row['repo']}#{row['number']}"
            self.add(f"{ref} ({_KIND_WORD[row['kind']]}, which you named in {', '.join(entry['why'])}): {phrase}. {row.get('link') or ''}",
                     key=f"feed:{ref.lower()}:{row['what']}", repo=row["repo"])
            added += 1
        return added

    def is_steward(self, name) -> bool:
        return name == self.name

    def _kick(self) -> None:
        """A batch goes once no new event has come for `quiet` seconds. With no loop running, the tick sends it."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._soon is None or self._soon.done():
            self._soon = loop.create_task(self._after_quiet())

    async def _after_quiet(self) -> None:
        while True:
            wait = self._last + self.quiet - self._clock()
            if wait <= 0:
                break
            await asyncio.sleep(min(wait, self.quiet))
        await self.flush()

    def text(self, events: list[dict], dropped: int = 0) -> str:
        lines = [f"- {e['text']}" for e in events]
        if dropped:
            lines.append(f"- {dropped} earlier event{'s' if dropped != 1 else ''} gave way before you were at your prompt: "
                         "my_suggestions, list_sessions and changes_since have the state.")
        return "\n".join(lines)

    async def flush(self) -> bool:
        """Sends what waits, as one turn, to the Steward at its prompt. A Steward at work, waiting for the person, stopped
        or not there keeps it waiting for the next try; nothing ever starts it."""
        now = self._clock()
        old = [e for e in self.pending if now - e["at"] > MAX_AGE]
        if old:
            self.pending = [e for e in self.pending if e not in old]
            self.dropped += len(old)
            self._save()
        if not self.pending or self.agents is None:
            return False
        try:
            steward = next((s for s in await self.agents.stewards() if s["name"] == self.name), None)
            if steward is None:
                return False
            batch = list(self.pending)
            if not steward.get("all_repos"):
                # Only what it may read: a repository that can't be told apart as public is taken for private.
                repos = {e["repo"] for e in batch if e.get("repo")}
                public = await self.public_of(repos) if (repos and self.public_of) else set()
                hidden = [e for e in batch if e.get("repo") and e["repo"] not in public]
                if hidden:
                    self.pending = [e for e in self.pending if e not in hidden]
                    batch = [e for e in batch if e not in hidden]
                    self._save()
            if not batch:
                return False
            dropped = self.dropped
            await self.agents.hub_events(self.name, self.text(batch, dropped))
        except Exception as e:  # noqa: BLE001 — at work, a draft in its prompt, no room, tmux: the next try sends it
            log.info("no events to %s yet: %s", self.name, e)
            return False
        self.pending = [e for e in self.pending if e not in batch]
        self.dropped -= dropped
        self._save()
        return True

    # --- the look on a tick ------------------------------------------------------------------
    def started(self, session: str) -> None:
        """A session the Steward started: looked at from now on, from its first state, so a turn that ends before the next
        look still wakes it."""
        self.seen[session] = "Working"
        self._save()

    async def look(self) -> None:
        """A Steward seen running for the first time gets its feed cursor at the newest change; the sessions it started are
        looked at for a turn ended or an end; and what waits is tried again."""
        if self.agents is None:
            return
        try:
            stewards = await self.agents.stewards()
        except Exception:  # noqa: BLE001 — the next tick looks again
            log.exception("the Stewards couldn't be listed")
            stewards = []
        if self.feed is not None:
            for steward in stewards:
                if not self.feed.known(steward["name"]):
                    self.feed.begin(steward["name"])
        try:
            await self._look_at_started()
        except Exception:  # noqa: BLE001
            log.exception("the sessions the Steward started weren't looked at")
        if self.pending and (self._soon is None or self._soon.done()):
            await self.flush()

    async def _look_at_started(self) -> None:
        rows = await self.agents.started()
        changed = False
        names = set()
        for row in rows:
            name = row["name"]
            # A session under a workflow is its owner's: its hand-back and end come as its owner's wake (managed.py).
            if self.agents.started_by(name) != self.name or self.agents.owner_record(name) is not None:
                continue
            names.add(name)
            before, now = self.seen.get(name), row["state"]
            if before == now:
                continue
            self.seen[name] = now
            changed = True
            if before is None:  # first seen with this hub: nothing to compare with
                continue
            on = f"{row['repo']}#{row['number']}" if row.get("number") else (row.get("repo") or "the project")
            if now == "Stopped":
                self.add(f"{name}, a session you started on {on}, ended.", key=f"session:{name}")
            elif now == "Idle":
                self.add(f"{name}, a session you started on {on}, finished its turn: session_summary reads what it said.",
                         key=f"session:{name}")
        for gone in [n for n in self.seen if n not in names]:
            del self.seen[gone]
            changed = True
        if changed:
            self._save()
