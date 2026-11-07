# GlassineOS/hub

The project's control room: a dashboard over the whole GlassineOS organization, the
tracker for strategic work, a terminal into the host where the agent sessions run, and a
tool server that gives those agents the same project management and the doc search.

| Part | What it does |
|---|---|
| **Overview** | Every repository, grouped by its place in the project (`config/repos.toml`), with open issues, PRs, CI state, last commit, release |
| **Roadmap** | The organization project that tracks strategy; its issues live in this repository |
| **Issues, Pull requests, Actions** | Read and manage them across all repositories: comment, close, merge, rerun, cancel, start workflows, read logs |
| **Docs search** | Semantic search over the docs, and the state of its index against the docs repository's CI |
| **Shells** | Interactive host shells in the browser, in tmux, so they outlive the page and the app |
| **Tool server** | All of the above but the shells, over MCP, for agents |

## How it fits together

```
browser ──TLS or loopback──▶ app (docker compose) ──Unix socket──▶ hubd (host, your user)
agent in a shell ──loopback, bearer token──▶ app                     ├─ PAM: the login
                                                                     ├─ gh: GlassineOS only
                                                                     └─ tmux: the shells
```

The app holds no credentials and no host rights. Everything of that kind is a request to
`hubd`, a small standard-library daemon on the host that decides what's allowed. Read
[SECURITY.md](SECURITY.md) before putting this on a network.

## Setting it up

You need `python3`, `gh` (logged in), `tmux`, `docker` with compose, `bwrap` 0.11 or later and `pasta` (for the review shell: packages `bubblewrap` and `passt`, and `ip` and `flock`, which most systems have), and systemd for the user.

```sh
gh auth refresh -h github.com -s project        # the Roadmap needs this scope
deploy/install.sh                               # starts hubd, writes .env
sudo install -m 644 deploy/glassine-hubd.pam /etc/pam.d/glassine-hubd
docker compose up -d --build
loginctl enable-linger "$USER"                  # shells keep running when you log out
```

Open <http://127.0.0.1:9094> and sign in with your account on this computer: the same
user and password as your desktop login. Only the user `hubd` runs as can sign in.

Create the roadmap once. The title has to match `project` in `config/repos.toml`:

```sh
gh project create --owner GlassineOS --title "GlassineOS roadmap"
```

## Agents

Each shell the hub starts has `GLASSINE_HUB_MCP_URL` and `GLASSINE_HUB_MCP_TOKEN` set. (Managed
sessions get a token of their own instead, good only for the tools their action lists, and only
until the session ends.) The
`.mcp.json` here picks them up for work in this repository; for other directories:

```sh
claude mcp add --scope user --transport http glassine-hub http://127.0.0.1:9095/mcp \
    --header 'Authorization: Bearer ${GLASSINE_HUB_MCP_TOKEN}'
```

## The work store

Views and agent tools read issues, pull requests, comments and runs from one SQLite file,
`work/work.sqlite` in the app's cache, so opening a page doesn't call GitHub. Each thing is
one row however often it's seen. Every 60 s (`HUB_SYNC_SECONDS`) a sync asks for what changed:
the overview, a search for issues and pull requests updated since the last tick, and a
conditional request per repository for its runs, free when nothing changed. GitHub's event
feeds aren't used: they lag by many hours and leave repositories out. Anything written through
the hub shows at once. Every 6 hours a complete pass drops what was deleted. The Refresh link
on Work syncs right away. Delete the file to rebuild it; nothing else depends on it.

Passages of issues, pull requests and comments are embedded, so `work_search` and the By
meaning switch on Work find them by meaning as well as by words. It uses the docs search's
model and nothing else of it: the index, files and tool are separate. It costs about 800 MB of
memory; `HUB_WORK_EMBED=off` in `.env` leaves search by words only. `HUB_SYNC_SECONDS` goes in
`.env` too, and is at least 15. Until the model is loaded and everything is embedded, search works
by words and says so. Agents searching without naming a repository see public repositories only, except the Steward.

