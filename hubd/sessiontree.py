# SPDX-License-Identifier: GPL-2.0-or-later
"""Sessions › Running as a tree (spec 004, FR-012 to FR-015, FR-024): every session placed under its owner by the managing
entry that started it, with the rounds it served, its liveness, its state and its items.

Two halves. `collect` reads what the hub keeps on disk (each session's folder, its machine, the machine log's managed
starts, returns and ends) and makes one flat node per session. `arrange` is pure: it groups the nodes under their owners'
entries, folds earlier rounds, decides which ended sessions stay in view, and orders the roots. The page builds nothing of
its own but rows.

Reads only, as the list is polled: no machine is made or saved, no usage is banked, nothing is asked of GitHub. The items'
states beyond what hubd knows (draft, checks, review) are joined in by the app, from its work store.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from . import machine, usage
from .handoff import conversations
from .instances import FILE as MACHINE_FILE
from .instances import Instance, MachineError, usage_of

log = logging.getLogger("hubd.sessiontree")

LIVENESS = ("working", "idle", "waits", "stopped", "ended")
STEWARD_PERSONA = "steward"
MAINTAINER_PERSONA = "repo-maintainer"
ENDED_FILE = "ended"
IDLE_FILE = "idle"
WAITING_FILE = "waiting"
STARTED, RETURNED, ENDED = "hub:managed.start", "hub:managed.return", "hub:managed.end"
MAX_EVENTS = 2000  # managed events read per owner: the newest, enough for many rounds of every entry


# ---- reading -------------------------------------------------------------------------------------------------------------

def _read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _instance(directory: Path) -> Instance | None:
    raw = _read_json(directory / MACHINE_FILE)
    if not isinstance(raw, dict):
        return None
    try:
        inst = Instance.from_json(raw)
        inst.definition()
    except (MachineError, ValueError, KeyError, TypeError, machine.DefinitionError):
        return None
    return inst


def _cost(directory: Path, inst: Instance | None) -> float | None:
    """What the session cost as banked per state (its outermost states, which count those inside), or what its status line
    says when nothing is banked. None when neither says: never 0 for not known."""
    banked = usage_of(directory)
    if banked and inst is not None:
        d = inst.definition()
        tops = [v for s, v in banked.items() if s in d.states and d.states[s].parent is None]
        if tops:
            return round(sum(tops), 4)
    status = usage.read_status(directory)
    said = usage._cost(status) if isinstance(status, dict) else None
    return round(said, 4) if isinstance(said, (int, float)) else None


def _entry_states(d: machine.Definition) -> dict[str, list[str]]:
    """Each entry name with the states that name it, in the definition's order."""
    out: dict[str, list[str]] = {}
    for sid, s in d.states.items():
        for m in s.manages:
            out.setdefault(m.name, [])
            if sid not in out[m.name]:
                out[m.name].append(sid)
    return out


def entries_of(inst: Instance) -> list[dict]:
    """Every managing entry of the instance's workflow, in force or not (FR-013): its configuration from the definition, the
    states that name it, whether it holds where the instance is now, and the round of the state it runs in."""
    d = inst.definition()
    here = {m.name: sid for sid, m in machine.managed_of(d, inst.state)}
    states = _entry_states(d)
    out, seen = [], set()
    for sid, s in d.states.items():
        for m in s.manages:
            if m.name in seen:
                continue
            seen.add(m.name)
            owner_state = here.get(m.name, sid)
            if m.name in here:  # the definition in force there (a child's entry of the same name stands for its parent's)
                m = next(x for _s, x in machine.managed_of(d, inst.state) if x.name == m.name)
            kept = inst.managed.get(m.name) or {}
            out.append({"name": m.name, "persona": m.persona, "workflow": m.workflow, "start": m.start, "when": " ".join(m.when.split()),
                        "max": m.max, "reuse": m.reuse, "on_exit": m.on_exit, "states": states.get(m.name, [sid]),
                        "in_force": m.name in here, "round": int(inst.counters["rounds"].get(owner_state, 0)),
                        "returns": sorted(m.returns), "child": (kept.get("child") or {}).get("name")})
    return out


def _exit_words(e: machine.Exit) -> str:
    bits = [f"→ {e.to}"]
    if e.when.strip():
        bits.append(f"when {' '.join(e.when.split())}")
    if e.requires:
        bits.append("requires " + ", ".join(e.requires))
    if e.move == "on-request":
        bits.append("on request")
    if e.approve and e.approve != "none":
        bits.append(f"approve: {e.approve}")
    return " ".join(bits[:2]) + "".join(f" · {b}" for b in bits[2:])


