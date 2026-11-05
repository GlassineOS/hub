# SPDX-License-Identifier: GPL-2.0-or-later
"""What the app was doing when it stopped answering.

All of the app runs on one event loop, so one piece of code that doesn't yield holds up every
page and tool. A thread beside the loop notices, and writes the stacks of all threads and the
requests in progress to the log, while the evidence is still there.

Stacks hold file names, lines and function names, not values. Requests are logged by path,
without the query, so no search text or token reaches the log.
"""
from __future__ import annotations

import asyncio
import faulthandler
import itertools
import logging
import signal
import sys
import threading
import time

log = logging.getLogger("hub.watchdog")
STALL_SECONDS = 20  # longer than anything the loop should ever be held for
REPEAT_SECONDS = 300  # still stuck: stacks again, to show whether it's moving
SLOW_REQUEST_SECONDS = 5


def stack_dump_on_signal(signum: int = signal.SIGUSR1, file=None) -> None:
    """`kill -USR1` writes the stacks, however stuck Python is. A crash in native code writes them too."""
    faulthandler.enable(file=file or sys.stderr, all_threads=True)
    faulthandler.register(signum, file=file or sys.stderr, all_threads=True)


class Requests:
    """ASGI middleware: which requests are in progress, and which ones took long."""

    def __init__(self, app, name: str, clock=time.monotonic, slow: float = SLOW_REQUEST_SECONDS):
        self.app = app
        self.name = name
        self.clock = clock
        self.slow = slow
        self.active: dict[int, tuple[str, str, float]] = {}
        self._ids = itertools.count()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":  # a terminal stays open for as long as it's used
            await self.app(scope, receive, send)
            return
        key = next(self._ids)
        self.active[key] = (scope["method"], scope["path"], self.clock())
        try:
            await self.app(scope, receive, send)
        finally:
            method, path, began = self.active.pop(key)
            took = self.clock() - began
            if took >= self.slow:
                log.warning("%s: %s %s took %.1f s", self.name, method, path, took)

    def in_progress(self) -> list[str]:
        now = self.clock()
        # A copy first: this runs on the watchdog's thread, while the loop may be changing it.
        return [f"{self.name}: {m} {p}, {now - t:.1f} s" for m, p, t in list(self.active.values())]


class Watchdog:
    def __init__(self, requests=(), stall: float = STALL_SECONDS, repeat: float = REPEAT_SECONDS, file=None,
                 clock=time.monotonic):
        self.requests = requests
        self.stall = stall
        self.repeat = repeat
        self.file = file
        self.clock = clock
        self.beat = clock()
        self._reported = None
        self._stuck_since = None
        self._stop = threading.Event()

    async def heartbeat(self) -> None:
        """Runs on the loop. If this stops, so has everything else."""
        while True:
            self.beat = self.clock()
            await asyncio.sleep(min(1.0, self.stall / 4))

    def check(self) -> None:
        now, beat = self.clock(), self.beat
        late = now - beat
        if late < self.stall:
            if self._stuck_since is not None:
                log.warning("the event loop is answering again, after about %.0f s", beat - self._stuck_since)
                self._stuck_since = self._reported = None
            return
        if self._stuck_since is None:
            self._stuck_since = beat
        if self._reported is None or now - self._reported >= self.repeat:
            self._reported = now
            self.report(late)

    def report(self, late: float) -> None:
        log.error("the event loop hasn't run for %.0f s; requests in progress: %s", late,
                  "; ".join(line for r in self.requests for line in r.in_progress()) or "none")
        faulthandler.dump_traceback(file=self.file or sys.stderr, all_threads=True)

    def _watch(self) -> None:
        while not self._stop.wait(min(1.0, self.stall / 4)):
            try:
                self.check()
            except Exception:  # the app goes on without it
                log.exception("watchdog check failed")

    def start(self) -> asyncio.Task:
        """Call on the running loop. The thread is a daemon: it never holds up an exit."""
        self.beat = self.clock()
        threading.Thread(target=self._watch, name="hub-watchdog", daemon=True).start()
        return asyncio.create_task(self.heartbeat())

    def stop(self) -> None:
        self._stop.set()