Every issue, pull request and run under Work has buttons that open Launch on it, as does "＋ New work"
in the header. Launch goes through five stages: the brief (action, items, model, notes), a short planner
(`claude -p`, read-only tools, up to $1) that reads the items and the docs, the plan (its steps and what
each touches, and the briefing, which you can edit), the run (the session, its asks inline) and the
result. Every Launch is a record in hubd, and the session shows it as its origin. The session runs in
tmux and opens below the item, or in Sessions; "Send to background" lets it go on without you, and its
asks and result come to Needs you. Actions with `plan = false` skip the planner: their plan is the action's
own. The library is in `agents/`: actions, personas, prompts and a plugin with skills. Each
action names its short `verb` and its `result` type; each persona has a display name, initials and
one of five families in `agents/personas/families.toml`, and hubd won't start if one is missing.

- **Review, Security audit, Triage, Diagnose and the other read-and-report actions** are locked: only the tools the action lists.
  Review, Triage and Diagnose hand in a result (a review, labels, findings) that you post or apply from its card.
- **Implement, Fix checks, Open a session** are full Claude Code, with your rights. They start
  in the workspace with a worktree in `work/<session>/<repo>`, on its own `agent/<session>` branch. They don't run on a fork's pull request. Ending one with work
  that isn't on GitHub keeps its worktrees.

**Repository copies.** hubd keeps its own clone of each repository in the organization under its state folder,
refreshed every 30 minutes and before a session starts, and Overview says if a refresh failed. A session with file
tools gets a whole tree in its own folder with `request_repository`: read-only, or for a full session a worktree on
its own branch. The Steward and planners read through `list_repo_files` and `read_repo_file`. On Btrfs a tree is a
snapshot, at no real cost even for `linux`; elsewhere it's `cp --reflink=auto`, so a plain copy where sharing isn't
available. `SECURITY.md` says what this means for private repositories.

**Code map.** After a copy moves, hubd has tree-sitter read what changed and writes a map of that commit under its state
folder. `map_overview`, `map_definition`, `map_usages` and `map_string` answer from it, with the same access as
`read_repo_file`: for each repository its main files and what's most used, where a name is defined, what uses it, and who
defines and uses a shared string (a path, device node, config key or package name), including through the constant that
holds it, with a guess at whether each use reads or writes. With no repository named they search public repositories only,
as `work_search` does, and list what they skipped. It's by name, so approximate, and the replies say so. It reads
C, Python, JavaScript, Shell and Rust. Forks stay out (GitHub's own flag: `linux` and TWRP today), as mostly someone else's
code, and `request_repository` still reaches them. The builder (`codemap/`) needs tree-sitter, so `deploy/install.sh` gives
it a virtualenv pinned by `deploy/codemap-requirements.txt`, and hubd stays standard library only. Overview shows failures.

**Code search.** `code_search` runs ripgrep over the copies: a string, or with `regex` a regular expression, optionally in
one repository or path (a folder, a file or a glob), with the line, a little context and the commit of each copy. It reads
every text file in any language, so it finds what the map can't, and the map follows a name or a string to what the search
only mentions. Access is the map's: with no repository named it searches public repositories only and lists what it skipped,
unless the session reads the whole project; forks (`linux` today) only when named. It runs in bubblewrap on a frozen snapshot, so
it needs `rg` on hubd's `PATH` (`deploy/install.sh` says if it's missing; the package is `ripgrep`; no restart after installing it).
A search that's cut, times out (20 s) or has a problem says so. Over all 12 non-fork copies here it takes about 0.3 s, and 2 s for `linux`
when named. `SECURITY.md` has what it can and can't reach.