def strip_words(inst: Instance | None, cards: int, running_under: dict[str, list[str]], live: str) -> tuple[str, str]:
    """What the session waits for and its next exit, a line each for the tile strip, from the definition and the hub's own
    records (nothing a session wrote)."""
    if inst is None:
        return ("you" if cards else "nothing the hub tracks", "")
    d = inst.definition()
    st = d.states.get(inst.state)
    exits = [e for sid in machine.ancestors(d, inst.state) for e in d.states[sid].exits]
    nxt = _exit_words(exits[0]) if exits else (f"stays in {inst.state} (one state)" if len(d.states) == 1 else
                                                f"nothing: {inst.state} is final" if st and st.final else "no exit leaves here")
    if inst.pending:
        return (f"your confirm: → {inst.pending.get('to')}", nxt)
    if cards:
        return (f"your answer to {cards} card{'' if cards == 1 else 's'}", nxt)
    if live == "waits":
        return ("you, in its terminal", nxt)
    if running_under:
        return ("; ".join(f"its {entry} ({', '.join(names)})" for entry, names in running_under.items()), nxt)
    if st and st.final:
        return ("nothing: it is in a final state", nxt)
    if live == "working":
        return ("nothing: it is working", nxt)
    held = [r for e in exits[:1] for r in e.requires]
    return ((f"{', '.join(held)}" if held else "its turn, or a signal its exits wait on"), nxt)


def _returned_words(checks: dict) -> str:
    facts = checks.get("returns") if isinstance(checks.get("returns"), dict) else {}
    bits = [str(v) for v in facts.values()]
    bits += [f"{n} {k}" for k, n in checks.items() if k not in ("from", "returns") and isinstance(n, int) and not isinstance(n, bool) and n]
    return " · ".join(bits) or "handed back"


def cards_by_session(items: list[dict]) -> dict[str, int]:
    """The open Needs-you cards of each session (the header's badge is their sum): asks, decisions (a move's confirm, a start
    approval, a design to look at, a stuck start, a stall), results and new work, and a proposed workflow change, which is
    counted with the session that proposed it."""
    out: dict[str, int] = {}
    for r in items:
        if r.get("status") != "pending":
            continue
        who = r.get("session")
        detail = r.get("detail") or {}
        if not who and detail.get("decision_kind") == "workflow.change":
            who = (detail.get("scope") or {}).get("proposed_by")
        if isinstance(who, str) and who:
            out[who] = out.get(who, 0) + 1
    return out


def collect(agents, live_names: set[str], cards: dict[str, int], now: float | None = None) -> dict:
    """One node per session folder, plus the events of each owner from the machine log. Read only."""
    now = time.time() if now is None else now
    root = Path(agents.sessions)
    nodes: dict[str, dict] = {}
    events: dict[str, list[dict]] = {}
    for directory in sorted(root.iterdir()) if root.is_dir() else ():
        record = _read_json(directory / "session.json")
        if not isinstance(record, dict) or not isinstance(record.get("config"), dict):
            continue
        name = directory.name
        try:
            nodes[name] = _node(agents, name, directory, record, live_names, cards.get(name, 0), now)
        except Exception:  # noqa: BLE001: one unreadable session leaves the rest of the tree
            log.exception("%s: its tree node couldn't be made", name)
            continue
        if nodes[name].get("_entries"):
            try:
                events[name] = agents.machines.log.managed_events(conversations(record), MAX_EVENTS)
            except Exception:  # noqa: BLE001: the tree shows without its rounds
                log.exception("%s: its managed events couldn't be read", name)
                events[name] = []
    return {"nodes": nodes, "events": events, "now": now}


