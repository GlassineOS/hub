"""New work: planner runs that end in drafts, which nothing files until you say so.

A record goes offered (an agent suggested it, nothing has run) or straight to planning, then
running, then done with its drafts, or failed. Each draft stays unfiled until you file it or hand
it to the Steward. Every move is on disk, so a restart keeps what a planner handed in.

Every Launch is one of these records (005 R1). A record from before Launch has no `v` and is read
as it was; one made since has `v: 2` with its covered items, repositories, where it was opened
from, the plan's steps, whether it runs in the background and the result it ended in. Its stage
(005 FR-002) is derived from its state and never stored as a decision.
"""
import json
import os
import re
import secrets
import time
from pathlib import Path

MAX_DRAFTS = 40
MAX_TITLE = 200
MAX_BODY = 8000
MAX_LABELS = 6
MAX_LABEL = 50
MAX_WHY = 500
MAX_OFFERS_PER_SESSION = 3
MAX_OFFERS = 20
KEEP_FINISHED = 50  # filed and dismissed records, for the list; the issues themselves are on GitHub
SEVERITIES = ("critical", "high", "medium", "low", "info")
FILING_LIFE = 600  # seconds with no progress before a draft in filing is yours again: the app filing it has gone
OPEN_STATES = ("offered", "planning", "planned", "starting", "running", "done", "failed")
_ID_RE = re.compile(r"[0-9a-f]{12}")
_REPO_RE = re.compile(r"[A-Za-z0-9._-]+")
_DRAFT_FIELDS = {"severity", "title", "body", "target", "labels", "parent"}
VERSION = 2
# The stage a page shows for a state (005 data model § Launch record). brief lives only in the page, until offered.
STAGES = {"offered": "brief", "planning": "planning", "planned": "plan", "starting": "run", "running": "run", "started": "run",
          "done": "result", "filed": "result", "failed": "failed", "dismissed": "dismissed", "discarded": "dismissed"}


def stage_of(record: dict) -> str:
    return STAGES.get(record.get("state"), "failed")


INTERRUPTED = "Filing was interrupted: check GitHub before filing this again."


class WorkError(Exception):
    """Said to whoever asked, in words."""


def clean_drafts(drafts, default_repo: str) -> list[dict]:
    """What a planner hands in, whatever it read on the way there."""
    if not isinstance(drafts, list) or not drafts or len(drafts) > MAX_DRAFTS:
        raise WorkError(f"hand in between 1 and {MAX_DRAFTS} drafts")
    cleaned = []
    for draft in drafts:
        if not isinstance(draft, dict) or set(draft) - _DRAFT_FIELDS:
            raise WorkError(f"a draft has only {', '.join(sorted(_DRAFT_FIELDS))}")
        title, body = draft.get("title"), draft.get("body", "")
        if not isinstance(title, str) or not title.strip() or len(title) > MAX_TITLE:
            raise WorkError(f"a draft needs a title of at most {MAX_TITLE} characters")
        if not isinstance(body, str) or len(body) > MAX_BODY:
            raise WorkError(f"a draft's body is text of at most {MAX_BODY} characters")
        severity = draft.get("severity")
        if severity is not None and severity not in SEVERITIES:
            raise WorkError(f"severity is one of {', '.join(SEVERITIES)}, or left out")
        target = draft.get("target") or default_repo
        if not isinstance(target, str) or not _REPO_RE.fullmatch(target) or ".." in target:
            raise WorkError(f"not a repository name: {target}")
        labels = draft.get("labels") or []
        if not isinstance(labels, list) or len(labels) > MAX_LABELS or not all(
                isinstance(x, str) and 0 < len(x) <= MAX_LABEL for x in labels):
            raise WorkError(f"at most {MAX_LABELS} labels, each short text")
        parent = draft.get("parent")
        if parent is not None and (not isinstance(parent, str) or len(parent) > MAX_TITLE):
            raise WorkError("parent is the title of another draft, or a reference to an issue")
        cleaned.append({"severity": severity, "title": title.strip(), "body": body, "target": target,
                        "labels": labels, "parent": parent or None, "state": "draft", "url": None, "note": None})
    return cleaned