**Sessions › History & cleanup** lists every session that has ended, with its transcript, and resumes any of
them where it stopped, restoring its checkout at the same path if it's gone. It also lists the worktrees: what's
safe to remove, what isn't and why. Nothing is removed without the commands being shown first, except a
session's worktree 7 days after its pull request merges, which you can turn off. Transcripts are never deleted.

**Plan new work** plans a locked session on a repository: an issue, a security or architecture audit, a
roadmap item, a docs sweep or a dependency review. You read its plan and press Start before anything runs. The session hands in drafts and files nothing. You choose which to
file, or send them to the Steward. Sessions can suggest such work too; a suggestion waits in Needs you and
runs nothing until you start it.

When a full session shows a permission prompt or asks a question, it also appears as a card under
Sessions, in Needs you, and the first answer wins: the card's or the terminal's. The hub waits 10 minutes,
then leaves it to the terminal with nothing approved. A session started before this needs a resume to get
the hook. Locked sessions don't prompt, but every session can ask a question. A locked one's question shows only on its card, and goes
unanswered after 10 minutes, when it carries on without you. The Steward's waits until you answer. The full actions run in auto mode, where
Claude Code decides most commands itself, so from those you'll mostly see questions.

Sessions use the workspace this checkout sits in (`HUBD_WORKSPACE`, by default `~/GlassineOS`):
worktrees come from its main checkouts, which are cloned if missing and otherwise only fetched
into. The exception is the `workspace` repository, whose checkout is that folder itself: a session on it
needs that clone there already, and the hub says so if it isn't. A session never moves a main checkout's files or takes a branch with unpushed commits, and
its commit identity and credentials are set for its worktree only. Overview shows what's in the
workspace; `./ws` there manages tasks by hand.

A session keeps running if the browser, the app or `hubd` goes away. If Claude ends, or its terminal
does, as after a reboot, it shows under Sessions with a Resume button that continues the conversation
with the same checkout and token. A stopped session stays until you discard it.

Once after installing, trust the folder the sessions run in, or each new checkout stops at
Claude Code's trust question until you answer it: run `claude` in
`~/GlassineOS`, accept, and quit. Locked sessions start in `~/.local/state/glassine-hub/home`, and
the first one asks about that folder, once for each Claude login. Accept it: the hub made it, and
it holds nothing from a pull request. Don't trust its parent.

Agents and hub shells get their environment from `~/.config/glassine-hub/agents.env`, because a
service doesn't see your shell's setup or aliases. `install.sh` creates it and never rewrites it.
Name the Claude login there, and any other variable they need, then restart hubd:

```sh
# ~/.config/glassine-hub/agents.env
# which Claude login
CLAUDE_CONFIG_DIR=~/.claude-something
# which Claude Code, if not the one on PATH
HUBD_CLAUDE=/path/to/claude
# seconds between pings to a Steward about changes: 60 to 86400, 300 if unset or not a number
HUBD_PING_SECONDS=300
# dollars for the header's usage meter to compare the cost of today's sessions with, when the status line gives no rate limit
HUBD_DAILY_USAGE_USD=20
```

The header's usage meter reads `status.json` in each session's folder: every session's settings run a status-line
command that copies Claude Code's status-line JSON there (at most 16 KiB, whole or not at all). If the newest has rate
limits that haven't reset yet, the meter shows the fullest (a window whose reset time has passed is ignored, and an
older session's limits are not used when the newest file has none); otherwise the total cost of the sessions active today against
`HUBD_DAILY_USAGE_USD`. That cost is Claude Code's running total for each session, so a session that began on an
earlier day counts whole, not just today's part; the meter says "spent by sessions active today", not a day's spend.
With neither it says "usage not known". The status-line command is the hub's, set for hub sessions through
`--settings`, which wins over your own `~/.claude` settings: in a session the hub starts, a status line of your own is
replaced by an empty one (your settings file is not touched). That is intended: the meter needs the status line. It says "low" from 80 %. Which fields your Claude Code version sends hasn't been tried yet.

