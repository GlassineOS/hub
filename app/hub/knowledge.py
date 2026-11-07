# SPDX-License-Identifier: GPL-2.0-or-later
"""Knowledge: one search over the docs index and the work store, and how far each index is.

A view over the two indexes there are, not a third one: the docs search (docsearch.py) and the work store's search
(GitHub.work_search). Code is a domain the page names but can't search yet (008 FR-002). Each domain fails on its own,
so a missing docs index still leaves the work items to search.
"""
from __future__ import annotations

import asyncio
import re
import time

from .github import BadRequest, _full

DOMAINS = ("docs", "work", "code")
PLANNED = ("code",)  # 008 FR-002: shown, and never searched
MODES = ("meaning", "exact")
MAX_QUERY = 500
MAX_REPOS = 10
DOCS_K = 8
WORK_K = 20
WORK_EXACT_K = 50  # all the work store gives at once
# 008 FR-006: below this, a search by meaning found nothing good, and the page offers research instead. A hit's score is
# the cosine of its passage and the query, in both indexes (the docs' own score fuses ranks, at most 2/61, and isn't
# used); a hit under a third of the way is a guess at best. The two indexes embed with different models, so the same
# cosine isn't quite the same match in each. A search by exact words has no score to judge: a hit has every word, so
# any hit is a good one.
GOOD_SCORE = 0.3
SNIPPET = 400


def _good(hit: dict) -> bool:
    """A hit scored by meaning clears GOOD_SCORE; one found only by its words (the work store has no model yet, or only
    the docs' word index found it) has to have every word, as in an exact search: a share of the words is no measure of
    an answer."""
    return hit["score"] >= GOOD_SCORE if hit["score"] is not None else hit["words"] >= 1.0


def _rank(hit: dict) -> tuple:
    """Best first: a hit with a meaning score above any without one, whose share of the words is on another scale."""
    return (hit["score"] is None, -(hit["score"] or 0), -(hit["words"] or 0))


def _words(query: str) -> list[str]:
    return [w for w in re.findall(r"\w+", query.lower()) if len(w) > 1]


def _utf16(text: str) -> list[int]:
    """For each code point offset, the offset in UTF-16 units, which is how the page's JavaScript slices text."""
    out, at = [0], 0
    for ch in text:
        at += 2 if ord(ch) > 0xFFFF else 1
        out.append(at)
    return out


def marks(text: str, query: str) -> list[list[int]]:
    """Where the query's words are in text, as [start, end) in UTF-16 units, merged. A short word only as a whole word
    (as the work store matches it), a longer one anywhere."""
    spans = []
    for word in set(_words(query)):
        pattern = re.escape(word) if len(word) > 2 else rf"\b{re.escape(word)}\b"
        spans += [[m.start(), m.end()] for m in re.finditer(pattern, text, re.IGNORECASE)]
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    if merged and not text.isascii():
        units = _utf16(text)
        merged = [[units[a], units[b]] for a, b in merged]
    return merged


def _found(word: str, low: str) -> bool:
    return bool(re.search(rf"\b{re.escape(word)}\b", low)) if len(word) <= 2 else word in low


def _share(text: str, query: str) -> float:
    """How many of the query's words text has, as the work store counts them."""
    words, low = _words(query), text.lower()
    return round(sum(_found(w, low) for w in words) / max(len(words), 1), 3)


def _has_every_word(text: str, query: str) -> bool:
    low = text.lower()
    return all(_found(w, low) for w in _words(query))


