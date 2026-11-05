# SPDX-License-Identifier: GPL-2.0-or-later
"""Keeps the work store in step with GitHub, for very little of the rate limit.

Each tick: the organization overview, one search for issues and pull requests updated since
the last one (the event feeds leave things out and lag for hours, this doesn't), and a
conditional request for each repository's runs, which GitHub doesn't count when nothing
changed. A webhook could later call wake(); nothing else would have to change.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import math
import os
import time
from pathlib import Path

from .github import ORG
from .hubd_client import HubdError
from .workstore import WorkStore, run_row

log = logging.getLogger("hub.sync")
DEFAULT_INTERVAL = 60.0
MIN_INTERVAL = 15.0
# Below this much of the hourly budget, ticks come this much further apart.
LOW_RATE = 500
SLOW_FACTOR = 5
# After a failed model load or embedding: words carry on, and the next try waits this long.
RETRY_LOAD = 600
# A complete pass this much smaller than what's here looks like lost access, not deletions.
MOST_GONE = 0.5
# GitHub's search index lags a little, so each tick looks back over this much again.
OVERLAP = 300
# A complete pass now and then is how deleted and transferred issues leave the store.
FULL_EVERY = 6 * 3600
SEARCH_CAP = 1000
RUNS_PER_REPO = 30
EMBED_BATCH = 32


def interval_from(value: str | None) -> float:
    """HUB_SYNC_SECONDS: a bad value mustn't stop the hub, nor a small one spend its rate limit."""
    try:
        seconds = float(value) if value else DEFAULT_INTERVAL
    except ValueError:
        seconds = math.nan
    if not math.isfinite(seconds):
        log.warning("HUB_SYNC_SECONDS isn't a number: %r; using %s", value, DEFAULT_INTERVAL)
        return DEFAULT_INTERVAL
    return max(MIN_INTERVAL, seconds)


INTERVAL = interval_from(os.environ.get("HUB_SYNC_SECONDS"))


def _earlier(stamp: str, seconds: int) -> str:
    moment = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")) - datetime.timedelta(seconds=seconds)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class Embedder:
    """The model the docs are embedded with, fetched from the same pinned lock. Its own instance and vectors."""

    def __init__(self, cache: Path):
        from glassine_docs import models
        from glassine_docs.transformer import TransformerModel
        lock = models.load_lock()
        entry = lock["models"]["transformer"]
        paths = models.fetch_profile(cache / "models", "transformer", only=[entry["onnx"], "tokenizer.json"], lock=lock)
        self.key = f"{entry['id']}@{entry['revision']}/{entry['onnx']}"
        self._model = TransformerModel(paths[entry["onnx"]], paths["tokenizer.json"], query_prefix=entry["query_prefix"],
                                       max_length=entry["max_length"], threads=2)

    def embed_many(self, texts):
        return self._model.embed_many(texts)

    def embed_query(self, text):
        return self._model.embed_query(text)


