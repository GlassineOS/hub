# SPDX-License-Identifier: GPL-2.0-or-later
import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def install(tmp_path, **env):
    done = run_install(tmp_path, **env)
    return done.stdout, (tmp_path / "config" / "glassine-hub" / "hubd.env").read_text().splitlines()


def run_install(tmp_path, **env):
    repo = tmp_path / "workspace" / "hub"
    if not repo.exists():
        (repo / "deploy").mkdir(parents=True)
        for name in ("install.sh", "glassine-hubd.service"):
            shutil.copy(REPO / "deploy" / name, repo / "deploy" / name)
    stubs = tmp_path / "stubs"
    stubs.mkdir(exist_ok=True)
    systemctl = stubs / "systemctl"
    systemctl.write_text("#!/bin/sh\nexit 0\n")
    systemctl.chmod(0o755)
    base = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
    done = subprocess.run(
        ["sh", str(repo / "deploy" / "install.sh")], capture_output=True, text=True, check=True,
        env={**base, "PATH": f"{stubs}:{base['PATH']}", "HOME": str(tmp_path),
             "XDG_CONFIG_HOME": str(tmp_path / "config"), "XDG_CACHE_HOME": str(tmp_path / "cache"),
             "XDG_STATE_HOME": str(tmp_path / "state"), "XDG_RUNTIME_DIR": str(tmp_path / "run"), **env})
    return done


def knob(tmp_path):
    return (tmp_path / "config" / "glassine-hub" / "agents.env").read_text()


def test_a_first_run_starts_the_knob_from_the_environment(tmp_path):
    out, lines = install(tmp_path, CLAUDE_CONFIG_DIR="/some/login")
    assert "CLAUDE_CONFIG_DIR=/some/login" in knob(tmp_path).splitlines()
    assert "Claude login for agents: /some/login" in out
    assert not any(line.startswith("CLAUDE_CONFIG_DIR=") for line in lines)


def test_the_knob_survives_later_runs(tmp_path):
    install(tmp_path)
    path = tmp_path / "config" / "glassine-hub" / "agents.env"
    path.write_text("CLAUDE_CONFIG_DIR=/mine\nOTHER=1\n")
    out, _ = install(tmp_path, CLAUDE_CONFIG_DIR="/another")
    assert knob(tmp_path) == "CLAUDE_CONFIG_DIR=/mine\nOTHER=1\n"
    assert "Claude login for agents: /mine" in out


def test_the_knob_is_private_and_says_how_to_use_it(tmp_path):
    out, _ = install(tmp_path)
    path = tmp_path / "config" / "glassine-hub" / "agents.env"
    assert path.stat().st_mode & 0o777 == 0o600
    assert not any(line.startswith("CLAUDE_CONFIG_DIR=") for line in knob(tmp_path).splitlines())
    assert "the default" in out


def test_a_login_from_an_older_hubd_env_moves_over(tmp_path):
    config = tmp_path / "config" / "glassine-hub"
    config.mkdir(parents=True)
    (config / "hubd.env").write_text("CLAUDE_CONFIG_DIR=/old/login\n")
    out, lines = install(tmp_path)
    assert "CLAUDE_CONFIG_DIR=/old/login" in knob(tmp_path).splitlines()
    assert not any(line.startswith("CLAUDE_CONFIG_DIR=") for line in lines)
    assert "Claude login for agents: /old/login" in out


def test_the_uncommented_template_means_what_it_says(tmp_path):
    install(tmp_path)
    assert "# CLAUDE_CONFIG_DIR=~/.claude-something\n" in knob(tmp_path)


def test_the_workspace_is_named_only_when_it_is_one(tmp_path):
    _, lines = install(tmp_path)
    assert not any(line.startswith("HUBD_WORKSPACE=") for line in lines)
    (tmp_path / "workspace" / "workspace.toml").write_text("")
    _, lines = install(tmp_path)
    assert f"HUBD_WORKSPACE={tmp_path / 'workspace'}" in lines


def test_a_spaced_login_is_still_reported(tmp_path):
    install(tmp_path)
    path = tmp_path / "config" / "glassine-hub" / "agents.env"
    path.write_text("export CLAUDE_CONFIG_DIR = /spaced\n")
    out, _ = install(tmp_path)
    assert "Claude login for agents: /spaced" in out