def _node(agents, name: str, directory: Path, record: dict, live_names: set[str], cards: int, now: float) -> dict:
    config = record["config"]
    agent = agents.describe(name) or {}
    inst = _instance(directory)
    ended_file = directory / ENDED_FILE
    ended = ended_file.exists()
    running = name in live_names and not ended
    if running:
        live = "waits" if cards or ((directory / WAITING_FILE).exists() and not (directory / IDLE_FILE).exists()) \
            else "idle" if (directory / IDLE_FILE).exists() else "working"
    else:
        live = "ended" if ended else "stopped"  # its terminal is gone and it didn't end: a reboot or a crash, resumable
    created = record.get("created") if isinstance(record.get("created"), (int, float)) else None
    ended_at = None
    if ended:
        try:
            ended_at = ended_file.stat().st_mtime
        except OSError:
            ended_at = None
    owned = record.get("owner") if isinstance(record.get("owner"), dict) else None
    covers = [{"kind": record.get("object") if record.get("object") in ("issue", "pr") else "issue", "repo": c["repo"], "number": c["number"]}
              for c in agent.get("covers") or () if isinstance(c, dict) and c.get("repo") and c.get("number")]
    if not covers and record.get("object") == "repo" and config.get("repo"):
        covers = [{"kind": "repo", "repo": config["repo"], "number": None}]
    covered = {(c["repo"], c["number"]) for c in covers}
    try:
        prs = agents.known_prs(name) or []
    except Exception:  # noqa: BLE001: shown only
        prs = []
    holds = [{"kind": "pr", "repo": p["repo"], "number": p["number"], "state": p.get("state")} for p in prs
             if isinstance(p, dict) and (p.get("repo"), p.get("number")) not in covered]
    for c in covers:
        if c["kind"] == "pr":
            seen = next((p for p in prs if (p.get("repo"), p.get("number")) == (c["repo"], c["number"])), None)
            c["state"] = seen.get("state") if seen else None
    summary = agent.get("machine")
    pending_to = inst.pending.get("to") if inst is not None and inst.pending else None
    persona = config.get("persona")
    return {
        "name": name, "plain": False, "session_id": record.get("session_id"), "conversations": conversations(record),
        "persona": {"id": persona, "name": agent.get("persona_name") or persona, "initials": agent.get("initials"), "family": agent.get("family")},
        "model": config.get("model"), "title": record.get("title"), "action": config.get("action"), "object": record.get("object"),
        "origin": record.get("origin"), "started_by": record.get("started_by") if isinstance(record.get("started_by"), str) else None,
        "owner": owned.get("name") if owned and isinstance(owned.get("name"), str) else None,
        "owner_sid": owned.get("session_id") if owned else None, "entry": owned.get("entry") if owned else None,
        "child_round": owned.get("round") if owned else None,
        "machine": summary, "version": inst.version if inst is not None else None, "pending_to": pending_to,
        "rounds": {k: int(v) for k, v in inst.counters["rounds"].items()} if inst is not None else {},
        "steward": persona == STEWARD_PERSONA, "maintainer": persona == MAINTAINER_PERSONA,
        "live": live, "running": name in live_names, "cards": cards,
        "items": [{**c, "role": "covers"} for c in covers] + [{**p, "role": "holds"} for p in holds],
        "started": created, "ended_at": ended_at,
        "seconds": int(max(0.0, (ended_at or now) - created)) if created is not None else None,
        "cost": _cost(directory, inst),
        "_inst": inst, "_entries": entries_of(inst) if inst is not None else [],
    }


def plain_node(shell: dict) -> dict:
    """A plain shell: no persona, no workflow (FR-012's last group)."""
    return {"name": shell["name"], "plain": True, "persona": None, "live": "idle" if not shell.get("attached") else "working",
            "running": True, "cards": 0, "items": [], "cwd": shell.get("cwd"), "machine": None, "owner": None, "entry": None,
            "started_by": None, "conversations": [], "started": None, "seconds": None, "cost": None, "_inst": None, "_entries": []}


# ---- arranging -----------------------------------------------------------------------------------------------------------

def _events_by_child(events: list[dict]) -> dict[str, dict]:
    """From an owner's managed events: per child, the rounds it served (state and round, a pair per start), whether it was
    ever resumed, its entry, and what it last returned."""
    out: dict[str, dict] = {}
    for e in events:
        checks = e.get("checks") if isinstance(e.get("checks"), dict) else {}
        if e.get("signal") == STARTED and isinstance(checks.get("started"), str):
            row = out.setdefault(checks["started"], {"served": [], "resumed": False, "entry": None, "returned": None, "returned_at": None})
            rnd = checks.get("round") if isinstance(checks.get("round"), int) and not isinstance(checks.get("round"), bool) else None
            pair = [e.get("state"), rnd]
            if not row["served"] or row["served"][-1] != pair:
                row["served"].append(pair)
            row["resumed"] = row["resumed"] or checks.get("resumed") is True
            proposal = e.get("proposal") or ""
            if proposal.startswith("start "):
                row["entry"] = proposal[len("start "):]
            row["returned"] = None  # a new round: what it returned before doesn't stand for this one
        elif e.get("signal") == RETURNED and isinstance(checks.get("from"), str):
            row = out.setdefault(checks["from"], {"served": [], "resumed": False, "entry": None, "returned": None, "returned_at": None})
            row["returned"] = _returned_words(checks)
            row["returned_at"] = e.get("at")
            row["verdict"] = (checks.get("returns") or {}).get("verdict") if isinstance(checks.get("returns"), dict) else None
            proposal = e.get("proposal") or ""
            if proposal.endswith(" returned"):
                row["entry"] = row["entry"] or proposal[:-len(" returned")]
    return out


