# SPDX-License-Identifier: GPL-2.0-or-later
"""The semantic doc search, and keeping its index in step with the docs repository.

The index is what the docs CI publishes with the site, so "updating the corpus" means
making sure that CI has run for the current commit of the docs repository. Searching
fetches a new index by itself when the published manifest changes.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

from .github import ORG, GitHub

log = logging.getLogger("hub.docs")
DOCS_REPO = "docs"
WORKFLOW = "docs.yml"
BASE = os.environ.get("HUB_DOCS_BASE", "https://docs.glassine.org/search/")
# A push starts the docs CI by itself; only step in when that evidently didn't happen.
STALE_GRACE = 900.0
CHECK_EVERY = 300.0
MANIFEST_TTL = 60.0


def _profile() -> str:
    wanted = os.environ.get("HUB_SEARCH_PROFILE")
    if wanted:
        return wanted
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return "static"
    return "transformer"


def _row(h) -> dict:
    """score is the fused rank (reciprocal ranks, at most 2/61), which orders hits but measures nothing; meaning is the
    cosine of the passage and the query, None when only the words found it."""
    return {"rank": h.rank, "title": h.chunk["title"], "heading": h.chunk["heading"], "score": round(h.score, 4),
            "meaning": None if h.vector_score is None else round(h.vector_score, 4), "url": h.url, "text": h.chunk["text"]}


class DocSearch:
    def __init__(self, github: GitHub, cache: Path | None = None, clock=time.monotonic,
                 loader=None):
        self.github = github
        self.cache = cache
        self._clock = clock
        self._load = loader or self._load_searcher
        self._searcher = None
        self._loaded_at = -MANIFEST_TTL
        self._lock = asyncio.Lock()
        self._stale_since = None
        self._dispatched_for = None

    def _load_searcher(self):
        from glassine_docs.client import Searcher, Site
        return Searcher(Site(BASE, cache=self.cache), _profile())

    async def _current(self):
        """The searcher, rebuilt when the published index changed."""
        async with self._lock:
            if self._searcher is None or self._clock() - self._loaded_at > MANIFEST_TTL:
                fresh = await asyncio.to_thread(self._load)
                self._searcher = fresh
                self._loaded_at = self._clock()
            return self._searcher

    async def search(self, query: str, k: int = 5) -> dict:
        if not query or not query.strip():
            return {"query": query, "results": []}
        searcher = await self._current()
        hits, seconds = await asyncio.to_thread(searcher.search, query, max(1, min(int(k), 20)))
        return {"query": query, "profile": searcher.profile, "commit": searcher.site.manifest["commit"],
                "ms": round(seconds * 1000, 1), "results": [_row(h) for h in hits]}

    async def exact(self, query: str, keep, k: int = 8) -> dict:
        """Every passage keep(row) accepts, not only the ones the search ranks near the top: those it ranks come first, in
        its order, then the rest in the order of the docs, with no score. keep sees the same row search gives."""
        searcher = await self._current()

        def run():
            hits, _ = searcher.search(query, 20)
            rows = [r for r in map(_row, hits) if keep(r)]
            seen = {(r["url"], r["heading"]) for r in rows}
            for c in searcher.chunks:
                if len(rows) >= k:
                    break
                row = {"rank": None, "title": c["title"], "heading": c["heading"], "score": None, "meaning": None,
                       "url": searcher.site.url(c["url"]), "text": c["text"]}
                if (row["url"], row["heading"]) not in seen and keep(row):
                    rows.append(row)
            return rows[:k]

        return {"query": query, "profile": searcher.profile, "commit": searcher.site.manifest["commit"],
                "results": await asyncio.to_thread(run)}

    async def status(self) -> dict:
        """How the published index compares with the docs repository and its CI."""
        searcher = await self._current()
        published = searcher.site.manifest["commit"]
        head = (await self.github.hubd.gh_json("api", f"repos/{ORG}/{DOCS_REPO}/commits/main"))["sha"]
        runs = await self.github.runs(DOCS_REPO, workflow=WORKFLOW, branch="main", limit=5)
        latest = runs[0] if runs else None
        active = next((r for r in runs if r["status"] != "completed"), None)
        if published == head:
            state = "current"
        elif active:
            state = "building"
        elif latest and latest["conclusion"] not in ("success", None) and latest["headSha"] == head:
            state = "failed"
        else:
            state = "stale"
        return {"state": state, "published": published, "head": head, "profile": searcher.profile,
                "chunks": searcher.site.manifest["chunks"].get("count"), "latest_run": latest,
                "auto": self._auto(state, head)}

    def _auto(self, state: str, head: str) -> dict:
        """What the watcher will do about a stale index."""
        if state != "stale" and state != "failed":
            return {"kind": "none"}
        if self._dispatched_for == head:
            return {"kind": "done"}
        if state == "failed":
            return {"kind": "none"}
        if self._stale_since is None:
            return {"kind": "waiting", "seconds": STALE_GRACE}
        return {"kind": "waiting", "seconds": max(0, round(STALE_GRACE - (self._clock() - self._stale_since)))}

    async def reindex(self) -> dict:
        """Run the docs CI for the current commit, unless it's already running."""
        status = await self.status()
        if status["state"] == "current":
            return {"started": False, "reason": "the index already matches the docs", **status}
        if status["state"] == "building":
            return {"started": False, "reason": "the docs CI is already running", **status}
        await self.github.dispatch(DOCS_REPO, WORKFLOW, "main")
        self._dispatched_for = status["head"]
        return {"started": True, **status}

    async def tick(self) -> dict | None:
        """One check of the watcher: start the CI once per commit if it stayed stale."""
        status = await self.status()
        if status["state"] != "stale":
            self._stale_since = None
            return None
        now = self._clock()
        if self._stale_since is None:
            self._stale_since = now
        if now - self._stale_since < STALE_GRACE or self._dispatched_for == status["head"]:
            return None
        log.info("docs index stale at %s: starting the docs CI", status["head"][:12])
        await self.github.dispatch(DOCS_REPO, WORKFLOW, "main")
        self._dispatched_for = status["head"]
        return status

    async def watch(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as e:  # a network or gh failure must not end the watcher
                log.warning("docs index check failed: %s", e)
            await asyncio.sleep(CHECK_EVERY)

