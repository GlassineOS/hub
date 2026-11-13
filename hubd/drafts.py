# SPDX-License-Identifier: GPL-2.0-or-later
"""Workflow drafts: what a Workflow author makes in the workflow-change workflow (spec 012, FR-062).

- **A draft is no version.** `draft_workflow` checks a text as a save would (the definition's checks and the library's own,
  as `workflow.check` does), diffs it against the version it starts from, replays it over a past session when one is named,
  and keeps it in hubd's state folder under the conversation that made it. It saves nothing and makes no decision: the tool
  server has no op that saves or proposes, and `workflow.save` and `workflow.propose` stay behind the login.
- **Facts.** The newest draft's `draft.ok` (it passes) and `draft.sensitive` (it grants a sensitive item or full access, so
  a code reviewer reads it first), and `drafts.failed`: the failed drafts since the last that passed, in the current round
  of the state the session is in, so a round of asking starts again at none.
- **The hub proposes.** When a workflow-change session enters its `propose` state, the hub puts its newest passing draft in
  Needs you as a `workflow.change` card through the editor's own proposal (`Workflows._propose`), with the session named as
  who proposed it and the draft's note shown as the session's words. The author never calls it.
- **Reading.** `read_workflow` gives a workflow's text as it runs, its versions and the sessions that ran on it, for a
  replay; `read_draft` the session's newest draft, or for a managed session its owner's.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import time
from pathlib import Path

from . import machinestore
from .instances import MachineError

log = logging.getLogger("hubd.drafts")

ACTION = "workflow-change"
PROPOSE = "propose"  # the state whose entry makes the hub propose the newest passing draft
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
        rows = [*self.drafts(session_id), draft][-KEPT:]
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self._file(session_id).with_suffix(f".{secrets.token_hex(4)}.tmp")
        tmp.write_text(json.dumps(rows))
        os.replace(tmp, self._file(session_id))

    # --- the tools ---------------------------------------------------------------------------
    def make(self, scope: dict, name, wscope, text, note, session=None) -> dict:
        """draft_workflow: check, diff and replay a text, and keep it as the conversation's newest draft."""
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
        changed = machinestore.diff(before, text)
        marks = machinestore.sensitive_marks(before, found["findings"])
        replay = None
        if session is not None:
            try:
                replay = self.workflows._replay({"name": name, "text": text, "session": session}, None)
                replay = {k: replay[k] for k in ("session", "differs", "cant_tell", "first_difference", "end", "logged_end", "unknown_facts")}
            except machinestore.StoreError as e:
                replay = {"error": str(e)}
        state, round_ = self._where(who)
        draft = {"id": f"wd-{secrets.token_hex(6)}", "at": time.time(), "by": who, "workflow": name, "scope": wscope, "base_version": base,
                 "text": text, "note": note.strip(), "ok": not problems, "problems": problems[:20], "sensitive": bool(marks),
                 "marks": marks, "stat": changed["stat"], "replay": replay, "replay_session": session, "state": state, "round": round_}
        self._keep(sid, draft)
        failed = self._failed(self.drafts(sid), state, round_)
        return {"id": draft["id"], "ok": draft["ok"], "problems": draft["problems"], "sensitive": [m["text"] for m in marks],
                "stat": changed["stat"], "replay": replay, "failed_in_a_row": failed, "saved": False,
                "next": ("It passes. Ask to move on: to review, as it grants a sensitive item." if draft["ok"] and marks else
                         "It passes. Ask to move on to propose." if draft["ok"] else "Fix what the checks found and draft again.")}

    def read(self, scope: dict) -> dict:
        """read_draft: the conversation's newest draft, or for a managed session its owner's (a reviewer reads what it reviews)."""
        name, sid = scope.get("session"), scope.get("instance")
        owner = self.agents.owner_record(name) if isinstance(name, str) else None
        if owner:
            sid = owner.get("session_id")
        rows = self.drafts(sid)
        if not rows:
            raise DraftError("there is no draft yet")
        d = rows[-1]
        try:
            base = self.workflows._from_text(d["workflow"], d["scope"], d["base_version"])
        except machinestore.StoreError:
            base = None
        return {k: d[k] for k in ("id", "workflow", "scope", "base_version", "text", "note", "ok", "problems", "sensitive", "marks",
                                  "stat", "replay")} | {"text_diff": machinestore.diff(base, d["text"])["text"] if base is not None else None}

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
                "drafts.failed": self._failed(rows, state, round_)}

    # --- the hub proposes --------------------------------------------------------------------
    def on_move(self, name: str, result: dict) -> None:
        if not result.get("moved") or result.get("to") != PROPOSE:
            return
        try:
            record = json.loads((self.agents.sessions / name / "session.json").read_text())
        except (OSError, ValueError):
            return
        if (record.get("config") or {}).get("action") != ACTION:
            return
        try:
            self.propose(name, record)
        except (DraftError, machinestore.StoreError) as e:
            log.info("%s: its draft wasn't proposed: %s", name, e)
            self.agents.tell(name, f"[From the hub] Your draft wasn't proposed: {e}")

    def propose(self, name: str, record: dict) -> dict:
        """The newest draft, if it passes, as a workflow.change card. A sensitive one only after its reviewer passed it."""
        rows = self.drafts(record.get("session_id"))
        if not rows or not rows[-1]["ok"]:
            raise DraftError("the newest draft doesn't pass the checks")
        d = rows[-1]
        if d["sensitive"]:
            try:
                inst = self.machines.peek(name)
            except MachineError:
                inst = None
            passed = inst is not None and (inst.managed.get("reviewer") or {}).get("returns", {}).get("verdict") == "pass"
            if not passed:
                raise DraftError("it grants a sensitive item and no reviewer passed it")
        req = {"name": d["workflow"], "scope": d["scope"], "text": d["text"], "note": d["note"]}
        if d.get("replay_session"):
            req["session"] = d["replay_session"]
        return self.workflows._propose(req, name)
