# SPDX-License-Identifier: GPL-2.0-or-later
"""The sandbox for a review session's shell, run for real where the host has what it needs."""
import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from hubd import shell_guard, shell_hook

HOOK = Path(shell_hook.__file__)


@pytest.fixture
def setup(tmp_path):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    git = lambda *a, cwd: subprocess.run(["git", *a], cwd=cwd, env=env, check=True, capture_output=True)
    origin = tmp_path / "origin"
    origin.mkdir()
    git("init", "-q", "-b", "main", cwd=origin)
    (origin / "file").write_text("from the tree\n")
    git("add", "file", cwd=origin)
    git("commit", "-qm", "one", cwd=origin)
    store = tmp_path / "store.git"
    git("clone", "-q", "--bare", str(origin), str(store), cwd=tmp_path)
    checkout = tmp_path / "s" / "checkout" / "repo"
    checkout.parent.mkdir(parents=True)
    git("worktree", "add", "-q", "--detach", str(checkout), "main", cwd=store)
    shell = tmp_path / "s" / "shell"
    shell.mkdir(parents=True)
    (shell / "marker").write_text("abc123")
    return tmp_path, checkout, store


def hook(tmp_path, checkout, command, extra=None, cwd=None, github=None):
    event = {"tool_name": "Bash", "cwd": cwd or str(tmp_path), "tool_input": {"command": command, **(extra or {})}}
    flag = ["--github", str(github)] if github else []
    return subprocess.run([sys.executable, "-I", str(HOOK), *flag, str(tmp_path / "s" / "shell"), str(checkout)], input=json.dumps(event), text=True, capture_output=True)


