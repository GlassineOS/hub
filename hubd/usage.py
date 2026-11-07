# SPDX-License-Identifier: GPL-2.0-or-later
"""How much of the sessions' usage allowance is used, for the header's meter (001 FR-006, 001 R1).

Each session's settings carry a status-line command (agents._hooks) that copies Claude Code's status-line JSON into
that session's own folder as status.json, at most MAX_BYTES. Nothing here asks Claude Code or the network.

The status-line input is Claude Code's, not ours, and not pinned. If the newest file carries rate limits (a used
percentage and a reset time, and the reset is not already past) those are shown; only that newest file is looked at,
so a slightly older session's limits are not used when the newest has none. Otherwise the total cost of the sessions active today is compared with
an allowance you set (HUBD_DAILY_USAGE_USD in agents.env). Claude Code's cost is a running total for a session (it
resets on /clear), so a session that began on an earlier day counts whole: this is not the day's own spend, and the
words say so. With neither, the meter says it doesn't know.
UNTESTED against a real claude: which rate-limit fields the installed version sends. The reader takes only numbers
it can check, so a field it doesn't know changes nothing but the words "not known".
"""
from __future__ import annotations

import json
import time
from pathlib import Path

STATUS_FILE = "status.json"
MAX_BYTES = 16 * 1024
LOW = 0.8  # the meter says "low" from here
NOT_KNOWN = "usage not known"


def _read(path: Path) -> dict | None:
    try:
        if path.is_symlink() or path.stat().st_size > MAX_BYTES:
            return None
        data = json.loads(path.read_text())
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _number(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


def _rate_limit(status: dict, now: float | None = None) -> dict | None:
    """The fullest window among the rate limits, if the file has any we can read: {used (0..1), resets}.
    A window whose numeric reset time is already past is skipped: its percentage is from before the reset."""
    limits = status.get("rate_limits")
    windows = limits.values() if isinstance(limits, dict) else limits if isinstance(limits, list) else ()
    best = None
    for window in windows:
        if not isinstance(window, dict):
            continue
        used = _number(window.get("used_percentage"))
        resets = window.get("resets_at")
        if used is None or not isinstance(resets, (int, float, str)) or isinstance(resets, bool):
            continue
        if now is not None and isinstance(resets, (int, float)) and resets <= now:
            continue
        used = min(used, 100.0) / 100  # the file says 0..100: compare on one scale
        if best is None or used > best["used"]:
            best = {"used": used, "resets": resets}
    return best


def _cost(status: dict) -> float | None:
    cost = status.get("cost")
    return _number(cost.get("total_cost_usd")) if isinstance(cost, dict) else None


def status(sessions: Path | None, allowance: float | None = None, now: float | None = None) -> dict:
    """{known, used (0..1), low, says, resets, source}. Reads only status.json in each session's own folder."""
    now = time.time() if now is None else now
    day = time.localtime(now)[:3]
    files = []
    for path in sessions.glob(f"*/{STATUS_FILE}") if sessions and sessions.is_dir() else ():
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        files.append((mtime, path))
    files.sort(reverse=True)
    if files:
        newest = _read(files[0][1])
        limit = _rate_limit(newest, now) if newest else None
        if limit:
            return _words(limit["used"], "rate limit", resets=limit["resets"])
    if allowance:
        today = [_cost(s) for mtime, path in files if time.localtime(mtime)[:3] == day for s in [_read(path)] if s]
        spent = sum(c for c in today if c is not None)
        return _words(spent / allowance, "cost of today's sessions", spent=round(spent, 2), allowance=allowance)
    return {"known": False, "used": None, "low": False, "says": NOT_KNOWN, "resets": None, "source": None}


def _words(used: float, source: str, resets=None, spent=None, allowance=None) -> dict:
    low = used >= LOW
    pct = round(used * 100)
    if source == "rate limit":
        says = f"{pct}% of the rate limit used"
    else:
        says = f"${spent:.2f} of ${allowance:.2f} spent by sessions active today ({pct}%)"
    return {"known": True, "used": round(min(used, 1.0), 3), "low": low, "says": f"{says}{', low' if low else ''}",
            "resets": resets, "source": source}


def allowance_of(setting) -> float | None:
    """HUBD_DAILY_USAGE_USD: a positive number of dollars, or nothing."""
    try:
        value = float(setting)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None
