#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""A session's hook: tells hubd that a turn ended, the session ended, a tool ran or a compaction is coming (spec 012,
FR-013). hubd tries the exits of the session's state that name that signal.

It sends one line and goes: it never waits for an answer, so it never holds a turn. Only the event's name goes, never
what the tool was given or said. Whatever goes wrong, it prints nothing and exits 0.
"""
import json
import socket
import sys

WAIT = 2.0  # seconds to reach hubd before giving up; the next signal tries again


def main() -> None:
    path, token_file = sys.argv[1:3]
    event = json.load(sys.stdin)
    with open(token_file) as f:
        token = f.read().strip()
    line = json.dumps({"op": "session.signal", "agent_token": token, "how": event.get("hook_event_name")}).encode()
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(WAIT)
        s.connect(path)
        s.sendall(line + b"\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001: a lost signal costs a move at most, never the turn
        pass
    sys.exit(0)
