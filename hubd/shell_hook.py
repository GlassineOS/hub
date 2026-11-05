#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""A review session's hook on Bash: runs each command inside a sandbox.

Bash isn't on the session's allowed list, and it runs under dontAsk, so only this hook's "allow" lets a command run,
and that comes with the command rewritten. On a failure this says deny. If it can't answer at all, Claude Code would
still run what it thinks is a read-only command, and shell_guard.py is what stops that.

The sandbox sees the system's programs and an overlay of the checkout and its git store. It has its own home and
/tmp, kept for the session, and no environment, tokens or other files of yours. Writes land in the overlay's upper
folder, so nothing outside ever runs on or from them: the hub's own git never sees that tree. It reaches the internet
through pasta, which keeps it away from this host's loopback and abstract sockets. pasta's own sockets are this host's,
so routes in its namespace refuse private ranges and this host's addresses, set before bubblewrap drops the right to
change them.

Commands take turns: overlays can't share their upper and work folders. The git store below an overlay is the clone the
hub fetches into for other sessions, which the kernel leaves undefined. That can give odd git results in here and no
harm outside, for as long as one command runs.
"""
import ipaddress
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

DNS = "169.254.1.1"
GATEWAY = "169.254.1.2"
ADDRESS = "169.254.1.3"
PREFIX = "29"
MARKER = "marker"
TURN_WAIT = 600  # seconds a command waits for the one before it
REFUSED_RANGES = ("0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.168.0.0/16",
                  "198.18.0.0/15", "224.0.0.0/4", "240.0.0.0/4")


def _refused_routes() -> list[str]:
    """The ranges, and this host's own addresses, which can be public. If this can't list them, the hook says deny."""
    listing = subprocess.run(["ip", "-4", "-o", "addr", "show"], check=True, capture_output=True, text=True, timeout=10).stdout
    words = [line.split() for line in listing.splitlines()]
    own = {w[w.index("inet") + 1].split("/")[0] for w in words if "inet" in w}
    return [*REFUSED_RANGES, *sorted(f"{a}/32" for a in own if ipaddress.ip_address(a).is_global)]


def _git_store(checkout: Path) -> Path:
    """A worktree's .git file names its folder in the store: <store>/worktrees/<name>."""
    text = (checkout / ".git").read_text().strip()
    if not text.startswith("gitdir: "):
        raise ValueError("not a worktree")
    return Path(text.removeprefix("gitdir: ")).parents[1]


def _overlay(lower: Path, folder: Path) -> list[str]:
    for part in ("upper", "work"):
        (folder / part).mkdir(parents=True, exist_ok=True)
    return ["--overlay-src", str(lower), "--overlay", str(folder / "upper"), str(folder / "work"), str(lower)]


def sandboxed(command: str, cwd: str, shell: Path, checkouts: list[Path]) -> list[str]:
    home = str(Path.home())
    for part in ("home", "tmp"):
        (shell / part).mkdir(parents=True, exist_ok=True)
    # With no way back to the host's loopback, a resolver there needs pasta to carry the queries.
    (shell / "resolv.conf").write_text(f"nameserver {DNS}\n")
    routes = "".join(f"ip route add blackhole {r} && " for r in _refused_routes())
    # The namespace's address and gateway are ours, or the host's own subnet would be on-link and beat the routes.
    # No IPv6: this host's addresses there would need the same care, and its subnets have no fixed ranges.
    argv = [f"GLASSINE_SANDBOX={(shell / MARKER).read_text().strip()}", "pasta", "--quiet", "--config-net", "-4", "--no-map-gw", "-a", ADDRESS, "-n", PREFIX, "-g", GATEWAY,
            "--dns-forward", DNS, "-t", "none", "-u", "none", "-T", "none", "-U", "none", "--",
            "sh", "-c", f'{routes}exec "$@"', "sh", "flock", "--no-fork", "--wait", str(TURN_WAIT), str(shell / "lock"),
            "bwrap", "--unshare-all", "--unshare-user", "--uid", str(os.getuid()), "--gid", str(os.getgid()), "--share-net", "--new-session", "--die-with-parent", "--clearenv",
            "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin", "--setenv", "HOME", home, "--setenv", "TMPDIR", "/tmp",
            "--setenv", "LANG", "C.UTF-8", "--setenv", "TERM", "dumb", "--setenv", "GIT_TERMINAL_PROMPT", "0",
            "--ro-bind", "/usr", "/usr", "--ro-bind", "/etc", "/etc", "--ro-bind", str(shell / "resolv.conf"), os.path.realpath("/etc/resolv.conf")]
    for link in ("/bin", "/sbin", "/lib", "/lib64"):
        argv += ["--ro-bind-try", link, link]
    argv += ["--proc", "/proc", "--dev", "/dev", "--bind", str(shell / "tmp"), "/tmp", "--bind", str(shell / "home"), home]
    stores: dict[Path, int] = {}
    for i, checkout in enumerate(checkouts):
        store = _git_store(checkout)
        if store not in stores:
            stores[store] = len(stores)
            argv += _overlay(store, shell / f"store{stores[store]}")
        argv += _overlay(checkout, shell / f"checkout{i}")
    here = Path(cwd)
    inside = any(here == c or c in here.parents for c in checkouts)
    argv += ["--chdir", str(here if inside else checkouts[0]), "bash", "-c", command]
    return argv


def main() -> None:
    event = json.load(sys.stdin)
    tool_input = event["tool_input"]
    argv = sandboxed(tool_input["command"], event.get("cwd", ""), Path(sys.argv[1]), [Path(p) for p in sys.argv[2:]])
    # The marker is an assignment, which shlex.join would quote into a command name. Only hex, so it needs no quoting.
    command = f"{argv[0]} {shlex.join(argv[1:])}"
    # Not in the background: it would hold everyone's turn, and the sandbox ends with its command anyway.
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                             "updatedInput": {**tool_input, "command": command, "run_in_background": False}}}))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001: whatever it was, the command doesn't run
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": f"The sandbox couldn't be set up: {e}"}}))