def fake_venv(tmp_path, pip_exit):
    stubs = tmp_path / "stubs"
    stubs.mkdir(exist_ok=True)
    python = stubs / "python3"
    python.write_text(f"""#!/bin/sh
mkdir -p "$3/bin"
printf '#!/bin/sh\\necho run >> "{tmp_path}/pip-runs"\\nexit {pip_exit}\\n' > "$3/bin/pip"
chmod +x "$3/bin/pip"
printf '#!/bin/sh\\nexit 0\\n' > "$3/bin/python"
chmod +x "$3/bin/python"
""")
    python.chmod(0o755)
    (tmp_path / "workspace" / "hub" / "deploy").mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / "deploy" / "codemap-requirements.txt", tmp_path / "workspace" / "hub" / "deploy" / "codemap-requirements.txt")
    shutil.copy(REPO / "deploy" / "install.sh", tmp_path / "workspace" / "hub" / "deploy" / "install.sh")
    shutil.copy(REPO / "deploy" / "glassine-hubd.service", tmp_path / "workspace" / "hub" / "deploy" / "glassine-hubd.service")


def test_the_parser_gets_its_own_environment_once(tmp_path):
    fake_venv(tmp_path, 0)
    install(tmp_path)
    install(tmp_path)
    venv = tmp_path / "state" / "glassine-hub" / "codemap" / "venv"
    assert (venv / "requirements.txt").read_text() == (REPO / "deploy" / "codemap-requirements.txt").read_text()
    assert (tmp_path / "pip-runs").read_text().count("run") == 1


def test_a_parser_that_wont_install_doesnt_stop_the_hub(tmp_path):
    fake_venv(tmp_path, 1)
    out, _lines = install(tmp_path)
    assert not (tmp_path / "state" / "glassine-hub" / "codemap" / "venv").exists()
    assert "hubd is running" in out


def test_a_parser_that_stopped_working_is_installed_again(tmp_path):
    fake_venv(tmp_path, 0)
    install(tmp_path)
    (tmp_path / "state" / "glassine-hub" / "codemap" / "venv" / "bin" / "python").write_text("#!/bin/sh\nexit 1\n")
    install(tmp_path)
    assert (tmp_path / "pip-runs").read_text().count("run") == 2


def test_the_parser_is_installed_before_hubd_starts():
    script = (REPO / "deploy" / "install.sh").read_text()
    assert script.index("pip\" install") < script.index("systemctl")
    assert script.index("cp \"$wanted\" \"$venv/requirements.txt\"") < script.index("systemctl")


def test_the_parsers_folder_is_private(tmp_path):
    fake_venv(tmp_path, 0)
    install(tmp_path)
    assert (tmp_path / "state" / "glassine-hub" / "codemap").stat().st_mode & 0o777 == 0o700


def only_these_programs(tmp_path, names):
    """A PATH with the stubs and just the programs install.sh needs, so a host that has ripgrep can't hide it being missing."""
    bin = tmp_path / "bin"
    bin.mkdir(exist_ok=True)
    for name in ("sh", "dirname", "id", "mkdir", "sed", "cat", "tail", "cmp", "rm", "chmod", "cp", *names):
        found = shutil.which(name)
        if found and not (bin / name).exists():
            (bin / name).symlink_to(found)
    return f"{tmp_path / 'stubs'}:{bin}"


def test_a_host_without_ripgrep_is_told_so_and_one_with_it_isnt(tmp_path):
    (tmp_path / "stubs").mkdir()
    errors = run_install(tmp_path, PATH=only_these_programs(tmp_path, ())).stderr.splitlines()
    assert "missing on this host: rg" in errors
    assert all(f"missing on this host: {tool}" in errors for tool in ("python3", "gh", "tmux", "docker", "setsid", "openssl", "bwrap", "pasta", "ip", "flock"))  # the list it had
    rg = tmp_path / "stubs" / "rg"
    rg.write_text("#!/bin/sh\nexit 0\n")
    rg.chmod(0o755)
    assert "missing on this host: rg" not in run_install(tmp_path, PATH=only_these_programs(tmp_path, ())).stderr.splitlines()