class WorkSync:
    def __init__(self, hubd, github, store: WorkStore, load_embedder=None, clock=time.time):
        self.hubd = hubd
        self.github = github
        self.store = store
        self._clock = clock
        self._load_embedder = load_embedder
        self._embedder = None
        self.semantic = "off" if load_embedder is None else "not loaded"
        self._lock = asyncio.Lock()
        self._model_lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._embedding = None
        self._retry_load_at = 0.0
        self._ticked_at = None
        self.error = None
        self.warning = None
        self.run_errors = {}
        self.rate_remaining = None
        self.running = False

    # --- status ---------------------------------------------------------------
    def status(self) -> dict:
        synced = self.store.get("synced_at")
        return {"enabled": True, "ready": self.ready(), "running": self.running, "error": self.error,
                "synced_at": float(synced) if synced else None, "semantic": self.semantic, "counts": self.store.counts(),
                "warning": self.warning, "run_errors": self.run_errors, "rate_remaining": self.rate_remaining}

    def ready(self) -> bool:
        return self.store.get("synced_at") is not None

    def wake(self) -> None:
        self._wake.set()

    def next_wait(self) -> float:
        low = self.rate_remaining is not None and self.rate_remaining < LOW_RATE
        return INTERVAL * (SLOW_FACTOR if low else 1)

    async def sync_now(self) -> dict:
        """A request for a tick: joins one under way, and doesn't queue up more."""
        recent = self._ticked_at is not None and self._clock() - self._ticked_at < MIN_INTERVAL
        if not self.running and not recent:
            await self.tick()
        return self.status()

    # --- one tick ---------------------------------------------------------------
    async def tick(self) -> dict:
        async with self._lock:
            self.running = True
            try:
                await self.github.overview(fresh=True)
                changed = await self._pull_changes()
                repos = [r["name"] for g in self.github._overview["groups"] for r in g["repos"]]
                new_runs = await self._pull_runs(repos)
                if self.store.get("open_prs_owed"):
                    # Whether a finished check moves a pull request's updatedAt isn't something to rely on.
                    await self._pull("open-prs")
                    self.store.put("open_prs_owed", "")
                self.store.put("synced_at", str(self._clock()))
                self.error = None
                return {"items": changed, "runs": new_runs}
            except HubdError as e:
                self.error = str(e)
                log.warning("sync failed: %s", e)
                raise
            except Exception as e:  # an answer of an unexpected shape, say: as visible as a refusal
                self.error = f"{type(e).__name__}: {e}"
                log.exception("sync failed")
                raise
            finally:
                self.running = False
                self._ticked_at = self._clock()
                self._embed_soon()

    async def _pull(self, scope: str, since: str | None = None) -> tuple[int, set, str | None, bool]:
        """Stores one search's results: (changed, seen, newest time, whether all of it was seen)."""
        changed, seen, newest, cursor, total = 0, set(), None, None, 0
        while True:
            data = await self.hubd.graphql("org_changes", scope=scope, since=since, cursor=cursor)
            self.store.put("viewer", data["viewer"]["login"])
            self.rate_remaining = (data.get("rateLimit") or {}).get("remaining", self.rate_remaining)
            found = data["search"]
            total = found["issueCount"]
            for node in found["nodes"]:
                if not node:  # a result GitHub won't show this login
                    continue
                changed += self.store.upsert(node)
                seen.add(("pr" if node["__typename"] == "PullRequest" else "issue", node["repository"]["name"], node["number"]))
                newest = max(newest or "", node["updatedAt"])
            if not found["pageInfo"]["hasNextPage"]:
                return changed, seen, newest, total < SEARCH_CAP and len(seen) >= total
            cursor = found["pageInfo"]["endCursor"]

    async def _pull_changes(self) -> int:
        cursor = self.store.get("items_cursor")
        full_at = float(self.store.get("full_at") or 0)
        full = cursor is None or self._clock() - full_at > FULL_EVERY
        changed, seen, newest, complete = await self._pull("changed", None if full else _earlier(cursor, OVERLAP))
        if newest and newest > (cursor or ""):
            self.store.put("items_cursor", newest)
        if full:
            self.warning = self._removal_check(seen, complete)
            if self.warning:
                log.warning("%s", self.warning)
            else:
                self.store.remove_missing(seen)
            self.store.prune(self._clock())
            self.store.put("full_at", str(self._clock()))
        return changed

    def _removal_check(self, seen: set, complete: bool) -> str | None:
        """Why this complete pass can't say what's gone, if it can't."""
        # Results past GitHub's cap are never returned.
        if not complete:
            return f"more than the {SEARCH_CAP} items a search can return: deleted ones stay in the store"
        counts = self.store.counts()
        here = counts.get("issue", 0) + counts.get("pr", 0)
        if here and len(seen) < here * MOST_GONE:
            return f"a complete pass saw {len(seen)} items of {here} here: kept them, in case access was lost"
        return None

    async def _pull_runs(self, repos: list[str]) -> int:
        async def one(repo):
            key = f"etag/{repo}"
            try:
                reply = await self.hubd.gh_conditional(f"repos/{ORG}/{repo}/actions/runs?per_page={RUNS_PER_REPO}", self.store.get(key))
            except HubdError as e:
                log.warning("no runs for %s: %s", repo, e)
                self.run_errors[repo] = str(e)
                return 0
            self.run_errors.pop(repo, None)
            if reply["status"] == 304:
                return 0
            count = sum(self.store.upsert_run(run_row(repo, run)) for run in reply["body"].get("workflow_runs") or [])
            if count:
                self.store.put(f"ci/{repo}", str(self._clock()))  # what a pull request's kept checks depend on
                self.store.put("open_prs_owed", "1")  # stays until that search has worked
            if reply.get("etag"):
                self.store.put(key, reply["etag"])
            return count
        return sum(await asyncio.gather(*(one(r) for r in repos)))

    # --- embeddings ---------------------------------------------------------------
    async def embedder(self):
        if self._load_embedder is None:
            return None
        if self._embedder is None and self._clock() < self._retry_load_at:
            return None
        async with self._model_lock:
            if self._embedder is None:
                self.semantic = "loading"
                try:
                    self._embedder = await asyncio.to_thread(self._load_embedder)
                    self.semantic = "ready"
                # SystemExit: the docs client says so when onnxruntime is missing, which mustn't end the app.
                except (Exception, SystemExit) as e:  # no model, no network: words still work
                    log.warning("no embedding model: %s", e)
                    self.semantic = f"unavailable: {e}"
                    self._retry_load_at = self._clock() + RETRY_LOAD
                    return None
            return self._embedder

    def _embed_soon(self) -> None:
        waiting = self._clock() < self._retry_load_at
        if self._load_embedder is not None and not waiting and (self._embedding is None or self._embedding.done()):
            self._embedding = asyncio.create_task(self.embed_pending())

    async def embed_pending(self) -> int:
        model = await self.embedder()
        if model is None:
            return 0
        done = 0
        try:
            while pending := self.store.unembedded(model.key, EMBED_BATCH):
                self.semantic = "embedding"
                vectors = await asyncio.to_thread(model.embed_many, [text for _, text in pending])
                self.store.add_vectors(model.key, [digest for digest, _ in pending], vectors)
                done += len(pending)
        except Exception as e:  # runs as a task nobody waits for, so it has to say so itself
            log.exception("embedding failed")
            self.semantic = f"failed: {e}"
            self._retry_load_at = self._clock() + RETRY_LOAD
            return done
        self.semantic = "ready"
        return done

    async def search(self, query: str, **filters) -> dict:
        # Only a model that's already here: a download mustn't hold up a search by words.
        self._embed_soon()
        model = self._embedder
        vector = None
        if model:
            try:
                vector = await asyncio.to_thread(model.embed_query, query)
            except Exception as e:
                log.warning("couldn't embed a query: %s", e)
        results = self.store.search(query, vector, model.key if model else None, **filters)
        whole = vector is not None and not self.store.unembedded(model.key, 1)
        return {"query": query, "results": results, "by_meaning": whole, "semantic": self.semantic,
                "synced_at": self.status()["synced_at"]}

    # --- the loop ---------------------------------------------------------------------
    async def watch(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                pass  # kept in self.error; views go on serving what's here
            try:
                await asyncio.wait_for(self._wake.wait(), self.next_wait())
            except TimeoutError:
                pass
            self._wake.clear()