The work sync records what changed (an issue, a pull request or a run: its state, head commit, who, when and a link,
never a title or text) in hubd's change feed, `feed.sqlite` in its state folder. Each running Steward reads it from its
own cursor with `changes_since`, and gets at most one ping per interval, only a count, and none when nothing it hasn't
read has changed. A ping is sent only to a Steward at its prompt; during a turn the next round tries again. `/api/changes` serves the same feed to you without moving a Steward's cursor.

```sh
systemctl --user restart glassine-hubd
```

Without `CLAUDE_CONFIG_DIR`, agents use the default login in `~/.claude`. The Overview page shows
which one is in use. Don't keep secrets in this file: its values are written to each session's
start script.

Personas can post as GitHub Apps of their own, not as you:

```sh
deploy/create-app.py reviewer      # also security-auditor, triager
```

It opens GitHub's form with the App described; you press Create, and install it on the repositories
it should work in with the link it prints. No restart is needed, and a session's manifest shows
who it posts as. `openssl` signs the App's requests.

The terminal takes all keys, Shift+Tab included, while it has focus; a message says when it
doesn't, and clicking it brings it back. Drag to select and copy, and use the wheel to scroll. If a program in the
pane takes the mouse, hold Shift while dragging; that selects what's on screen.

To run an agent by hand, choose **New shell** with the command `claude` and the project's
directory. From a normal terminal: `tmux -L glassine-hub attach -t NAME`. Shells started
from there don't have the two variables unless you export them; the token is in
`~/.config/glassine-hub/agent-token`.

Tools that are hard to undo or visible to others (`merge_pr`, `close_issue`, `close_pr`,
`dispatch_workflow`) carry a destructive annotation, so an agent's permission settings can
keep prompting for them. Shells are not a tool.

## If the app stops answering

All of the app runs on one event loop. If the loop doesn't run for 20 seconds, the app writes the
requests in progress and the stack of every thread to its log, and repeats the stacks every 5
minutes while it's stuck. So look before restarting anything:

```sh
docker logs hub-hub-1 2>&1 | grep -A40 "hasn't run"
docker kill -s USR1 hub-hub-1                     # the stacks, right now
systemctl --user kill -s USR1 glassine-hubd       # the same for hubd, in its journal
```

These hold file names, lines, function names and request paths, not values or query strings.
Requests that take over 5 seconds are also logged.

## The docs index

The index is published with the docs site by the docs repository's CI, so keeping it
current means keeping that CI current. The app compares the published commit with the
docs repository's head. A push starts the CI by itself; if the index is still stale after
15 minutes and no run is active, the app starts the workflow, once per commit. **Run docs
CI** on the Knowledge page and the `docs_reindex` tool do the same on request. Searches pick up
a new index by themselves.

## On the LAN

The dashboard stays on loopback by default. Over the network, use TLS: the app refuses to
start on another address without it. Put in `.env`:

```sh
HUB_BIND=192.168.1.5
HUB_ALLOWED_HOSTS=hub.lan:9094                  # names you reach it by, besides the address
HUB_TLS_DIR=/path/to/certs
HUB_TLS_CERT=/tls/cert.pem
HUB_TLS_KEY=/tls/key.pem
```

The tool server always stays on loopback.

## Development

```sh
pip install -e ".[dev]" && app/fetch-vendor.sh
make check
```

`tests/dev_hubd.py` is a `hubd` with a fixed password for trying the app. It accepts any
user with that password, so never use it as the real daemon.

## License

GPL-2.0-or-later (`LICENSE`). The IBM Plex and Kalam fonts are under the SIL Open Font License
(`app/hub/static/fonts/`). The Spec Kit files in `.specify/` and `.claude/skills/speckit-*` come from
[github/spec-kit](https://github.com/github/spec-kit) under the MIT license (`.specify/LICENSE-spec-kit`).
