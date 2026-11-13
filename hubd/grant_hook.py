#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""A session's hook before each tool use, for a session whose workflow can move: refuses a tool its current state doesn't grant.

Its launch named the tools it may use, and a move to a state that grants fewer takes effect at once (spec 012, FR-022):
hubd rewrites grant.json in the session's folder, 0600, and this reads it at every tool use. A Claude Code tool must be on
its `tools` list; one of the hub's tools, named `mcp__<server>__<tool>`, on its `hub_tools` list (the hub's tool server
checks the session's token as well); anything else is refused. A null list is a full session's, which has none: this
stays silent there, as a full session is guarded and not limited.

It only refuses or says nothing, never allows: an allow would let a command past the other hooks, the shell's sandbox among
them. It refuses by exiting 2 with the reason on stderr, which Claude Code takes as a block whatever else the hooks say.
Whatever goes wrong (no file, a file it can't read, input it can't parse) it refuses; the command hubd installs ends in
`|| exit 2`, so an interpreter that can't start refuses too. A hook that runs past its timeout is ended by Claude Code,
which then goes on: that case is a guard, not a limit (SECURITY.md).
"""
import json
import sys


DENY = 2  # Claude Code's exit status for a hook that blocks the tool


def _deny(why: str) -> None:
    print(why, file=sys.stderr)
    sys.exit(DENY)


def decide(grant: dict, tool: str) -> str | None:
    """Why the tool is refused, or None if this has nothing to say."""
    tools, hub_tools, server = grant.get("tools"), grant.get("hub_tools"), grant.get("server")
    prefix = f"mcp__{server}__"
    if tool.startswith(prefix):
        if hub_tools is None or tool[len(prefix):] in hub_tools:
            return None
        return f"{tool[len(prefix):]} isn't granted in this session's current workflow state"
    if tools is None or tool in tools:
        return None
    return f"{tool} isn't granted in this session's current workflow state"


def main() -> None:
    try:
        event = json.load(sys.stdin)
        tool = event["tool_name"]
        with open(sys.argv[1]) as f:
            grant = json.load(f)
        if not isinstance(tool, str) or not isinstance(grant, dict) or not isinstance(grant.get("server"), str):
            raise ValueError("unreadable")
        for key in ("tools", "hub_tools"):
            if grant.get(key) is not None and not (isinstance(grant[key], list) and all(isinstance(t, str) for t in grant[key])):
                raise ValueError("unreadable")
        why = decide(grant, tool)
    except Exception:  # noqa: BLE001: fails closed
        why = "the hub can't say what this session's workflow state grants right now"
    if why:
        _deny(why)


if __name__ == "__main__":
    main()