def _last_round(served: list) -> int | None:
    rounds = [r for _s, r in served if isinstance(r, int)]
    return rounds[-1] if rounds else None


def _category(n: dict) -> str:
    if n.get("plain"):
        return "shells"
    if n.get("steward"):
        return "steward"
    if n.get("maintainer"):
        return "maintainers"
    m = n.get("machine") or {}
    return "quick" if m.get("one_state") else "items"


def _quick_key(n: dict) -> str:
    covers = [i for i in n.get("items") or () if i.get("role") == "covers"]
    if covers:
        c = covers[0]
        return c["repo"] if c.get("number") is None else f"{c['repo']}#{c['number']}"
    return "the project"


def arrange(collected: dict) -> dict:
    """The tree: each owner's entries with this round's sessions and the earlier ones folded, which ended sessions stay in
    view, and the roots in FR-012's order. Pure: everything comes in `collected`."""
    nodes: dict[str, dict] = {k: dict(v) for k, v in collected["nodes"].items()}
    events = collected.get("events") or {}
    # where each session hangs: under its owner, when the owner is a session here and the conversation it names is one of the
    # owner's; started_by alone places nothing, as no managing entry started it (it stays a root and says who started it)
    for n in nodes.values():
        o = nodes.get(n.get("owner") or "")
        n["parent"] = n["owner"] if o is not None and (n.get("owner_sid") in o.get("conversations", ()) or not n.get("owner_sid")) else None
    by_owner: dict[str, list[str]] = {}
    for name, n in nodes.items():
        if n["parent"]:
            by_owner.setdefault(n["parent"], []).append(name)
    verdicts: dict[str, tuple[float, str]] = {}
    for owner, names in by_owner.items():
        seen = _events_by_child(events.get(owner) or [])
        for child in names:
            c = nodes[child]
            got = seen.get(child) or {}
            c["served"] = got.get("served") or ([[None, c["child_round"]]] if isinstance(c.get("child_round"), int) else [])
            c["resumed"] = bool(got.get("resumed"))
            c["returned"] = got.get("returned")
            c["round"] = _last_round(c["served"])
            if got.get("verdict"):
                for it in c["items"]:
                    if it["kind"] == "pr":
                        key = f"{it['repo']}#{it['number']}"
                        at = got.get("returned_at") or 0
                        if key not in verdicts or verdicts[key][0] <= at:
                            verdicts[key] = (at, got["verdict"])
    # a stopped child of an entry that resumes, and is the one it resumes, is "stopped" (resumable), not ended
    for owner, names in by_owner.items():
        o = nodes[owner]
        entries = {e["name"]: e for e in o.get("_entries") or ()}
        for child in names:
            c = nodes[child]
            e = entries.get(c.get("entry"))
            if c["live"] == "ended" and e and e["reuse"] == "resume" and e.get("child") == child and o["live"] != "ended":
                c["live"] = "stopped"
    # what still runs under a session, at any depth: an ended owner stays while anything under it runs
    def running_below(name: str, depth: int = 0) -> bool:
        if depth > 16:
            return False
        return any(nodes[k]["live"] != "ended" or running_below(k, depth + 1) for k in by_owner.get(name, ()))
    entries_out: dict[str, list[dict]] = {}
    for owner, n in nodes.items():
        defs = n.get("_entries") or []
        kids = by_owner.get(owner, [])
        if not defs and not kids:
            continue
        seen = _events_by_child(events.get(owner) or [])
        rows, named = [], set()
        for e in defs:
            named.add(e["name"])
            rows.append(_entry_row(e, [k for k in kids if nodes[k].get("entry") == e["name"]], nodes, n, seen))
        stray = sorted({nodes[k].get("entry") or "" for k in kids} - named)
        for name in stray:  # an entry the owner's workflow no longer has (a newer version), or a child with no entry
            rows.append(_entry_row({"name": name or "other", "persona": None, "workflow": None, "start": None, "when": "", "max": None,
                                    "reuse": None, "on_exit": None, "states": [], "in_force": False, "round": 0, "returns": [],
                                    "child": None, "gone": True},
                                   [k for k in kids if (nodes[k].get("entry") or "") == name], nodes, n, seen))
        notes = (collected.get("notes") or {}).get(owner) or {}
        for r in rows:
            r["note"] = notes.get(r["name"])
        entries_out[owner] = rows
    # FR-024: which ended sessions stay in view
    folded = {x["name"] for rows in entries_out.values() for r in rows for x in r["earlier"]}
    for name, n in nodes.items():
        if n["live"] != "ended":
            n["kept"] = True
            continue
        o = nodes.get(n.get("parent") or "")
        e = next((r for r in entries_out.get(n.get("parent") or "", ()) if r["name"] == n.get("entry")), None)
        latest = bool(e and e.get("latest") == name and n.get("returned") and o is not None and o["live"] != "ended")
        n["kept"] = bool(n.get("cards")) or latest or running_below(name)
        if name in folded:
            n["kept"] = n["kept"] and bool(n.get("cards"))
    # the strip's words, and what runs under each
    for name, n in nodes.items():
        under: dict[str, list[str]] = {}
        for r in entries_out.get(name, ()):
            names = [k for k in r["sessions"] if nodes[k]["live"] in ("working", "idle", "waits")]
            if names:
                under[r["name"]] = names
        n["waits_for"], n["next"] = ("", "") if n.get("plain") else strip_words(n.get("_inst"), n.get("cards", 0), under, n["live"])
    # roots, in FR-012's order: the Steward, repository maintainers, workflows started from an item, quick tasks by item, shells
    roots = [k for k, n in nodes.items() if not n["parent"]]
    order = {"steward": 0, "maintainers": 1, "items": 2, "quick": 3, "shells": 4}
    roots.sort(key=lambda k: (order[_category(nodes[k])], nodes[k].get("started") or 0, k))
    quick: dict[str, list[str]] = {}
    for k in roots:
        if _category(nodes[k]) == "quick":
            quick.setdefault(_quick_key(nodes[k]), []).append(k)
    out_nodes = {k: {f: v for f, v in n.items() if not f.startswith("_") and f not in ("conversations", "owner_sid", "child_round", "session_id")}
                 for k, n in nodes.items()}
    for k, n in nodes.items():
        out_nodes[k]["entries"] = entries_out.get(k, [])
    return {"nodes": out_nodes,
            "roots": [k for k in roots if _category(nodes[k]) in ("steward", "maintainers", "items")],
            "quick": [[key, names] for key, names in quick.items()],
            "shells": [k for k in roots if _category(nodes[k]) == "shells"],
            "verdicts": {k: v for k, (_at, v) in verdicts.items()},
            "ended_hidden": sum(1 for n in nodes.values() if n["live"] == "ended" and not n["kept"] and n["name"] not in folded)}


