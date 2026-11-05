# SPDX-License-Identifier: GPL-2.0-or-later
"""The queue view: open pull requests as sets, in order, from the work store and your decisions.

Only arranges. It merges, reviews and starts nothing, and what a pull request's text says stays that:
`Set:` and `Tested:` are its author's words, shown as what it says, and can't record anything.
"Approved" here is your merge decision, never a GitHub review, and the two stay in their own fields.
docs/workspace.md, "Merging across repositories", is the design.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

BLOCKER_LABEL = "blocks-merge"
_ORG = "GlassineOS"
_SET = re.compile(r"^[ \t]*(?:[-*][ \t]+)?Set:[ \t]*([A-Za-z0-9][A-Za-z0-9._/-]*),[ \t]*([0-9]{1,4})[ \t]+of[ \t]+([0-9]{1,4})[ \t]*\r?$", re.M)
_TESTED = re.compile(r"^[ \t]*(?:[-*][ \t]+)?Tested:[ \t]*(\S[^\r\n]*?)[ \t]*\r?$", re.M)
_LINK = re.compile(rf"https://github\.com/{_ORG}/([A-Za-z0-9._-]+)/issues/([0-9]+)"
                   rf"|(?<![\w/#&.-])(?:(?:{_ORG}/)?([A-Za-z0-9._-]+))?#([0-9]+)\b")
_CLOSING = re.compile(r"(?:^|[^\w-])(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):?[ \t]+$", re.I)
MERGED_WITHIN = timedelta(days=14)
MAX_NAMED = 3
MAX_TESTED = 200
MAX_WHY = 300
CHECKS = {"passing": "Passing", "failing": "Failing", "pending": "Still running", "none": "None reported"}
REVIEWS = {"APPROVED": "Approved by a reviewer", "CHANGES_REQUESTED": "Changes requested", "REVIEW_REQUIRED": "A review is required"}
MERGEABLE = {"CONFLICTING": "Has conflicts", "MERGEABLE": "No conflicts", "UNKNOWN": "GitHub hasn't worked this out"}


def declared_set(body: str | None) -> tuple[str, int, int] | None:
    """`Set: NAME, N of M`, the pull request's first such line, or None if it hasn't one that makes sense."""
    match = _SET.search(body or "")
    if not match:
        return None
    n, m = int(match[2]), int(match[3])
    return (match[1], n, m) if 1 <= n <= m else None


def tested_says(body: str | None) -> str:
    match = _TESTED.search(body or "")
    if not match:
        return "It doesn't say"
    words = match[1].strip()
    return f"It says: {words[:MAX_TESTED]}{'…' if len(words) > MAX_TESTED else ''}"


def links(body: str | None, repo: str) -> set[tuple[str, int]]:
    """What a pull request's text links to, as (repository, number) in lower case."""
    return {key for key, _ in _linked(body, repo)}


def says_it_fixes(body: str | None, repo: str) -> set[tuple[str, int]]:
    """The links with a closing word right before them, as in `Fixes #2`: the words GitHub closes an issue on."""
    return {key for key, closing in _linked(body, repo) if closing}


def _linked(body: str | None, repo: str):
    text = body or ""
    for match in _LINK.finditer(text):
        name, number = (match[1], match[2]) if match[1] else (match[3] or repo, match[4])
        before = text[text.rfind("\n", 0, match.start()) + 1:match.start()]
        yield (name.lower(), int(number)), bool(_CLOSING.search(before))


def _when(value) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def _merged_when(pr: dict) -> datetime | None:
    """Rows synced before the store kept mergedAt have their last change instead, which is at or after the merge."""
    return _when(pr.get("mergedAt")) or _when(pr.get("updatedAt"))


def _belongs(merged: dict, members: list[dict]) -> bool:
    """A set's name can be used again, so a merged pull request counts only if it merged around when this one began."""
    when = _merged_when(merged)
    opened = [t for t in (_when(pr.get("createdAt")) for pr in members) if t]
    return bool(when and opened and when >= min(opened) - MERGED_WITHIN)