def _cut(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= SNIPPET else f"{text[:SNIPPET]}…"


def _domains(value) -> list[str]:
    asked = [d for d in (value or "docs,work").split(",") if d]
    for d in asked:
        if d not in DOMAINS:
            raise BadRequest(f"not a domain: {d[:40]}")
        if d in PLANNED:
            raise BadRequest(f"{d} isn't indexed yet: it's planned")
    if not asked or len(set(asked)) != len(asked):
        raise BadRequest("choose each domain once, and at least one")
    return asked


def _repos(value, readable: set[str]) -> list[str]:
    asked = [r for r in (value or "").split(",") if r]
    if len(asked) > MAX_REPOS or len(set(asked)) != len(asked):
        raise BadRequest(f"at most {MAX_REPOS} different repositories")
    for name in asked:
        _full(name)
        if name not in readable:  # 008 FR-010: only what the host login reads
            raise BadRequest(f"{name} isn't a repository the hub can read")
    return asked


def _docs_title(h: dict) -> str:
    return h["title"] + (f" › {h['heading']}" if h.get("heading") and h.get("heading") != h["title"] else "")


async def _docs(docs, query: str, mode: str) -> list[dict]:
    if mode == "exact":  # every passage with every word, not only those the search ranks high (008 FR-003)
        found = await docs.exact(query, lambda h: _has_every_word(f"{_docs_title(h)}\n{h.get('text') or ''}", query), DOCS_K)
    else:
        found = await docs.search(query, DOCS_K)
    rows = []
    for h in found.get("results", []):
        text, title = h.get("text") or "", _docs_title(h)
        snippet = _cut(text)
        meaning = h.get("meaning")
        rows.append({"domain": "docs", "kind": "docs", "title": title, "score": meaning, "words": _share(f"{title}\n{text}", query),
                     "snippet": snippet, "marks": marks(snippet, query), "title_marks": marks(title, query), "link": h["url"],
                     "repo": None, "by": "meaning" if meaning is not None else "words"})
    return rows[:DOCS_K]


async def _work(github, query: str, mode: str, repos: list[str], open_only: bool, readable: set[str]) -> list[dict]:
    state = "open" if open_only else None
    # An exact search keeps only hits with every word, so it asks for as many as the work store gives, not the first few.
    k = WORK_EXACT_K if mode == "exact" else WORK_K
    asks = [github.work_search(query, None, r, state, k) for r in repos] or [github.work_search(query, None, None, state, k)]
    found = [row for reply in await asyncio.gather(*asks) for row in reply["results"]]
    rows = []
    for r in found:
        if r["repo"] not in readable:
            continue
        # The work store counts the words on the whole passage; what it returns is cut to 400 characters.
        if mode == "exact" and (r.get("words") or 0) < 1.0:
            continue
        meaning = r.get("meaning")
        snippet = _cut(r.get("passage") or "")
        rows.append({"domain": "work", "kind": r["kind"], "title": r["title"], "score": meaning, "words": r.get("words") or 0,
                     "snippet": snippet, "marks": marks(snippet, query), "title_marks": marks(r["title"], query), "link": r["url"],
                     "by": "meaning" if meaning is not None else "words", "repo": r["repo"], "number": r["number"], "state": r["state"]})
    rows.sort(key=_rank)
    return rows[:WORK_K]


async def search(docs, github, query, mode="meaning", domains=None, repos=None, open_only=False) -> dict:
    """008 FR-001-FR-004, FR-006, FR-010. Each domain is searched on its own; one that fails says why and the rest stand."""
    query = (query or "").strip()
    if not query:
        raise BadRequest("a search needs words")
    if len(query) > MAX_QUERY:
        raise BadRequest(f"a search is at most {MAX_QUERY} characters")
    if mode not in MODES:
        raise BadRequest(f"mode is {' or '.join(MODES)}")
    if mode == "exact" and not _words(query):  # or every hit would have "every word"
        raise BadRequest("an exact search needs a word of two letters or more")
    asked = _domains(domains)
    readable = {r["name"] for g in (await github.overview())["groups"] for r in g["repos"]}
    chosen = _repos(repos, readable)
    jobs = {"docs": lambda: _docs(docs, query, mode),
            "work": lambda: _work(github, query, mode, chosen, open_only, readable)}
    replies = await asyncio.gather(*(jobs[d]() for d in asked), return_exceptions=True)
    results, states = [], []
    for domain, reply in zip(asked, replies):
        if isinstance(reply, Exception):
            states.append({"id": domain, "ok": False, "error": str(reply) or type(reply).__name__})
        else:
            states.append({"id": domain, "ok": True, "count": len(reply)})
            results += reply
    results.sort(key=_rank)
    good = bool(results) if mode == "exact" else any(_good(x) for x in results)
    return {"query": query, "mode": mode, "results": results, "domains": states, "good": good, "good_score": GOOD_SCORE}


async def indexes(docs, github) -> list[dict]:
    """008 FR-009: each index with its state and age, and what the page can do about it."""
    now = time.time()
    try:
        d = await docs.status()
        run = d.get("latest_run") or {}
        state = {"current": "ready", "stale": "ready", "building": "indexing", "failed": "failed"}.get(d.get("state"), "failed")
        words = {"current": "matches the docs head", "stale": "behind the docs head: no docs run is active",
                 "building": "the docs CI is publishing the head", "failed": "the docs CI failed: search still uses the published index"}
        docs_row = {"id": "docs", "state": state, "stale": d.get("state") == "stale", "says": words.get(d.get("state"), d.get("state")),
                    "age": run.get("createdAt"), "size": d.get("chunks"), "action": "reindex",
                    "can_act": d.get("state") in ("stale", "failed")}
    except Exception as e:  # no index here, or GitHub didn't answer: say so, and go on
        docs_row = {"id": "docs", "state": "failed", "stale": False, "says": f"can't be read: {e}", "age": None, "size": None,
                    "action": "reindex", "can_act": False}
    w = github.work_status()
    if not w.get("enabled"):
        work_row = {"id": "work", "state": "failed", "stale": False, "says": "the work store isn't set up", "age": None, "size": None,
                    "action": None, "can_act": False}
    else:
        synced = w.get("synced_at")
        state = "indexing" if w.get("running") or not w.get("ready") else "failed" if w.get("error") else "ready"
        says = w["error"] if w.get("error") else "ingesting now" if w.get("running") else "not ingested yet" if not w.get("ready") else "ingested"
        counts = w.get("counts") or {}
        work_row = {"id": "work", "state": state, "stale": False, "says": str(says)[:300],
                    "age": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(synced)) if synced else None,
                    "size": sum(v for k, v in counts.items() if k in ("issue", "pr") and isinstance(v, int)) if isinstance(counts, dict) else None,
                    "action": "sync", "can_act": not w.get("running"), "seconds": round(now - synced) if synced else None}
    code_row = {"id": "code", "state": "planned", "stale": False, "says": "not indexed yet", "age": None, "size": None,
                "action": None, "can_act": False}
    return [docs_row, work_row, code_row]


__all__ = ["search", "indexes", "marks", "DOMAINS", "PLANNED", "GOOD_SCORE"]
