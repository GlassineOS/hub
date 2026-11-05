# SPDX-License-Identifier: GPL-2.0-or-later
import asyncio
import faulthandler
import logging
import os
import signal
import time

import pytest

from hub.watchdog import Requests, Watchdog, stack_dump_on_signal


def spin(seconds):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        pass


def test_a_really_stuck_loop_leaves_its_stack_and_requests_in_the_log(tmp_path, caplog):
    out = open(tmp_path / "stacks", "w+")
    requests = Requests(None, "web")

    async def handler(_scope, _receive, _send):
        spin(0.6)
    requests.app = handler

    async def go():
        watchdog = Watchdog([requests], stall=0.2, file=out)
        beating = watchdog.start()
        await asyncio.sleep(0.05)
        await requests({"type": "http", "method": "GET", "path": "/api/stuck?secret=1"}, None, None)
        await asyncio.sleep(0.4)  # it answers again, and the thread sees that
        watchdog.stop()
        beating.cancel()
    with caplog.at_level(logging.WARNING, "hub.watchdog"):
        asyncio.run(go())
    out.seek(0)
    assert "spin" in out.read()
    words = caplog.text
    assert "the event loop hasn't run" in words and "web: GET /api/stuck" in words
    assert "answering again" in words


def fake_clock():
    now = [100.0]
    return now, lambda: now[0]


def test_a_stall_is_reported_once_then_at_the_repeat_interval(monkeypatch):
    now, clock = fake_clock()
    watchdog = Watchdog(stall=20, repeat=300, clock=clock)
    reports = []
    monkeypatch.setattr(watchdog, "report", reports.append)
    watchdog.check()
    assert reports == []
    now[0] += 25
    watchdog.check()
    now[0] += 100
    watchdog.check()
    assert len(reports) == 1
    now[0] += 200
    watchdog.check()
    assert len(reports) == 2


def test_after_recovering_a_new_stall_reports_again(monkeypatch):
    now, clock = fake_clock()
    watchdog = Watchdog(stall=20, clock=clock)
    reports = []
    monkeypatch.setattr(watchdog, "report", reports.append)
    now[0] += 25
    watchdog.check()
    watchdog.beat = now[0]
    watchdog.check()
    now[0] += 25
    watchdog.check()
    assert len(reports) == 2


def test_a_failed_request_still_leaves_the_list(caplog):
    now, clock = fake_clock()

    async def boom(_scope, _receive, _send):
        assert requests.in_progress() == ["web: POST /x, 0.0 s"]
        now[0] += 9
        raise ValueError

    requests = Requests(boom, "web", clock=clock)
    with caplog.at_level(logging.WARNING, "hub.watchdog"), pytest.raises(ValueError):
        asyncio.run(requests({"type": "http", "method": "POST", "path": "/x"}, None, None))
    assert requests.in_progress() == [] and "web: POST /x took 9.0 s" in caplog.text


def test_only_http_is_timed(caplog):
    async def app(_scope, _receive, _send):
        pass
    requests = Requests(app, "web", slow=0)
    with caplog.at_level(logging.WARNING, "hub.watchdog"):
        asyncio.run(requests({"type": "websocket", "path": "/api/shells/a/attach"}, None, None))
    assert caplog.text == ""


def test_the_signal_writes_the_stacks(tmp_path):
    out = open(tmp_path / "stacks", "w+")
    stack_dump_on_signal(signal.SIGUSR2, file=out)
    try:
        os.kill(os.getpid(), signal.SIGUSR2)
        time.sleep(0.1)
    finally:
        faulthandler.unregister(signal.SIGUSR2)
        faulthandler.disable()
    out.seek(0)
    assert "test_the_signal_writes_the_stacks" in out.read()