def test_the_hook_allows_only_with_the_command_in_the_sandbox(setup):
    tmp_path, checkout, _ = setup
    done = hook(tmp_path, checkout, "echo hi; rm -rf /", {"timeout": 5, "dangerouslyDisableSandbox": True})
    out = json.loads(done.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "allow" and out["updatedInput"]["timeout"] == 5
    argv = shlex.split(out["updatedInput"]["command"])
    assert argv[:2] == ["GLASSINE_SANDBOX=abc123", "pasta"] and "bwrap" in argv and argv[-3:] == ["bash", "-c", "echo hi; rm -rf /"]
    assert out["updatedInput"]["command"].startswith("GLASSINE_SANDBOX=abc123 pasta ")
    assert out["updatedInput"]["run_in_background"] is False
    assert "--clearenv" in argv and argv[argv.index("--chdir") + 1] == str(checkout)
    assert "Bash" not in out["updatedInput"]


def test_a_failure_says_deny(tmp_path):
    (tmp_path / "s" / "shell").mkdir(parents=True)
    done = hook(tmp_path, tmp_path / "not-a-checkout", "true")
    out = json.loads(done.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny" and "updatedInput" not in out and done.returncode == 0
    done = subprocess.run([sys.executable, "-I", str(HOOK), str(tmp_path)], input="not json", text=True, capture_output=True)
    assert json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_routes_refuse_private_ranges_and_this_hosts_public_addresses(setup, monkeypatch):
    tmp_path, checkout, _ = setup
    listing = "1: lo inet 127.0.0.1/8 x\n2: eth0 inet 192.168.1.5/24 x\n3: wan inet 203.0.113.9/24 x\n4: pub inet 8.8.4.4/24 x\n"
    monkeypatch.setattr(shell_hook.subprocess, "run", lambda *_a, **_k: subprocess.CompletedProcess([], 0, listing, ""))
    routes = shell_hook._refused_routes()
    assert {"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16"} <= set(routes)
    assert "8.8.4.4/32" in routes
    argv = shell_hook.sandboxed("x", str(checkout), tmp_path / "s" / "shell", [checkout])
    script = argv[argv.index("-c") + 1]
    assert "ip route add blackhole 10.0.0.0/8 && " in script and script.endswith('exec "$@"')
    assert "-4" in argv and argv[argv.index("-a") + 1] == shell_hook.ADDRESS


def test_a_resolver_symlink_is_bound_where_it_points(setup, monkeypatch):
    tmp_path, checkout, _ = setup
    monkeypatch.setattr(shell_hook.os.path, "realpath", lambda _p: "/run/systemd/resolve/stub-resolv.conf")
    argv = shell_hook.sandboxed("x", str(checkout), tmp_path / "s" / "shell", [checkout])
    assert argv[argv.index(str(tmp_path / "s" / "shell" / "resolv.conf")) + 1] == "/run/systemd/resolve/stub-resolv.conf"


def test_it_starts_inside_the_checkout_only(setup):
    tmp_path, checkout, _ = setup
    (checkout / "sub").mkdir()
    argv = shell_hook.sandboxed("x", str(checkout / "sub"), tmp_path / "s" / "shell", [checkout])
    assert argv[argv.index("--chdir") + 1] == str(checkout / "sub")
    argv = shell_hook.sandboxed("x", "/etc", tmp_path / "s" / "shell", [checkout])
    assert argv[argv.index("--chdir") + 1] == str(checkout)


def run_in(tmp_path, checkout, command, github=None):
    out = json.loads(hook(tmp_path, checkout, command, github=github).stdout)["hookSpecificOutput"]
    return subprocess.run(out["updatedInput"]["command"], shell=True, text=True, capture_output=True, timeout=60)


has_tools = all(shutil.which(t) for t in ("bwrap", "pasta", "ip", "flock"))
if os.environ.get("HUB_REQUIRE_SANDBOX") and not has_tools:
    raise RuntimeError("HUB_REQUIRE_SANDBOX is set and the sandbox tools are missing")
real = pytest.mark.skipif(not has_tools, reason="skipped: no sandbox tools on this host")


def tree(path):
    return {str(p.relative_to(path)): (p.read_bytes() if p.is_file() else None) for p in path.rglob("*") if not p.is_symlink()}


@real
def test_the_real_store_and_checkout_dont_change(setup):
    tmp_path, checkout, store = setup
    before = tree(store), tree(checkout)
    done = run_in(tmp_path, checkout, "echo x > new; git add new; git -c user.name=t -c user.email=t@t commit -qm planted; git config core.fsmonitor /tmp/evil; git config core.hooksPath /tmp/evil; git log --oneline | wc -l")
    assert done.stdout.strip().endswith("2"), done
    assert before == (tree(store), tree(checkout))
    assert "fsmonitor" not in (store / "config").read_text()


@real
def test_it_cant_reach_this_host_or_private_addresses_or_change_the_routes(setup):
    tmp_path, checkout, _ = setup
    addresses = [a.split()[3].split("/")[0] for a in subprocess.run(["ip", "-4", "-o", "addr", "show"], capture_output=True, text=True).stdout.splitlines()]
    servers = []
    for address in addresses:
        server = socket.socket()
        server.bind((address, 0))
        server.listen()
        servers.append(server)
    abstract = socket.socket(socket.AF_UNIX)
    abstract.bind(b"\0hub-sandbox-test")
    abstract.listen()
    try:
        tries = "".join(f"timeout 3 bash -c '</dev/tcp/{s.getsockname()[0]}/{s.getsockname()[1]}' 2>/dev/null && echo reached {s.getsockname()[0]};\n" for s in servers)
        tries += "timeout 3 python3 -c \"import socket; s = socket.socket(socket.AF_UNIX); s.connect(b'\\0hub-sandbox-test')\" 2>/dev/null && echo reached abstract;\n"
        done = run_in(tmp_path, checkout, tries + "ip route del blackhole 192.168.0.0/16 2>/dev/null && echo changed; ip route add default via 169.254.1.2 metric 1 2>/dev/null && echo changed; echo finished")
    finally:
        for server in [*servers, abstract]:
            server.close()
    assert "finished" in done.stdout and "reached" not in done.stdout and "changed" not in done.stdout, done


@real
def test_host_processes_are_invisible(setup):
    tmp_path, checkout, _ = setup
    keeper = subprocess.Popen(["sleep", "30"])
    try:
        done = run_in(tmp_path, checkout, f"test -e /proc/{keeper.pid} && test {keeper.pid} -gt 100 && echo visible; ls /proc | grep -c '^[0-9]'")
    finally:
        keeper.kill()
    assert "visible" not in done.stdout and int(done.stdout.strip()) < 10, done


@real
def test_commands_take_turns(setup):
    tmp_path, checkout, _ = setup
    first = hook(tmp_path, checkout, "sleep 2; echo first > ~/order")
    second = hook(tmp_path, checkout, "cat ~/order")
    command = lambda done: json.loads(done.stdout)["hookSpecificOutput"]["updatedInput"]["command"]
    running = subprocess.Popen(command(first), shell=True)
    time.sleep(0.5)
    done = subprocess.run(command(second), shell=True, text=True, capture_output=True, timeout=60)
    running.wait(timeout=30)
    assert "first" in done.stdout, done


def sandbox_processes(shell):
    found = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                if str(shell).encode() in (entry / "cmdline").read_bytes():
                    found.append(entry.name)
            except OSError:
                pass
    return found


@real
def test_killing_a_session_mid_command_ends_the_sandbox_and_frees_the_turn(setup):
    tmp_path, checkout, _ = setup
    shell = tmp_path / "s" / "shell"
    out = json.loads(hook(tmp_path, checkout, "sleep 300").stdout)["hookSpecificOutput"]
    running = subprocess.Popen(out["updatedInput"]["command"], shell=True, start_new_session=True)
    time.sleep(1.5)
    assert sandbox_processes(shell)
    os.killpg(running.pid, signal.SIGHUP)
    running.wait(timeout=10)
    for _ in range(50):
        if not sandbox_processes(shell):
            break
        time.sleep(0.1)
    assert not sandbox_processes(shell)
    assert run_in(tmp_path, checkout, "echo free").stdout.strip() == "free"


@real
def test_what_the_sandbox_sees_for_real(setup, monkeypatch):
    tmp_path, checkout, store = setup
    secret = tmp_path / "secret"
    secret.write_text("private")
    monkeypatch.setenv("GLASSINE_HUB_MCP_TOKEN", "token-value")
    done = run_in(tmp_path, checkout, f"cat file; git log --oneline | wc -l; env | grep -c TOKEN; cat {shlex.quote(str(secret))} || echo gone; echo changed >> file; touch made; git status --short; ln -s /etc/passwd link")
    assert "from the tree" in done.stdout and "gone" in done.stdout and "private" not in done.stdout and "token-value" not in done.stdout, done
    assert (checkout / "file").read_text() == "from the tree\n" and not (checkout / "made").exists() and not (checkout / "link").exists()
    again = run_in(tmp_path, checkout, "cat file; ls made; echo x > ~/kept")
    assert "changed" in again.stdout and "made" in again.stdout, again
    assert "kept" in run_in(tmp_path, checkout, "ls ~").stdout
    assert not (Path.home() / "kept").exists() or (Path.home() / "kept").read_text() != "x\n"


# --- a GitHub token, for a session whose launch carries GitHub capabilities -------------------------
def github_folder(tmp_path, token="ghs_scoped"):
    folder = tmp_path / "s" / "github"
    folder.mkdir(exist_ok=True)
    (folder / shell_hook.GITHUB_TOKEN).write_text(token)
    return folder


def test_without_the_switch_the_command_is_as_before(setup, monkeypatch):
    tmp_path, checkout, _ = setup
    monkeypatch.setattr(shell_hook, "_refused_routes", lambda: ["10.0.0.0/8"])
    plain = shell_hook.sandboxed("echo hi", str(checkout), tmp_path / "s" / "shell", [checkout])
    assert plain[-3:] == ["bash", "-c", "echo hi"] and not any("GH_TOKEN" in a or "GIT_CONFIG" in a or "github" in a for a in plain)
    with_token = shell_hook.sandboxed("echo hi", str(checkout), tmp_path / "s" / "shell", [checkout], github_folder(tmp_path))
    assert with_token[:len(plain) - 3] == plain[:-3]  # the same sandbox, with the token's lines after it


def test_the_token_stays_off_the_command_line(setup):
    tmp_path, checkout, _ = setup
    folder = github_folder(tmp_path)
    out = json.loads(hook(tmp_path, checkout, "gh pr list", github=folder).stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "allow"
    command = out["updatedInput"]["command"]
    assert "ghs_scoped" not in command and command.startswith("GLASSINE_SANDBOX=abc123 pasta ")
    argv = shlex.split(command)
    at = argv.index(shell_hook.GITHUB_MOUNT)
    assert argv[at - 2:at] == ["--ro-bind", str(folder)]
    assert argv[-2:] == ["sh", "gh pr list"]


def test_no_token_file_says_deny(setup):
    tmp_path, checkout, _ = setup
    out = json.loads(hook(tmp_path, checkout, "true", github=tmp_path / "s" / "missing").stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny" and "GitHub token" in out["permissionDecisionReason"]


@real
def test_the_token_reaches_gh_and_git_for_github_only_and_is_read_anew(setup):
    tmp_path, checkout, _ = setup
    folder = github_folder(tmp_path)
    fill = "printf 'protocol=https\nhost={}\n\n' | git credential fill 2>/dev/null"
    done = run_in(tmp_path, checkout, f'echo "env=$GH_TOKEN"; {fill.format("github.com")}; echo ---; {fill.format("example.com")}; true', folder)
    head, tail = done.stdout.split("---")
    assert "env=ghs_scoped" in head and "username=x-access-token" in head and "password=ghs_scoped" in head, done
    assert "ghs_scoped" not in tail, done
    (folder / "next").write_text("ghs_renewed")
    os.replace(folder / "next", folder / shell_hook.GITHUB_TOKEN)
    assert "env=ghs_renewed" in run_in(tmp_path, checkout, 'echo "env=$GH_TOKEN"', folder).stdout
    assert "GH_TOKEN" not in run_in(tmp_path, checkout, "env").stdout


# --- the guard: the lock that doesn't depend on the hook ----------------------------------------
def guarded(tmp_path, command, marker="s3cret", hooks=("touch done",)):
    (tmp_path / "shell").mkdir(exist_ok=True)
    (tmp_path / "shell" / "marker").write_text(marker)
    (tmp_path / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": h} for h in hooks]}]}}))
    return subprocess.run([sys.executable, "-I", str(Path(shell_guard.__file__)), str(tmp_path), command], text=True, capture_output=True, cwd=tmp_path)


def test_the_guard_runs_the_sandbox_command_and_the_sessions_hooks(tmp_path):
    assert guarded(tmp_path, "source x || true && eval 'GLASSINE_SANDBOX=s3cret echo ran' && pwd -P").stdout.startswith("ran")
    assert guarded(tmp_path, "touch done").returncode == 0 and (tmp_path / "done").exists()


@pytest.mark.parametrize("command", ["cat /etc/hostname", "env", "eval 'GLASSINE_SANDBOX=wrong echo ran'", "touch done; echo more", "GLASSINE_SANDBOX= echo ran"])
def test_the_guard_refuses_anything_else(tmp_path, command):
    done = guarded(tmp_path, command)
    assert done.returncode == shell_guard.REFUSED and "refused" in done.stderr and "ran" not in done.stdout


def test_an_empty_marker_opens_nothing(tmp_path):
    assert guarded(tmp_path, "GLASSINE_SANDBOX= echo ran", marker="").returncode == shell_guard.REFUSED


def test_the_guard_refuses_if_it_cant_read_its_files(tmp_path):
    done = subprocess.run([sys.executable, "-I", str(Path(shell_guard.__file__)), str(tmp_path), "echo ran"], text=True, capture_output=True)
    assert done.returncode == shell_guard.REFUSED and "ran" not in done.stdout
