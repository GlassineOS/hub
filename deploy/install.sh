#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
# Sets the hub up for the current user. Run again after moving the repository.
set -eu
repo=$(cd "$(dirname "$0")/.." && pwd)
units=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
sockets=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/glassine-hub

for tool in python3 gh tmux docker setsid openssl bwrap pasta ip flock; do
    command -v "$tool" >/dev/null || echo "missing on this host: $tool" >&2
done

cache=${XDG_CACHE_HOME:-$HOME/.cache}/glassine-hub
mkdir -p "$units" "$cache"

# The code map's parser. It's the one part of the host's side with dependencies, so it has its own environment, and hubd
# runs it in a sandbox. Before hubd starts, as hubd takes the copied list of pins as the sign that it's ready. Without it
# the hub works, and the map tools say why there's no map. The import is for a system Python that has moved on since.
wanted="$repo/deploy/codemap-requirements.txt"
codemap=${XDG_STATE_HOME:-$HOME/.local/state}/glassine-hub/codemap
venv="$codemap/venv"
if [ -f "$wanted" ] && { ! cmp -s "$wanted" "$venv/requirements.txt" || ! "$venv/bin/python" -c 'import tree_sitter, tree_sitter_c, tree_sitter_bash' 2>/dev/null; }; then
    mkdir -p "$codemap"
    chmod 700 "$codemap"
    rm -rf "$venv"
    if python3 -m venv "$venv" && "$venv/bin/pip" install -q -r "$wanted"; then
        cp "$wanted" "$venv/requirements.txt"
    else
        rm -rf "$venv"
        echo "no code map on this host: its parser wouldn't install. Run this again to retry." >&2
    fi
fi

sed "s|@REPO@|$repo|" "$repo/deploy/glassine-hubd.service" > "$units/glassine-hubd.service"
systemctl --user daemon-reload
systemctl --user enable --now glassine-hubd.service
systemctl --user restart glassine-hubd.service
state=${XDG_STATE_HOME:-$HOME/.local/state}/glassine-hub
mkdir -p "$state"

# What the hub found on this host; rewritten by every run.
config=${XDG_CONFIG_HOME:-$HOME/.config}/glassine-hub
mkdir -p "$config"
# From a hubd.env of before agents.env, if it's the only place the login was named.
: "${CLAUDE_CONFIG_DIR:=$(sed -n 's/^CLAUDE_CONFIG_DIR=//p' "$config/hubd.env" 2>/dev/null | tail -n 1)}"
{
    if command -v claude >/dev/null; then echo "HUBD_CLAUDE=$(command -v claude)"; fi
    # Sessions work in the workspace this checkout sits in, or else the default one.
    if [ -f "$repo/../workspace.toml" ]; then echo "HUBD_WORKSPACE=$(cd "$repo/.." && pwd)"; fi
} > "$config/hubd.env"

# The agents' environment is yours to edit, and never rewritten: a service doesn't get your
# shell's setup, so an alias that picks a Claude login has to be repeated here.
if [ ! -f "$config/agents.env" ]; then
    (
        umask 077
        cat > "$config/agents.env" <<EOF
# The environment of the hub's agents and shells. KEY=value, one per line; ~ and \$HOME expand.
# After a change: systemctl --user restart glassine-hubd
# Which Claude login:
# CLAUDE_CONFIG_DIR=~/.claude-something
# Which Claude Code, if not the one on PATH:
# HUBD_CLAUDE=/path/to/claude
EOF
        if [ -n "${CLAUDE_CONFIG_DIR:-}" ]; then echo "CLAUDE_CONFIG_DIR=$CLAUDE_CONFIG_DIR" >> "$config/agents.env"; fi
    )
fi
login=$(sed -n 's/^[[:space:]]*\(export[[:space:]]*\)\{0,1\}CLAUDE_CONFIG_DIR[[:space:]]*=[[:space:]]*//p' "$config/agents.env" | tail -n 1)
echo "Claude login for agents: ${login:-the default; set CLAUDE_CONFIG_DIR in $config/agents.env to change it}"
systemctl --user restart glassine-hubd.service
state=${XDG_STATE_HOME:-$HOME/.local/state}/glassine-hub
mkdir -p "$state"

if [ ! -f "$repo/.env" ]; then
    cat > "$repo/.env" <<EOF
HUB_UID=$(id -u)
HUB_GID=$(id -g)
HUB_SOCKET_DIR=$sockets
HUB_CACHE_DIR=$cache
EOF
fi

cat <<EOF
hubd is running. Now, once:
  sudo install -m 644 $repo/deploy/glassine-hubd.pam /etc/pam.d/glassine-hubd
  docker compose up -d --build     # in $repo
  loginctl enable-linger $(id -un)      # shells keep running when you log out
Then open http://127.0.0.1:9094 and sign in with your account on this computer.
EOF
