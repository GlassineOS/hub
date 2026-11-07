# SPDX-License-Identifier: GPL-2.0-or-later
"""What waits for the person, in one shape: a projection over asks, decisions and new work.

Nothing is stored here. Each source keeps its own lifetime and its own rules (asks live while their hook holds a
connection, decisions and new work are on disk), and an answer goes to that source's own op: interaction.answer in
Hubd only dispatches. Ids keep their source as a prefix: "a:" an ask, "d-" a decision, "w:" new work.

Every row is shown only to a login. What a session wrote in it (a why, a question, a suggestion's notes) stays the
session's words, marked so on the card.
"""
from __future__ import annotations

import time

from .agents import SCREENS, screen_of
from .decisions import EYE_TEST, REQUEST_LIFE

KINDS = ("permission", "question", "decision", "suggestion", "result")
STATUSES = ("pending", "allowed", "always", "denied", "answered", "started", "dismissed", "terminal", "timeout", "ended")
# Where a page says an answer came from. A claim, checked against the list and shown as such, never trusted for anything.
WHERE = (*SCREENS, "Needs you", "SessionView")
ASK_STATUS = {"pending": "pending", "allowed": "allowed", "always": "always", "denied": "denied", "answered": "answered",
              "terminal": "terminal", "timeout": "timeout", "stopped": "ended"}
WORK_WAITS = ("offered", "planned", "done", "failed")  # what the old Needs you counted
WORK_RUNS = ("planning", "starting", "running", "started")
NO_ANSWER = "nobody answered in time"  # decisions.current_state's words for a request that ran out
OBJECT_KIND = {"issue": "issue", "pr": "pr", "run": "run"}
# Seconds a settled ask or piece of new work stays in the list, for "handled in this view" and the Settled filter.
# Ended decisions stay as decisions.list keeps them (the last 200): they were the Decisions page's record.
SETTLED_FOR = 24 * 3600


def _persona(agent: dict | None) -> dict | None:
    if not agent:
        return None
    return {"id": agent.get("persona"), "name": agent.get("persona_name") or agent.get("persona"),
            "initials": agent.get("initials"), "family": agent.get("family"), "ended": bool(agent.get("ended"))}


def _session_items(agent: dict | None) -> list[dict]:
    kind = OBJECT_KIND.get((agent or {}).get("object"))
    if not kind:
        return []
    return [{"kind": kind, "repo": c["repo"], "number": c["number"]} for c in agent.get("covers") or ()]


def _row(id_, kind, status, session, agent, items, made, now, handled, detail, settled=None) -> dict:
    """settled: when it stopped waiting, for sorting what was handled. waited: how long it has waited, while it does."""
    pending = status == "pending"
    return {"id": id_, "kind": kind, "status": status, "blocking": pending and kind in ("permission", "question"),
            "session": session, "persona": _persona(agent), "items": items, "made": made,
            "waited": max(0, round(now - made)) if pending else 0, "settled": None if pending else settled or made,
            "handled": handled, "detail": detail}


def from_ask(view: dict, now: float) -> dict:
    status = ASK_STATUS.get(view["state"], "ended")
    handled = view.get("handled")
    if handled is None and status == "terminal":
        handled = {"by": "terminal", "where": "terminal", "at": view.get("answered_at")}
    agent = view.get("agent")
    made = view["made"] if "made" in view else now - view.get("waited", 0)
    return _row(f"a:{view['id']}", view["kind"], status, view["session"], agent, _session_items(agent), made, now, handled, view,
                view.get("answered_at"))


def decision_status(view: dict) -> str:
    state = view["state"]
    if state == "requested":
        return "pending"
    if state in ("current", "using"):
        return "allowed"
    if view.get("asked_by") and not view.get("approved"):  # asked for, and never yours: you said no, or nobody answered
        return "timeout" if view.get("why_ended") == NO_ANSWER else "denied"
    return "ended"


