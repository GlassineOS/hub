#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""The second lock on a review session's shell: Claude Code's shell prefix, so every command comes through here.

The hook decides, but a hook that crashes, times out or can't start is no answer, and then Claude Code runs a command
it considers read-only, on the host and with the session's environment. So this refuses anything that isn't the
hook's sandbox command, which carries a secret from the session's folder, or one of the session's own hooks.
If this can't run, nothing does.
"""
import json
import os
import sys
from pathlib import Path

REFUSED = 126


def _commands(value) -> set[str]:
    """Every hook command in the session's settings."""
    if isinstance(value, dict):
        found = {value["command"]} if isinstance(value.get("command"), str) else set()
        return found.union(*map(_commands, value.values()))
    if isinstance(value, list):
        return set().union(*map(_commands, value))
    return set()


def allowed(command: str, session: Path) -> bool:
    marker = (session / "shell" / "marker").read_text().strip()
    if marker and f"GLASSINE_SANDBOX={marker} " in command:
        return True
    return command in _commands(json.loads((session / "settings.json").read_text()))


def main() -> int:
    session, command = Path(sys.argv[1]), sys.argv[2]
    if len(sys.argv) != 3 or not allowed(command, session):
        print("refused: this command didn't come through the sandbox, so it didn't run", file=sys.stderr)
        return REFUSED
    os.execv("/bin/bash", ["bash", "-c", command])
    return REFUSED


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001: unsure means no
        print(f"refused: {e}", file=sys.stderr)
        sys.exit(REFUSED)