def _entry_row(e: dict, kids: list[str], nodes: dict, owner: dict, seen: dict) -> dict:
    """One entry of an owner (FR-013, FR-014): this round's sessions, each a row, and the earlier rounds' sessions of an entry
    that starts fresh, folded, with what each returned. A resumed session is one row however many rounds it served."""
    kids = sorted(kids, key=lambda k: (nodes[k].get("started") or 0, k))
    latest = e.get("child") if e.get("child") in kids else (kids[-1] if kids else None)
    latest_round = nodes[latest]["round"] if latest else None
    sessions, earlier = [], []
    for k in kids:
        c = nodes[k]
        older = c["round"] is not None and latest_round is not None and c["round"] < latest_round
        if e.get("reuse") == "fresh" and c["live"] == "ended" and k != latest and (older or latest_round is None):
            earlier.append({"name": k, "round": c["round"], "returned": c.get("returned"), "seconds": c.get("seconds"),
                            "cost": c.get("cost"), "persona": c.get("persona")})
        else:
            sessions.append(k)
    # sessions of earlier rounds whose folders are gone: from the owner's log, with their returns
    for name, got in seen.items():
        if name in nodes or got.get("entry") != e["name"] or e.get("reuse") != "fresh":
            continue
        earlier.append({"name": name, "round": _last_round(got.get("served") or []), "returned": got.get("returned"),
                        "seconds": None, "cost": None, "persona": None, "gone": True})
    earlier.sort(key=lambda x: (x["round"] if isinstance(x["round"], int) else -1, x["name"]))
    running = sum(1 for k in sessions if nodes[k]["live"] in ("working", "idle", "waits"))
    return {**{k: v for k, v in e.items() if k != "child"}, "sessions": sessions, "earlier": earlier, "running": running,
            "latest": latest, "note": None}