def _blocker(issue: dict) -> dict:
    why = " ".join((issue.get("body") or "").split())
    return {"repo": issue["repo"], "number": issue["number"], "title": issue["title"], "url": issue.get("url"),
            "why": f"{why[:MAX_WHY]}{'…' if len(why) > MAX_WHY else ''}"}


def _approval(pr: dict, decisions: list[dict]) -> dict:
    """Your word on this head, in words. A decision for another head or base is said too, and doesn't count."""
    head, base = pr.get("headRefOid"), pr.get("baseRefName")
    current = asked = using = ended = None
    notes = []
    for d in decisions:  # newest first
        scope = d["scope"]
        if d["kind"] != "merge" or scope["repo"].lower() != pr["repo"].lower() or scope["number"] != pr["number"]:
            continue
        same_head = head == scope["head"]
        if d["state"] == "current":
            if not same_head:
                notes.append(f"Your approval {d['id']} is for head {scope['head'][:12]}, not this one, so it doesn't count.")
            elif scope.get("base") and scope["base"] != base:
                notes.append(f"Your approval {d['id']} is for merging into {scope['base']}, and this now targets {base}, so it doesn't count.")
            elif current is None:
                current = d
        elif d["state"] == "using":
            using = using or d
        elif d["state"] == "requested":
            if same_head:
                asked = asked or d
            else:
                notes.append(f"{d.get('asked_by') or 'A hub shell'} asked for head {scope['head'][:12]}, not this one.")
        elif same_head and ended is None and d["state"] == "ended":
            ended = d
    if using:
        result = {"state": "using", "id": using["id"], "says": "A merge is using your approval right now."}
    elif current:
        by = "" if current["scope"].get("session", "any") == "any" else f", for {current['scope']['session']}"
        result = {"state": "approved", "id": current["id"], "says": f"You approved this head{by}: {current.get('words') or 'no words kept'}"}
    else:
        result = {"state": "none", "id": None, "says": "You haven't approved this head."}
    if asked and not current and not using:
        notes.insert(0, f"{asked.get('asked_by') or 'A hub shell'} asks you to, in its own words, which aren't yours: {asked.get('why') or 'no reason given'}")
        result["asked"] = asked["id"]
    if ended and result["state"] == "none":
        notes.append(f"An earlier approval of this head ended: {ended.get('why_ended') or 'no reason kept'}.")
    return {**result, "notes": notes}


def _row(pr: dict, order, blockers: dict, decisions: list[dict]) -> dict:
    merged = pr["state"] == "MERGED"
    when = _merged_when(pr) if merged else None
    linked = links(pr.get("body"), pr["repo"])
    fixes = says_it_fixes(pr.get("body"), pr["repo"])
    return {"repo": pr["repo"], "number": pr["number"], "title": pr["title"], "url": pr.get("url"),
            "author": (pr.get("author") or {}).get("login") or "unknown", "state": pr["state"], "merged_on": when.date().isoformat() if when else None, "draft": pr.get("isDraft") is True,
            "branch": pr.get("headRefName"), "base": pr.get("baseRefName"), "head": pr.get("headRefOid"),
            "order": {"n": order[1], "m": order[2]} if order else None, "next": False,
            "tested": tested_says(pr.get("body")), "checks": CHECKS.get(pr.get("checks"), "Not known"),
            "mergeable": MERGEABLE.get(pr.get("mergeable"), "Not known"),
            "reviews": REVIEWS.get(pr.get("reviewDecision"), "No review decision"),
            "approval": None if merged else _approval(pr, decisions),
            "blockers": [] if merged else [b for key, b in blockers.items() if key in linked - fixes],
            "fixes": [] if merged else [b for key, b in blockers.items() if key in fixes]}