class NewWork:
    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.records: dict[str, dict] = {}
        for path in self.folder.glob("*.json"):
            try:
                record = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            self.records[record["id"]] = record
            self._after_restart(record)

    def _after_restart(self, record: dict) -> None:
        changed = False
        if record["state"] == "planning":  # the start itself died with hubd
            record.update(state="failed", error="hubd restarted before the planner started. Nothing was filed.")
            changed = True
        if record["state"] == "starting":  # its session may be running with nothing pointing at it: Start again could make two
            record.update(state="failed", error="hubd restarted while the session was starting. Check Sessions: it may be running, and then it can't hand in drafts.")
            changed = True
        for draft in record.get("drafts") or ():
            if draft["state"] == "filing":  # it may or may not have gone out
                draft.update(state="draft", note=INTERRUPTED)
                changed = True
        if changed:
            self._save(record)

    def _save(self, record: dict) -> None:
        record["stage"] = stage_of(record)  # derived, kept beside the state it comes from for whoever reads the reply
        path = self.folder / f"{record['id']}.json"
        scratch = path.with_suffix(".tmp")
        fd = os.open(scratch, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(record, f)
        scratch.replace(path)

    def _prune(self) -> None:
        finished = sorted((r for r in self.records.values() if r["state"] not in OPEN_STATES), key=lambda r: r["made"])
        for record in finished[:max(0, len(finished) - KEEP_FINISHED)]:
            del self.records[record["id"]]
            (self.folder / f"{record['id']}.json").unlink(missing_ok=True)

    def get(self, work_id) -> dict:
        record = self.records.get(work_id) if isinstance(work_id, str) and _ID_RE.fullmatch(work_id) else None
        if record is None:
            raise WorkError("that planned work isn't here any more")
        return record

    def new(self, fields: dict, state: str) -> dict:
        record = {"id": secrets.token_hex(6), "v": VERSION, "state": state, "session": None, "drafts": [], "error": None, "made": time.time(),
                  "covers": [], "repos": [], "from": None, "plan": None, "background": False, "result": None, **fields}
        self.records[record["id"]] = record
        self._save(record)
        self._prune()
        return record

    def offer(self, session: str, fields: dict) -> dict:
        waiting = [r for r in self.records.values() if r["state"] == "offered"]
        if len(waiting) >= MAX_OFFERS or sum(r["by"] == session for r in waiting) >= MAX_OFFERS_PER_SESSION:
            raise WorkError("enough suggestions are waiting for the person already: wait until they've looked at them")
        return self.new({**fields, "by": session}, "offered")

    def move(self, record: dict, state: str, **changes) -> dict:
        record.update(state=state, moved=time.time(), **changes)
        self._save(record)
        self._prune()
        return record

    def by_session(self, session: str, session_id: str | None = None) -> dict | None:
        """A stopped session can be resumed from Sessions, and then it can still hand in. Only its own conversation:
        an older one restored under the same name isn't this run."""
        return next((r for r in self.records.values() if r["session"] == session and r["state"] in ("running", "failed")
                     and r.get("session_id") in (None, session_id)), None)

    def forget_session(self, session: str) -> None:
        for record in self.records.values():
            if record["session"] == session:
                record["session"] = None
                self._save(record)

    def _chosen(self, record: dict, indexes) -> list[int]:
        drafts = record["drafts"]
        if not isinstance(indexes, list) or not indexes or len(set(map(str, indexes))) != len(indexes) or not all(
                isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(drafts) for i in indexes):
            raise WorkError("choose at least one draft")
        taken = [drafts[i]["title"] for i in indexes if drafts[i]["state"] != "draft"]
        if taken:
            raise WorkError(f"already filed or handed over: {taken[0]}")
        return indexes

    def edit(self, work_id, index, title, body) -> dict:
        """005 FR-015: you change a draft's title and body before filing it. Only a draft still waiting, within a draft's limits.

        A draft's `parent` is another draft's title, so a new title is followed by the drafts that name the old one, and a
        title another draft already has is refused: a parent line would mean either."""
        record = self.get(work_id)
        self._chosen(record, [index])
        drafts = record["drafts"]
        draft = drafts[index]
        cleaned = clean_drafts([{"title": title, "body": body, "severity": draft["severity"], "target": draft["target"],
                                 "labels": draft["labels"], "parent": draft["parent"]}], draft["target"])[0]
        old, new = draft["title"], cleaned["title"]
        if new != old and any(d["title"] == new for d in drafts):
            raise WorkError(f"another draft is called {new}: a title needs to be its own, as a parent is named by its title")
        # file_drafts reads a parent line as the first draft with that title: if this is a second of the same name, nothing points here.
        if new != old and next(i for i, d in enumerate(drafts) if d["title"] == old) == index:
            for other in drafts:
                if other["parent"] == old:
                    other["parent"] = new
        draft.update(title=new, body=cleaned["body"], note=None)
        self._save(record)
        return record

    def claim(self, work_id, indexes) -> dict:
        """Before filing: two clicks, or two tabs, can't file a draft twice."""
        record = self.get(work_id)
        for i in self._chosen(record, indexes):
            record["drafts"][i]["state"] = "filing"
        record["filing_at"] = time.time()
        self._save(record)
        return record

    def filed(self, work_id, index, url, note=None) -> dict:
        record = self.get(work_id)
        draft = record["drafts"][index]
        record["filing_at"] = time.time()
        if url:
            draft.update(state="filed", url=url, note=note)
        else:
            draft.update(state="draft", note=note)
        self._settle(record)
        self._save(record)
        return record

    def hand(self, work_id, indexes) -> dict:
        record = self.get(work_id)
        for i in self._chosen(record, indexes):
            record["drafts"][i]["state"] = "handed"
        self._settle(record)
        self._save(record)
        return record

    def bring_back(self, work_id) -> dict:
        """Setting aside hides drafts, it doesn't delete them."""
        record = self.get(work_id)
        if record["state"] != "dismissed" or not record["drafts"]:
            raise WorkError("there's nothing set aside here to bring back")
        record["state"] = "done"
        self._settle(record)
        self._save(record)
        return record

    def discard(self, work_id) -> dict:
        """You don't want these: unlike setting aside, they can't come back. What you filed or handed over isn't touched."""
        record = self.get(work_id)
        if record["state"] in ("planning", "starting", "running"):
            raise WorkError("it's still running: cancel it first")
        if any(d["state"] == "filing" for d in record["drafts"]):
            raise WorkError("a draft is being filed: wait for it to finish")
        for draft in record["drafts"]:
            if draft["state"] == "draft":
                draft["state"] = "discarded"
        return self.move(record, "discarded")

    def _settle(self, record: dict) -> None:
        """Done until no draft is waiting for you. A draft you didn't choose goes when you dismiss the record."""
        if record["state"] == "done" and all(d["state"] in ("filed", "handed") for d in record["drafts"]):
            record["state"] = "filed"

    def handed(self) -> list[dict]:
        """What the Steward has been given and hasn't got an issue for. Written by planners: data."""
        rows = []
        for record in self.records.values():
            drafts = [{"index": i, **{k: d[k] for k in ("severity", "title", "body", "target", "labels", "parent")}}
                      for i, d in enumerate(record["drafts"]) if d["state"] == "handed"]
            if drafts:
                rows.append({"id": record["id"], "template": record["title"], "repo": record["repo"], "drafts": drafts})
        return rows

    def _release_stuck(self, record: dict) -> None:
        if time.time() - record.get("filing_at", 0) < FILING_LIFE:
            return
        stuck = [d for d in record["drafts"] if d["state"] == "filing"]
        for draft in stuck:
            draft.update(state="draft", note=INTERRUPTED)
        if stuck:
            self._save(record)

    def list(self) -> list[dict]:
        for record in self.records.values():
            self._release_stuck(record)
            record["stage"] = stage_of(record)  # derived each time: set here, as callers move these very records
        return sorted(self.records.values(), key=lambda r: r["made"], reverse=True)