def decision_left(view: dict, now: float) -> dict:
    ends, left = view.get("ends") or {}, {}
    if "runs" in ends:
        left["runs"] = ends["runs"]
    if "until" in ends:
        left["hours"] = round(max(0.0, ends["until"] - now) / 3600, 1)
    return left


def from_decision(view: dict, agents: dict, now: float) -> dict:
    scope = view["scope"]
    status = decision_status(view)
    asked_by = view.get("asked_by")
    items = [{"kind": "pr", "repo": scope["repo"], "number": scope["number"]}] if view["kind"] == "merge" else []
    detail = {**view, "decision_kind": view["kind"], "left": decision_left(view, now),
              "eye_test": view["kind"] == "go" and EYE_TEST in scope.get("actions", ()), "head": scope.get("head")}
    return _row(view["id"], "decision", status, asked_by, agents.get(asked_by), items, view["made"], now, view.get("handled"), detail,
                view.get("ended") or view.get("approved"))


def work_status(record: dict) -> str:
    state = record["state"]
    if state in WORK_WAITS:
        return "pending"
    if state in WORK_RUNS:
        return "started"
    if state == "filed":
        return "answered"
    return "dismissed"  # dismissed, discarded


def from_work(record: dict, agents: dict, objects: dict, now: float) -> dict:
    status = work_status(record)
    has_drafts = bool(record.get("drafts")) and record["state"] in ("done", "filed", "dismissed", "discarded")
    kind = "result" if has_drafts else "suggestion"
    by = record.get("by")
    session = None if by == "you" else by
    agent = agents.get(session) if session else None
    items = []
    if record.get("number"):
        item_kind = OBJECT_KIND.get(objects.get(record.get("action")), "issue")
        items = [{"kind": item_kind, "repo": record["repo"], "number": n} for n in [record["number"], *record.get("also_numbers", ())]]
    detail = {**record, "result_type": "drafts" if kind == "result" else None}
    return _row(f"w:{record['id']}", kind, status, session, agent, items, record["made"], now, record.get("handled"), detail,
                (record.get("handled") or {}).get("at") or record.get("moved"))


def wanted(record: dict) -> bool:
    """New work that is or was an interaction: anything waiting, offered by a session, with drafts, or handled from a card.
    Work you started yourself and is still running is a session, not a question for you."""
    return record["state"] in WORK_WAITS or record.get("by") != "you" or bool(record.get("drafts")) or bool(record.get("handled"))


def project(asks: dict, decisions: list[dict], work: list[dict], agents: dict, objects: dict, session=None, now=None) -> dict:
    """The list the page shows. Pending first, oldest first; settled rows of the last day after, newest first."""
    now = time.time() if now is None else now
    rows = [from_ask(v, now) for v in [*asks["open"], *asks["answered"]]]
    rows += [from_decision(v, agents, now) for v in decisions]
    rows += [from_work(r, agents, objects, now) for r in work if wanted(r)]
    if session is not None:
        rows = [r for r in rows if r["session"] == session]
    pending = sorted((r for r in rows if r["status"] == "pending"), key=lambda r: r["made"])
    grants = sorted((r for r in rows if r["kind"] == "decision" and r["status"] == "allowed"), key=lambda r: r["made"])
    standing = {g["id"] for g in grants}
    settled = sorted((r for r in rows if r["status"] != "pending" and r["id"] not in standing
                      and (r["kind"] == "decision" or now - r["settled"] < SETTLED_FOR)),
                     key=lambda r: r["settled"], reverse=True)
    counts = {"pending": len(pending), "blocking": sum(r["blocking"] for r in pending),
              "by_kind": {k: sum(r["kind"] == k for r in pending) for k in KINDS},
              "longest_wait": max((r["waited"] for r in pending), default=0)}
    return {"items": [*pending, *settled], "counts": counts, "grants": grants}


def check_where(where) -> str | None:
    if where is None:
        return None
    where = screen_of(where)
    if where not in WHERE:
        raise ValueError(f"where is one of {', '.join(WHERE)}")
    return where


__all__ = ["KINDS", "STATUSES", "WHERE", "project", "check_where", "REQUEST_LIFE"]
