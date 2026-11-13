# SPDX-License-Identifier: GPL-2.0-or-later
"""Workflow drafts: what a Workflow author makes in the workflow-change workflow (spec 012, FR-062).

- **A draft is no version.** `draft_workflow` checks a text as a save would (the definition's checks and the library's own,
  as `workflow.check` does), diffs it against the version it starts from, replays it over a past session when one is named,
  and keeps it in hubd's state folder under the conversation that made it. It saves nothing and makes no decision: the tool
  server has no op that saves or proposes, and `workflow.save` and `workflow.propose` stay behind the login.
- **A replay is part of the checks.** When sessions ran on the workflow, a draft is replayed over one: the one named, else
  the newest. A replay that can't be run fails the draft; what it found goes on the proposal card.
- **Facts.** The newest draft's `draft.ok` (it passes), `draft.sensitive` (it grants a sensitive item or full access, so a
  code reviewer reads it first) and `draft.reviewed` (it went to that reviewer already, so a re-review needs a new draft),
  and `drafts.failed`: the failed drafts since the last that passed, a refused call among them, in the current round of
  the state the session is in, so a round of asking starts again at none.
- **The hub proposes.** The action names its states (`drafting` in the action file, checked on load). When the session
  enters the `propose` one, the hub puts its newest passing draft in Needs you as a `workflow.change` card through the
  editor's own proposal (`Workflows._propose`), with the session named as who proposed it and the draft's note shown as the
  session's words; a sensitive draft only with the reviewer's pass on that very draft. The author never calls it. A draft
  made from a version that is no longer the newest isn't proposed: the session goes back to drafting, told why.
- **Reading.** `read_workflow` gives a workflow's text as it runs, its versions and the sessions that ran on it, for a
  replay; `read_draft` the session's newest draft, or for a managed session its owner's.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import asyncio
import time
from pathlib import Path

from . import machinestore
from .instances import MachineError

log = logging.getLogger("hubd.drafts")

KEPT = 20            # drafts kept per conversation, the newest
OPS = ("wfdraft.make", "wfdraft.read", "wfdraft.workflow")
TOOLS = {"wfdraft.make": "draft_workflow", "wfdraft.read": "read_draft", "wfdraft.workflow": "read_workflow"}


class DraftError(Exception):
    """A request about a draft that can't be done; the message goes back to the caller."""