def _problems(rows: list[dict]) -> list[str]:
    """What the set's own lines don't agree on. The words say what's seen, and leave the rest to you."""
    said = [r["order"] for r in rows if r["order"]]
    if not said:
        return ["No pull request says its place: they share a branch name, and the order is yours to work out."]
    problems = []
    sizes = sorted({o["m"] for o in said})
    if len(sizes) > 1:
        problems.append(f"They don't agree on the set's size: {' or '.join(map(str, sizes))}.")
    places = [o["n"] for o in said]
    for n in sorted({n for n in places if places.count(n) > 1}):
        problems.append(f"More than one says it's number {n}.")
    missing = [n for n in range(1, sizes[-1] + 1) if n not in places]
    if missing:
        problems.append(f"Nothing in the work store says it's number {', '.join(map(str, missing))} of {sizes[-1]}.")
    if len(said) < len(rows):
        problems.append("Some share the branch name and don't say their place.")
    return problems


def _older(prs: list[dict]) -> list[str]:
    if not prs:
        return []
    named = ", ".join(f"{pr['repo']}#{pr['number']}" for pr in prs[:MAX_NAMED]) + (" and more" if len(prs) > MAX_NAMED else "")
    return [f"Older merged pull requests use this name too and don't count as part of this set: {named}."]


def _mark_next(rows: list[dict]) -> None:
    """The one to merge next, only where the lines are clear: every earlier place merged, no doubts."""
    said = [r for r in rows if r["order"]]
    places = [r["order"]["n"] for r in said]
    if not said or len(said) < len(rows) or len(set(places)) < len(places) or len({r["order"]["m"] for r in said}) > 1:
        return
    for n in range(1, said[0]["order"]["m"] + 1):
        row = next((r for r in said if r["order"]["n"] == n), None)
        if row is None or row["state"] not in ("MERGED", "OPEN"):
            return
        if row["state"] == "OPEN":
            row["next"] = True
            return


def arrange(open_prs: list[dict], merged_prs: list[dict], blocker_issues: list[dict], decisions: list[dict]) -> dict:
    """Pull requests with their bodies, as the work store keeps them, and decision.list's rows."""
    blockers = {(i["repo"].lower(), i["number"]): _blocker(i) for i in blocker_issues}
    declared = {(pr["repo"], pr["number"]): declared_set(pr.get("body")) for pr in open_prs}
    names: dict[str, list[dict]] = {}
    for pr in open_prs:
        said = declared[(pr["repo"], pr["number"])]
        names.setdefault(said[0] if said else pr.get("headRefName") or "", []).append(pr)
    sets, alone = [], []
    for name, members in sorted(names.items()):
        is_set = any(declared[(pr["repo"], pr["number"])] for pr in members) or (len({pr["repo"] for pr in members}) > 1 and name)
        if not is_set:
            alone += [_row(pr, None, blockers, decisions) for pr in members]
            continue
        rows = [_row(pr, declared[(pr["repo"], pr["number"])], blockers, decisions) for pr in members]
        older = []
        for pr in merged_prs:
            said = declared_set(pr.get("body"))
            if said and said[0] == name:
                if _belongs(pr, members):
                    rows.append(_row(pr, said, blockers, decisions))
                else:
                    older.append(pr)
        rows.sort(key=lambda r: (r["order"]["n"] if r["order"] else 1 << 30, r["repo"].lower(), r["number"]))
        _mark_next(rows)
        sets.append({"name": name, "rows": rows, "problems": _problems(rows) + _older(older)})
    alone.sort(key=lambda r: (r["repo"].lower(), r["number"]))
    linked = {(b["repo"].lower(), b["number"]) for r in [*alone, *(r for s in sets for r in s["rows"])] for b in r["blockers"] + r["fixes"]}
    return {"sets": sets, "alone": alone,
            "blockers": sorted(({**b, "linked": key in linked} for key, b in blockers.items()), key=lambda b: (b["repo"].lower(), b["number"]))}
