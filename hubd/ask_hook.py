#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""A session's hook: tells hubd what Claude Code is asking, and waits for the hub's answer.

Whatever goes wrong, it prints nothing and exits, and the terminal's own prompt carries on. It holds the
connection open until the answer comes, and hubd takes the connection ending to mean the prompt has
gone: Claude Code ends this process when someone says no or presses Esc in the terminal. When someone says
yes there, it doesn't, and the same script reports the PostToolUse or Stop that follows. That just closes the card.
"""
import json
import socket
import sys

MAX_LINE = 90_000  # hubd reads at most 100 KB as a request


def main() -> None:
    path, token_file = sys.argv[1:3]
    event = json.load(sys.stdin)
    with open(token_file) as f:
        token = f.read().strip()
    how = event.get("hook_event_name")
    request = {"op": "ask.moved" if how in ("PostToolUse", "PostToolUseFailure", "Stop") else "ask.wait", "agent_token": token, "how": how, "tool": event.get("tool_name"),
               "input": event.get("tool_input"), "suggestions": event.get("permission_suggestions")}
    line = json.dumps(request).encode()
    if len(line) > MAX_LINE:  # hubd shows that it's too long to show, rather than part of it
        line = json.dumps({**request, "input": None}).encode()
    with socket.socket(socket.AF_UNIX) as s:
        s.connect(path)
        s.sendall(line + b"\n")
        reply = s.makefile("rb").readline()
    output = json.loads(reply).get("output")
    if output:
        print(json.dumps(output))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001: the prompt is still up in the terminal
        pass