class Drafts:
    def __init__(self, agents, workflows, runner=None):
        self.agents = agents
        self.workflows = workflows  # machinestore.Workflows, whose checks, diff, replay and proposal these are
        self.root = Path(agents.sessions).parent / "workflow-drafts"
        self.machines = agents.machines
        self.machines.on_move(self.on_move)
        self._tasks: set[asyncio.Task] = set()
        if runner is not None:
            before = runner.more_facts

            def more(name, record):
                return {**(before(name, record) if before else {}), **self.facts(name, record)}
            runner.more_facts = more

    # --- the store ---------------------------------------------------------------------------
    def _file(self, session_id: str) -> Path:
        if not isinstance(session_id, str) or not session_id.replace("-", "").isalnum() or len(session_id) > 64:
            raise DraftError("not a conversation")
        return self.root / f"{session_id}.json"

    def drafts(self, session_id) -> list[dict]:
        try:
            rows = json.loads(self._file(session_id).read_text())
        except (OSError, ValueError, DraftError):
            return []
        return rows if isinstance(rows, list) else []

    def _keep(self, session_id: str, draft: dict) -> None:
        self._write(session_id, [*self.drafts(session_id), draft][-KEPT:])

    def _write(self, session_id: str, rows: list[dict]) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self._file(session_id).with_suffix(f".{secrets.token_hex(4)}.tmp")
        tmp.write_text(json.dumps(rows))
        os.replace(tmp, self._file(session_id))

    # --- the tools ---------------------------------------------------------------------------
    def make(self, scope: dict, name, wscope, text, note, session=None) -> dict:
        """draft_workflow: check, diff and replay a text, and keep it as the conversation's newest draft. A call refused before
        the checks is kept too, as a failed draft, so refusals count toward the failures in a row."""
        try:
            return self._make(scope, name, wscope, text, note, session)
        except DraftError as e:
            state, round_ = self._where(scope.get("session"))
            try:
                self._keep(scope.get("instance"), {"id": f"wd-{secrets.token_hex(6)}", "at": time.time(), "by": scope.get("session"),
                                                   "refused": True, "ok": False, "sensitive": False, "problems": [{"kind": "problem", "where": "call", "text": str(e)}],
                                                   "state": state, "round": round_})
            except DraftError:
                pass
            raise

    def _make(self, scope: dict, name, wscope, text, note, session=None) -> dict:
        who, sid = scope.get("session"), scope.get("instance")
        if not isinstance(note, str) or not note.strip() or len(note) > machinestore.MAX_NOTE:
            raise DraftError("say what the draft changes and why, in at most 2000 characters")
        if not isinstance(text, str) or len(text) > machinestore.MAX_TEXT:
            raise DraftError("text is the whole definition, at most 128 KiB")
        wscope = wscope or machinestore.ORG
        try:
            name = self.workflows._known(name)
            machinestore.repo_of(wscope)
            found = self.workflows._check({"name": name, "scope": wscope, "text": text}, None)
            base = self.workflows.store.latest_number(name, wscope)
            before = self.workflows._from_text(name, wscope, base)
        except machinestore.StoreError as e:
            raise DraftError(str(e)) from None
        problems = machinestore.problems_of(found["findings"])
        if before == text:
            problems = [*problems, {"kind": "problem", "where": "text", "text": "it's the same as the version it starts from"}]
        changed = machinestore.diff(before, text, machinestore._file_starts(self.workflows.library, name))
        marks = machinestore.sensitive_marks(before, found["findings"])
        replay = None
        if session is None:  # FR-062: replayed over the newest session that ran on it, when there is one
            past = self.workflows._sessions(name)
            session = past[0].get("session_id") if past else None
        if session is not None:
            try:
                replay = self.workflows._replay({"name": name, "text": text, "session": session}, None)
                replay = {k: replay[k] for k in ("session", "differs", "cant_tell", "first_difference", "end", "logged_end", "unknown_facts")}
            except machinestore.StoreError as e:
                replay = {"error": str(e)}
                problems = [*problems, {"kind": "problem", "where": "replay", "text": f"the replay couldn't run: {e}"}]
        state, round_ = self._where(who)
        draft = {"id": f"wd-{secrets.token_hex(6)}", "at": time.time(), "by": who, "workflow": name, "scope": wscope, "base_version": base,
                 "text": text, "note": note.strip(), "ok": not problems, "problems": problems[:20], "sensitive": bool(marks),
                 "marks": marks, "stat": changed["stat"], "replay": replay, "replay_session": session, "state": state, "round": round_}
        self._keep(sid, draft)
        failed = self._failed(self.drafts(sid), state, round_)
        # `passes`, not `ok`: the op's own `ok` says whether the call worked, and a failing draft is a call that worked
        return {"id": draft["id"], "passes": draft["ok"], "problems": draft["problems"], "sensitive": [m["text"] for m in marks],
                "stat": changed["stat"], "starts": [r for r in changed["starts"] or () if r["kind"] != "same"],
                "replay": replay, "failed_in_a_row": failed, "saved": False,
                "next": ("It passes. Ask to move on: to review, as it grants a sensitive item." if draft["ok"] and marks else
                         "It passes. Ask to move on to propose." if draft["ok"] else "Fix what the checks found and draft again.")}

    def read(self, scope: dict) -> dict:
        """read_draft: the conversation's newest draft, or for a managed session its owner's (a reviewer reads what it reviews)."""
        name, sid = scope.get("session"), scope.get("instance")
        owner = self.agents.owner_record(name) if isinstance(name, str) else None
        if owner:
            sid = owner.get("session_id")
        rows = [r for r in self.drafts(sid) if not r.get("refused")]
        if not rows:
            raise DraftError("there is no draft yet")
        d = rows[-1]
        try:
            base = self.workflows._from_text(d["workflow"], d["scope"], d["base_version"])
        except machinestore.StoreError:
            base = None
        return {k: d[k] for k in ("id", "workflow", "scope", "base_version", "text", "note", "problems", "sensitive", "marks",
                                  "stat", "replay")} | {"passes": d["ok"], "text_diff": machinestore.diff(base, d["text"])["text"] if base is not None else None}

    def read_workflow(self, name, wscope=None) -> dict:
        """read_workflow: a workflow's text as it runs for a scope, its versions, and the sessions that ran on it."""
        try:
            got = self.workflows._get({"name": name, "scope": wscope or machinestore.ORG}, None)
        except machinestore.StoreError as e:
            raise DraftError(str(e)) from None
        return {k: got[k] for k in ("name", "scope", "text", "shown", "latest", "in_use", "versions", "findings")} | {
            "sessions": [{"session": s.get("session_id"), "name": s.get("name"), "versions": s.get("versions")} for s in got["sessions"]]}

    # --- facts -------------------------------------------------------------------------------
    def _where(self, name) -> tuple[str | None, int]:
        try:
            inst = self.machines.peek(name) if isinstance(name, str) else None
        except MachineError:
            inst = None
        if inst is None:
            return None, 0
        return inst.state, int(inst.counters["rounds"].get(inst.state, 0))

    @staticmethod
    def _failed(rows: list[dict], state, round_) -> int:
        count = 0
        for d in reversed(rows):
            if d.get("state") != state or d.get("round") != round_ or d.get("ok"):
                break
            count += 1
        return count

    def facts(self, name: str, record: dict) -> dict:
        rows = self.drafts(record.get("session_id"))
        if not rows:
            return {}
        state, round_ = self._where(name)
        return {"draft.ok": bool(rows[-1]["ok"]), "draft.sensitive": bool(rows[-1]["sensitive"]),
                "draft.reviewed": bool(rows[-1].get("reviewed")), "drafts.failed": self._failed(rows, state, round_)}

    # --- the hub proposes --------------------------------------------------------------------
    def _drafting(self, record: dict) -> dict | None:
        action = self.agents.library.actions.get((record.get("config") or {}).get("action"))
        got = (action or {}).get("drafting")
        return got if isinstance(got, dict) else None

    def on_move(self, name: str, result: dict) -> None:
        if not result.get("moved"):
            return
        try:
            record = json.loads((self.agents.sessions / name / "session.json").read_text())
        except (OSError, ValueError):
            return
        drafting = self._drafting(record)
        if drafting is None:
            return
        if result.get("to") == drafting["review"]:
            self._mark_reviewed(record)
        elif result.get("to") == drafting["propose"]:
            self._spawn(self._propose_or_back(name, record, drafting))

    def _mark_reviewed(self, record: dict) -> None:
        """The draft the reviewer reads is the newest when review is entered; the author can't draft while it reads."""
        rows = self.drafts(record.get("session_id"))
        if rows:
            rows[-1]["reviewed"] = True
            self._write(record["session_id"], rows)

    async def _propose_or_back(self, name: str, record: dict, drafting: dict) -> None:
        try:
            self.propose(name, record, drafting)
            return
        except (DraftError, machinestore.StoreError) as e:
            why = str(e)
        log.info("%s: its draft wasn't proposed: %s", name, why)
        rows = self.drafts(record.get("session_id"))
        if rows and rows[-1].get("ok"):  # it no longer passes: the next proposal is of a new draft
            rows[-1]["ok"] = False
            rows[-1]["problems"] = [*rows[-1].get("problems", []), {"kind": "problem", "where": "proposal", "text": why}]
            self._write(record["session_id"], rows)
        self.agents.tell(name, f"[From the hub] Your draft wasn't proposed: {why}. You are back to drafting: draft again.")
        try:
            self.machines.move(name, drafting["draft"], "machine")
        except MachineError as e:
            log.warning("%s: it couldn't go back to drafting: %s", name, e)

    def propose(self, name: str, record: dict, drafting: dict | None = None) -> dict:
        """The newest draft, if it passes and starts from the newest version, as a workflow.change card. A sensitive one only
        after the reviewer passed that very draft."""
        drafting = drafting or self._drafting(record) or {}
        rows = self.drafts(record.get("session_id"))
        if not rows or not rows[-1]["ok"]:
            raise DraftError("the newest draft doesn't pass the checks")
        d = rows[-1]
        latest = self.workflows.store.latest_number(d["workflow"], d["scope"])
        if latest != d["base_version"]:
            raise DraftError(f"it was drafted from v{d['base_version']}, and v{latest} was saved since")
        if d["sensitive"]:
            try:
                inst = self.machines.peek(name)
            except MachineError:
                inst = None
            verdict = (inst.managed.get(drafting.get("reviewer", "")) or {}).get("returns", {}).get("verdict") if inst is not None else None
            if not (d.get("reviewed") and verdict == "pass"):
                raise DraftError("it grants a sensitive item and no reviewer passed this draft")
        req = {"name": d["workflow"], "scope": d["scope"], "text": d["text"], "note": d["note"]}
        if d.get("replay_session"):
            req["session"] = d["replay_session"]
        return self.workflows._propose(req, name)

    def _spawn(self, coroutine) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            coroutine.close()
            return
        task = loop.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
            await asyncio.sleep(0)  # a finished task leaves the set in its done callback, which runs only once the loop turns
