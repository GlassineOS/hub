# SPDX-License-Identifier: GPL-2.0-or-later
"""Results: what a session hands in, which nothing applies until a login says so.

A session's own token hands in one result of its action's type (submit_result), in a closed shape per type. A login
reads it on a card and applies it: a review posted, labels set, a report kept. Applying writes only through the tools the
producing action names for it (`result_tools` in its file), as that persona's App when there is one, so a result can't
do more than its session's action allows. Every move is on disk, so a restart keeps what was handed in; one that died
while applying goes back to pending with a note to check GitHub first. A notes result keeps each operation's state on disk
as it starts and ends, so after a restart what finished is marked, and the one that was running is unknown until you look.

Drafts stay in the NewWork record (`clean_drafts`). A notes result is note operations (009 FR-006): each carries the command
hubd built for it and its own state, and applying one runs the notes tool for a login, never for a token.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import time
from pathlib import Path

from . import notes as notes_ops

# What a session hands in, per type. pr results are made by the hub when it finds the session's pull request.
HANDED_IN = ("comment", "labels", "findings", "report", "notes")
TYPES = (*HANDED_IN, "pr")
# The tools a person's press writes through, per type. An action lists the ones it may use as result_tools.
APPLY_TOOLS = {"comment": ("review_pr",), "labels": ("label_issue", "edit_issue"), "notes": ("notes_apply",)}
# A note operation's own state. running is on disk only while it runs; unknown is one that may or may not have gone in (hubd
# stopped, or the tool gave no answer in time), which doesn't run again until a login has looked and said which.
OP_STATES = ("pending", "running", "applied", "failed", "unknown")
STATES = ("pending", "applying", "applied", "dismissed")
PR_SETTLED = "The pull request is on GitHub: there is nothing to apply."


def _pr_settled() -> dict:
    now = time.time()
    return {"state": "applied", "applied_at": now, "applied_by": "the hub", "note": PR_SETTLED,
            "handled": {"by": "the hub", "where": None, "at": now}}
KEEP = 200  # results kept; settled ones go first, oldest first
PR_SEEN_FILE = "pr-seen.json"  # the pull requests already noted, per run: kept apart, so a pruned result isn't made again
PR_SEEN_KEEP = 5000
PAGE = 20
INTERRUPTED = "hubd restarted while this was being applied: check GitHub before applying it again."
NOTES_INTERRUPTED = ("hubd restarted while these were being applied. What finished is marked; the one that was running is "
                     "unknown: look at its topic, then say whether it's in the notes. It doesn't run again until you do.")
OP_INTERRUPTED = "hubd restarted while this ran, so it may or may not be in the notes."
REVIEW_EVENTS = ("comment", "request-changes", "approve")
SIDES = ("LEFT", "RIGHT")
_ID_RE = re.compile(r"r-[0-9a-f]{12}")
_REF_RE = re.compile(r"\.?[A-Za-z0-9_][A-Za-z0-9._-]{0,99}#[1-9][0-9]{0,14}")  # 15 digits, as feed.py takes: a run's number is 11 now
_REPO_RE = re.compile(r"\.?[A-Za-z0-9_][A-Za-z0-9._-]{0,99}")
MAX_LABELS = 6
MAX_LABEL = 50


class ResultError(Exception):
    """Said to whoever asked, in words."""


def _text(value, what: str, limit: int, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ResultError(f"{what} is text of {'at most' if empty else '1 to'} {limit} characters")
    return value


def _closed(payload, required: set, optional: set, what: str) -> dict:
    if not isinstance(payload, dict):
        raise ResultError(f"{what} is an object")
    keys = set(payload)
    if keys - required - optional:
        raise ResultError(f"{what} has only {', '.join(sorted(required | optional))}: not {', '.join(sorted(keys - required - optional))}")
    if required - keys:
        raise ResultError(f"{what} needs {', '.join(sorted(required - keys))}")
    return payload


def _list(value, what: str, limit: int) -> list:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > limit:
        raise ResultError(f"{what} is a list of at most {limit}")
    return value


def _ref(value, what: str) -> str:
    if not isinstance(value, str) or not _REF_RE.fullmatch(value) or ".." in value:
        raise ResultError(f"{what} is an item reference, repo#number")
    return value


def _labels(value, what: str) -> list[str]:
    labels = _list(value, what, MAX_LABELS)
    if not all(isinstance(x, str) and 0 < len(x) <= MAX_LABEL and x.strip() == x for x in labels) or len(set(labels)) != len(labels):
        raise ResultError(f"{what}: at most {MAX_LABELS} different labels, each short text")
    return labels


def clean_payload(kind: str, payload, items: list[dict]) -> dict:
    """The closed shape of each type (005 data model § Result): unknown keys are refused, every string capped."""
    covered = {f"{i['repo']}#{i['number']}" for i in items}
    if kind == "comment":  # 005 FR-017
        p = _closed(payload, {"summary", "event"}, {"notes"}, "a comment result")
        if p["event"] not in REVIEW_EVENTS:
            raise ResultError(f"event is one of {', '.join(REVIEW_EVENTS)}")
        summary = _text(p["summary"], "the summary", 8000, empty=p["event"] == "approve")
        notes = []
        for note in _list(p.get("notes"), "notes", 50):
            n = _closed(note, {"path", "line", "body"}, {"side"}, "a note")
            if not isinstance(n["line"], int) or isinstance(n["line"], bool) or n["line"] <= 0:
                raise ResultError("a note's line is a line number")
            side = n.get("side", "RIGHT")
            if side not in SIDES:
                raise ResultError("a note's side is LEFT (the old code) or RIGHT (the new)")
            notes.append({"path": _text(n["path"], "a note's path", 500), "line": n["line"], "side": side,
                          "body": _text(n["body"], "a note's body", 2000)})
        return {"summary": summary, "event": p["event"], "notes": notes}
    if kind == "labels":  # 005 FR-018
        p = _closed(payload, {"issues"}, set(), "a labels result")
        issues = _list(p["issues"], "issues", 20)
        if not issues:
            raise ResultError("name at least one issue")
        cleaned = []
        for issue in issues:
            i = _closed(issue, {"ref", "why"}, {"add", "remove", "part_of"}, "an issue")
            ref = _ref(i["ref"], "ref")
            if ref not in covered:  # the items this session was started on, and no others
                raise ResultError(f"{ref} isn't an item this session covers")
            add, remove = _labels(i.get("add"), "add"), _labels(i.get("remove"), "remove")
            part_of = None if i.get("part_of") is None else _ref(i["part_of"], "part_of")
            if not add and not remove and not part_of:
                raise ResultError(f"{ref}: add or remove a label, or name what it's part of")
            if set(add) & set(remove):
                raise ResultError(f"{ref}: a label can't be added and removed")
            cleaned.append({"ref": ref, "add": add, "remove": remove, "part_of": part_of, "why": _text(i["why"], "why", 500)})
        if len({c["ref"] for c in cleaned}) != len(cleaned):
            raise ResultError("one issue is named twice")
        return {"issues": cleaned}
    if kind == "findings":  # 005 FR-019
        p = _closed(payload, {"cause", "fix"}, {"files", "run"}, "a findings result")
        files = _list(p.get("files"), "files", 20)
        if not all(isinstance(f, str) and 0 < len(f) <= 500 for f in files):
            raise ResultError("files are paths of at most 500 characters")
        run = p.get("run")
        if run is not None and (not isinstance(run, str) or len(run) > 200):
            raise ResultError("run is the run's reference")
        return {"cause": _text(p["cause"], "the cause", 4000), "fix": _text(p["fix"], "the fix", 4000), "files": files, "run": run}
    if kind == "report":  # 005 FR-020
        p = _closed(payload, {"question", "answer"}, {"unsettled", "sources", "followups"}, "a report")
        unsettled = [_text(u, "what's unsettled", 1000) for u in _list(p.get("unsettled"), "unsettled", 20)]
        sources = []
        for source in _list(p.get("sources"), "sources", 30):
            s = _closed(source, {"link", "why"}, set(), "a source")
            sources.append({"link": _text(s["link"], "a source's link", 500), "why": _text(s["why"], "why a source matters", 500)})
        followups = [_text(f, "a follow-up", 500) for f in _list(p.get("followups"), "followups", 10)]
        return {"question": _text(p["question"], "the question", 2000), "answer": _text(p["answer"], "the answer", 20000),
                "unsettled": unsettled, "sources": sources, "followups": followups}
    if kind == "notes":  # 009 FR-006: proposed, never applied by the session; no op deletes (005 FR-021)
        p = _closed(payload, {"ops"}, {"summary"}, "a notes result")
        ops = _list(p["ops"], "ops", notes_ops.MAX_OPS)
        if not ops:
            raise ResultError("propose at least one operation")
        cleaned = []
        for op in ops:
            try:
                clean = notes_ops.clean_op(op)
            except notes_ops.OpError as e:
                raise ResultError(str(e)) from None
            cleaned.append({**clean, "command": notes_ops.command_of(clean), "state": "pending", "said": None})
        summary = _text(p.get("summary") or "", "the summary", 2000, empty=True)
        return {"ops": cleaned, "summary": summary}
    if kind == "pr":  # 005 FR-016: made by the hub, not handed in
        p = _closed(payload, {"repo", "number"}, set(), "a pr result")
        if not isinstance(p["repo"], str) or not _REPO_RE.fullmatch(p["repo"]) or ".." in p["repo"]:
            raise ResultError("not a repository name")
        if not isinstance(p["number"], int) or isinstance(p["number"], bool) or p["number"] <= 0:
            raise ResultError("not a pull request number")
        return {"repo": p["repo"], "number": p["number"]}
    raise ResultError(f"a result is one of {', '.join(TYPES)}")


def _pr_key(record: dict) -> str:
    return json.dumps([record.get("session"), record.get("session_id"), record["payload"].get("repo"), record["payload"].get("number")])


class Results:
    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.folder, 0o700)
        self.records: dict[str, dict] = {}
        try:
            seen = json.loads((self.folder / PR_SEEN_FILE).read_text())
        except (OSError, ValueError):
            seen = []
        self._pr_seen: list[str] = [s for s in seen if isinstance(s, str)] if isinstance(seen, list) else []
        for path in self.folder.glob("r-*.json"):
            try:
                record = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if not isinstance(record, dict) or not _ID_RE.fullmatch(str(record.get("id"))) or record.get("state") not in STATES:
                continue
            self.records[record["id"]] = record
            if record.get("type") == "pr" and record["state"] == "pending":  # one made before pr results were settled as made
                record.update(**_pr_settled())
                self._save(record)
            if record["state"] == "applying":  # it may or may not have gone out
                ops = record["payload"].get("ops") if record.get("type") == "notes" and isinstance(record.get("payload"), dict) else None
                for op in ops if isinstance(ops, list) else ():
                    if isinstance(op, dict) and op.get("state") == "running":
                        op.update(state="unknown", said=OP_INTERRUPTED)
                record.update(state="pending", note=NOTES_INTERRUPTED if record.get("type") == "notes" else INTERRUPTED)
                self._save(record)
        known = [_pr_key(r) for r in self.records.values() if r.get("type") == "pr" and isinstance(r.get("payload"), dict)]
        if any(k not in self._pr_seen for k in known):  # those noted before the list was kept
            self._pr_seen = [*self._pr_seen, *(k for k in known if k not in self._pr_seen)][-PR_SEEN_KEEP:]
            self._save_seen()

    def _save(self, record: dict) -> None:
        path = self.folder / f"{record['id']}.json"
        scratch = path.with_suffix(".tmp")
        fd = os.open(scratch, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(record, f)
        scratch.replace(path)

    def _prune(self) -> None:
        if len(self.records) <= KEEP:
            return
        order = sorted(self.records.values(), key=lambda r: (r["state"] in ("pending", "applying"), r["made"]))
        for record in order[:len(self.records) - KEEP]:
            del self.records[record["id"]]
            (self.folder / f"{record['id']}.json").unlink(missing_ok=True)

    def get(self, result_id) -> dict:
        record = self.records.get(result_id) if isinstance(result_id, str) and _ID_RE.fullmatch(result_id) else None
        if record is None:
            raise ResultError("that result isn't here any more")
        return record

    def _new(self, **fields) -> dict:
        record = {"id": f"r-{secrets.token_hex(6)}", "state": "pending", "kept": False, "made": time.time(), "applied_at": None,
                  "applied_by": None, "note": None, "handled": None, **fields}
        self.records[record["id"]] = record
        self._save(record)
        self._prune()
        return record

    def submit(self, kind: str, payload, *, session: str, session_id, launch, items: list[dict], action: str, persona) -> dict:
        """One pending result per session: a new hand-in replaces the one still waiting, which nobody has acted on. Once one is
        being applied or has been, the session has handed in its result and a second is refused (SECURITY.md: one result)."""
        if kind not in HANDED_IN:
            raise ResultError(f"a session hands in one of {', '.join(HANDED_IN)}")
        mine = [r for r in self.records.values() if r["session"] == session and r.get("session_id") == session_id and r["type"] in HANDED_IN]
        if any(r["state"] in ("applying", "applied") for r in mine):
            raise ResultError("this session's result was already applied or is being applied: a session hands in one result")
        cleaned = clean_payload(kind, payload, items)
        for old in [r for r in mine if r["state"] == "pending"]:
            del self.records[old["id"]]
            (self.folder / f"{old['id']}.json").unlink(missing_ok=True)
        return self._new(type=kind, payload=cleaned, session=session, session_id=session_id, launch=launch, items=items,
                         action=action, persona=persona)

    def note_pr(self, *, session: str, session_id, launch, items: list[dict], action: str, persona, repo: str, number: int) -> dict | None:
        """The pull request a session opened (or worked on), once per run. It is on GitHub already, so there is nothing to
        apply and nothing to ask: it is settled as it is made, and its card only links it."""
        payload = clean_payload("pr", {"repo": repo, "number": number}, items)
        key = _pr_key({"session": session, "session_id": session_id, "payload": payload})
        if key in self._pr_seen or any(r["type"] == "pr" and r["session"] == session and r.get("session_id") == session_id
                                       and r["payload"] == payload for r in self.records.values()):
            return None
        self._pr_seen = [*self._pr_seen, key][-PR_SEEN_KEEP:]
        self._save_seen()
        return self._new(type="pr", payload=payload, session=session, session_id=session_id, launch=launch, items=items,
                         action=action, persona=persona, **_pr_settled())

    def _save_seen(self) -> None:
        path = self.folder / PR_SEEN_FILE
        scratch = path.with_suffix(".tmp")
        fd = os.open(scratch, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(self._pr_seen, f)
        os.replace(scratch, path)

    def list(self, kind=None, kept=None, session=None, after=None) -> list[dict]:
        rows = sorted(self.records.values(), key=lambda r: r["made"], reverse=True)
        if kind is not None:
            rows = [r for r in rows if r["type"] == kind]
        if kept is not None:
            rows = [r for r in rows if r["kept"] is bool(kept)]
        if session is not None:
            rows = [r for r in rows if r["session"] == session]
        if after is not None:
            ids = [r["id"] for r in rows]
            rows = rows[ids.index(after) + 1:] if after in ids else []
        return rows[:PAGE]

    def all(self) -> list[dict]:
        return list(self.records.values())

    def claim(self, result_id) -> dict:
        """Before writing: two presses, or two tabs, can't post one review twice."""
        record = self.get(result_id)
        if record["type"] not in APPLY_TOOLS:
            raise ResultError({"findings": "findings have nothing to apply: start a fix session from them",
                               "report": "a report isn't applied: keep it for Knowledge",
                               "pr": "a pull request result has nothing to apply: open the pull request"}.get(record["type"], "nothing to apply"))
        if record["state"] != "pending":
            raise ResultError(f"this result is {record['state']}, not waiting to be applied")
        record.update(state="applying", note=None)
        self._save(record)
        return record

    def settle(self, result_id, applied: bool, by: str | None, note: str | None = None) -> dict:
        record = self.get(result_id)
        if applied:
            record.update(state="applied", applied_at=time.time(), applied_by=by, note=note)
        else:
            record.update(state="pending", note=note)
        self._save(record)
        return record

    def save_op(self, result_id, index: int, **fields) -> dict:
        """One note operation's state, on disk as soon as it changes, while its result is being applied."""
        record = self.get(result_id)
        record["payload"]["ops"][index].update(fields)
        self._save(record)
        return record

    def keep(self, result_id, kept) -> dict:
        record = self.get(result_id)
        if record["type"] != "report":
            raise ResultError("only a report is kept for Knowledge")
        record["kept"] = kept is not False
        self._save(record)
        return record

    def dismiss(self, result_id, handled: dict | None = None) -> dict:
        record = self.get(result_id)
        if record["state"] == "applying":
            raise ResultError("it's being applied: wait for it to finish")
        if record["state"] == "applied":
            raise ResultError("it's applied already")
        record.update(state="dismissed", handled=handled or record.get("handled"))
        self._save(record)
        return record

    def mark_handled(self, result_id, handled: dict) -> None:
        record = self.get(result_id)
        record["handled"] = handled
        self._save(record)


__all__ = ["Results", "ResultError", "clean_payload", "TYPES", "HANDED_IN", "APPLY_TOOLS", "INTERRUPTED", "NOTES_INTERRUPTED"]
