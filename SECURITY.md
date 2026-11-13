# Security of the hub

This repository's own threat model; the organization's reporting policy is in
`GlassineOS/.github`.

The hub puts a shell on your computer behind a web page, and can act on the organization
with your GitHub login. Treat access to it as access to your account on the host.

## Who this defends against

Everything the hub does runs as the host user, with that user's GitHub login. Whoever logs in could do the same by hand,
and Claude Code runs under the same account, so a full session is effectively that user. Nothing here limits that person.

Two threats are left:

- **Someone without the login** reaching the page, the socket or the token. The table below covers most of this.
- **An agent steered by text it reads.** Anyone can write issues, comments and pull requests on the public repositories, and
  sessions read them. The outsider has no access, but the agent does. The limits on planners and locked sessions exist
  for this, and they're the only reason a session isn't simply your account. They hold through Claude Code's rules, hubd's
  checks and the review sandbox, not through a separate OS user.

A leak of private text needs one session to do three things: read an outsider's text, read something private, and post in
public. A person's approval can't reliably break that chain, because a steered agent writes the reason on its card.

## What protects what

| Asset | Protection |
|---|---|
| Host shell | Needs a session token, issued only after a PAM login for the user `hubd` runs as. The token check is in `hubd`, not the app |
| Password guessing | Failed logins delay the next attempt, doubling up to 30 s, one attempt at a time. The delay is global, so on a LAN someone guessing also slows your own login. The dedicated PAM service keeps failures from locking the account elsewhere. Sessions end after 12 h idle or 7 days, and when `hubd` restarts |
| GitHub token | Stays in the host's `gh`. `hubd` passes a fixed set of variables to it, so `GH_TOKEN` or `GH_HOST` can't be injected |
| GitHub reach | `hubd/ghpolicy.py`: an allowlist of exactly the commands the app runs, GlassineOS only, with search qualifiers that cross repositories refused. `gh api` is read-only. No repository deletion, `auth`, secrets, access changes, admin merges or pushing code. Raw GraphQL is refused: only the documents in `hubd/graphql/` run, and their project and content ids must belong to the organization |
| Host files | The policy refuses every way `gh` reads or writes local files, except stdin |
| Browser attacks | `SameSite=Strict`, `HttpOnly` session cookie. Host must be on the allowlist, against DNS rebinding. Origin must match for writes and for the terminal's WebSocket. Content-Security-Policy without inline or remote scripts |
| Network | Loopback by default. The app won't start on another address without TLS, as long as `HUB_BIND` names the address; `HUB_LISTEN` is for the container and overrides what the app binds. The tool server stays on loopback under compose |
| The container | Runs as your uid, read-only, no capabilities, no credentials. Its only way to the host is the socket |
| A session's rights | Its action's workflow (`agents/workflows/<name>.toml`) holds them: the effective grant of the state the session is in, its first at launch (most actions' default workflows have one state; `implement`'s has steps and runs sandboxed). The action file holds none (hubd refuses one that sets any), so they are said once. hubd builds the tool lists, the permission mode, the checkout and the token's scope from that grant, and won't start on a workflow its checks refuse. The action's `ceiling` is that grant in plain words |

## Guards, not limits

The table above lists limits: each one stops a threat named at the top. Guards are different. They catch mistakes and collisions, by making a session stop and ask or by leaving a trail. Anything running as your user can get past one, so none of them holds against a misled full session.

- **The device lock and goes** (`workspace#6`) stop two sessions using a device at once, and device actions you didn't agree to.
- **Merge decisions for full sessions and hub shells** stop a merge nobody asked you about. For sessions held to a tool list they're a limit.
- **`art rm` retention** (`workspace#2`) stops a kept file being deleted by mistake.
- **Ignored-file checks on removal** stop files being lost with a worktree.
- **The prompt rule in `agents/private.md`** helps against a session posting private text by mistake. It isn't a limit on a steered one.
- **A full session's workflow grant.** A state that grants `access = "full"` runs the agent with your rights: its tool list and the
  check before each tool use (Workflow moves) don't hold it, and its confirm marks that.

A new restriction has to name the threat it stops, or be listed here as a guard.

## What this does not protect against

- **A compromised app container.** It sees passwords as you log in and session tokens as
  you use them, so it could open a shell then. It can also use `gh` within the policy
  without any login, and read the tool server's token as it passes through. The container
  limits what a bug in the app can do while nobody is using it; it isn't a boundary against
  malicious code in the image. Pinned dependencies and a small image are the defence.
- **Other processes running as your user.** They can reach the socket and read the token
  file, as they could read your `gh` login anyway.
- **Text that agents read.** Issues and pull requests can be written by outsiders. The
  planner and the locked actions only have the tools their action's workflow grants, enforced by the
  command line `hubd` builds after checking the plan against that grant, and they ignore a
  pull request's own CLAUDE.md, MCP config and hooks. Their file tools reach only their
  working directory, the checkout, and the snapshots of the organization's repositories below, so
  an agent that can post can't be talked into posting your other files, though it can be talked
  into posting from those repositories. This was tried with a real session: a snapshot added after
  it started can be read, a file outside can't, and neither can one through a symlink pointing
  outside. They can still be misled within those
  tools, for example into posting a bad comment. A full session on an outsider's issue can be
  misled with your full rights, as if you had pasted the issue into your own session; only
  forks' pull requests are refused, and for a run's fix (`run-fix`) a run of a fork's branch: hubd reads the run
  first and starts the new branch only from a branch of the repository itself. Each session has its own tool server token, in a file only
  your user can read, and the tool server refuses any tool outside that session's list, so a
  locked session is held to it whatever Claude Code does. Shells keep the one general token, and
  a full session could read that file, as it can anything of yours.
- **Private text in a public post.** A locked session can read a private repository by naming it, and it can post, so
  nothing technical stops a misled one from putting private text in a public comment. This is accepted, without an extra
  card to ask first. The one measure is a rule in every agent's prompt, `agents/private.md`, which helps against
  accidents and is exactly what an injection tries to override. The safety scan is no help here: it sees only what goes
  into git, and it matches file types, keys, tokens, addresses and paths, so it can't recognise private code.
- **The repository copies.** The hub keeps a clone of each repository in the organization under
  `~/.local/state/glassine-hub/seeds`, private ones included. `request_repository` gives a session with
  file tools a snapshot in its own folder, and `list_repo_files`, `read_repo_file` and `code_search` serve the Steward,
  Knowledge's research session (`knowledge-research`) and every planner, none of which have file tools. The research
  session reads the whole project like the Steward, but has nothing that writes or posts: its one way out is the report it
  hands in, which only a login reads (and keeps), so private text it read reaches you and no one else. A follow-up
  pins a kept report by its id, and `read_report` gives a report only to a session started with it pinned, so its text
  never sits in Launch, where the action could be switched to one that posts. There's no question asked and no difference by repository, by your
  decision, so what was said above about private text reaches all of them. Actions with neither those tools nor
  file tools, such as `issue-triage` and the `run-*` actions, have no direct way in, but their planners do, and a
  planner writes the session's brief, which you see before it starts.
  The worst case is a review on an outsider's pull request: `pr-review` and `pr-security-audit` have a shell
  with the internet as well as `request_repository`, so an injection there can read any private repository's files and send
  them out with no visible post. The snapshots aren't mounted in the shell, but the session's file tools read them, and
  it can type what it read into a command. This is accepted. Comments, drafts and tool arguments can all carry what a session
  has read too, including drafts from the `new-*` actions, which you read before filing. The drafter has none of these
  tools: that keeps a draft to the item it's about, and isn't a boundary the others share.
  These are the hub's own clones, never main checkouts, so ignored files such as secrets
  aren't in them. A read-only snapshot prevents accidents only: any process running as your user
  can switch that off, and what keeps a locked session from doing so is having no shell outside
  the sandbox. Full sessions get a worktree on their own branch, and what they write reaches neither
  the copy nor another session. Only the organization's repositories are copied. Ended sessions keep
  their snapshots until they're removed, which holds on to old data; the Overview lists them.
- **The code map.** A map under `~/.local/state/glassine-hub/codemap` describes private repositories, and it reaches the
  same sessions as the copies, through tools with the same list, so what's said above about private text applies. Everything in
  it can be read from a copy by naming the repository, so it adds no access. It would add a way to find private code by
  topic, so it keeps the line `work_search` keeps: with no repository named, hubd answers from public repositories only and
  lists what it skipped, by the session's token, except for a session that reads the whole project. Every repository it names
  says whether it's private. It's never indexed for the docs search.
  tree-sitter's C parsers read whatever is committed, so hubd doesn't load them: `codemap/` runs as a separate process under
  bubblewrap with no network, seeing the system's programs, its virtualenv, its own code, one frozen tree, the last map
  read-only, and an empty scratch folder. It reads through git objects, so a link in a repository leads nowhere. hubd keeps a
  bounded part of what it says, and limits its address space, file size, time and priority, because this host is someone's
  desktop. Total disk has no hard limit: the scratch folder's size is checked each second and the build stopped past 1 GiB, so
  a fast writer can overshoot by what the disk takes in a second. A subverted build can spoil its own repository's map and
  no other's: it can't write where maps are kept, hubd moves the result there only if it's a regular file that says the right
  commit, and hubd opens maps read-only with SQLite's defensive mode on and `trusted_schema` off. A map that can't be read is
  listed as not searched, and takes no other repository's answers with it. Agents read a map as data.
- **Code search.** `code_search` runs ripgrep over the same copies, for the same sessions as the map, by the same tools list. Every
  line it can return is in a copy that `read_repo_file` or `request_repository` already gives a session by naming the repository, so
  it adds no access to files. What it adds is finding private text by topic, so it keeps the line `work_search` and the map keep, and
  through the same code, `hubd/reach.py`: with no repository named it searches public repositories only and lists what it skipped in
  `not_searched`, by the session's token, except for a session that reads the whole project. A named private repository is searched
  and says it's private. Forks are the one place it differs from the map, and that's about cost and not access: it leaves them out
  unless one is named, because `linux` is 96,000 files that mostly aren't ours and would be searched, and then deleted, on every
  query. Unnamed, a fork is listed in `not_searched`. A named fork is searched, as `read_repo_file` reads it.
  The copies are text anyone may have written, so hubd doesn't search them itself: ripgrep runs as a separate process under
  bubblewrap with no network, seeing the system's programs, itself if it's installed outside `/usr`, and one frozen read-only
  snapshot of the one repository it is searching, taken with the same lock as any other snapshot, so a refresh can't change it
  meanwhile. Nothing of the host is writable: the root is remounted read-only, which leaves only `/dev/shm`, in memory, and gone
  with the process. It runs with no environment, so none of hubd's, and with `--no-config`. A process searches one repository,
  so a subverted ripgrep can forge results, but only for the repository it was given, which hubd labels by process and not by what
  the output says. hubd limits its address space (2 GiB), file size, priority and core files, the same as for the map's builder (both start their program through `hubd/limits.py`), stops it after 20 s and says it timed out, runs
  at most two searches at once, and reads a bounded part of what it prints: a line of at most 300 bytes shown, 5 matches per
  file, 200 matches from a named repository or 40 from each of several, and a reply of at most 40,000 characters in all: the
  matches are shared between repositories in what's left after everything else in the reply, so a long `not_searched` (cut at 8,000 characters, with a count of
  what it left out) or a long list of files with more matches than are shown doesn't push it over. What each repository says about itself is still in it,
  so that holds for a few dozen repositories searched in one reply (the organization has twelve), and not beyond. It keeps the end of what ripgrep says on stderr, 600 bytes, and reports it, even if matches were found: an
  exit status of 2 is a problem the reply names, and a result that was cut, timed out or had a problem says so and isn't `complete`.
  What a query can do: it reaches ripgrep only as the value of `-e`, and a path only as the value of `--glob=`, so neither can
  be taken for an option, and a query is one line of at most 500 characters. A regular expression runs in ripgrep's default engine,
  which has no backtracking to blow up, and not PCRE2; the time and address space limits are what end a regex that's slow anyway.
  A path is checked as `read_repo_file`'s is, can't start with `!` or `/`, and is only ever a glob inside the frozen tree, never a
  path on the host. Links aren't followed (and one that leads outside the snapshot leads nowhere inside the sandbox, which has
  no other files), `.git` is left out, and `.gitignore` and `.ignore` files in a repository don't hide anything.
  The frozen tree is made for each search under `~/.local/state/glassine-hub/search`, mode 0700, and removed after it. Taking a
  large one apart takes a few seconds without root, so that happens after the reply, and a stop halfway leaves one that's removed
  at the first search after the next start. On a host that can't snapshot, a tree is a full copy, which for `linux` is a lot: it isn't waited for past the
  time limit, and is discarded when it's made. Replies describe private repositories, so they are never indexed for the docs search.
  ripgrep isn't a dependency of the hub's code: `deploy/install.sh` says if it's missing, and hubd looks for it on its own `PATH` at
  each search, so installing it later needs no restart, and until then the tool says so.
- **The review shell.** The two review actions list Bash, for running a pull request's code and tests. Bash is
  left off their allowed list, so under dontAsk a command runs only when `hubd/shell_hook.py` allows it, and it allows
  it only rewritten to run inside bubblewrap and pasta. On a failure the hook says deny. A hook that can't answer at all
  is no opinion to Claude Code, which then still runs what it considers a read-only command. So every command also
  passes `hubd/shell_guard.py`, Claude Code's shell prefix, which refuses anything but the hook's sandbox command, marked
  with a secret from the session's folder, and the session's own hooks. Both were tried with a real session.
  Inside: the system's programs, `/etc`, the checkout and its git store as overlays, its own home and `/tmp`, and no
  environment. So no tool token, `gh` login (but see the GitHub token below), SSH key, other files, the hub's socket, or the host's loopback and abstract
  sockets. Writes land in the session's folder and never in the real checkout, so nothing the hub's own git does can run
  what a pull request planted, and the file tools still read the tree as it is. pasta's sockets are this host's, so without
  more they would reach the hub's container, the docker gateway and your network. Routes set before bubblewrap starts,
  which code inside can't change, refuse private, link-local and CGNAT ranges and this host's own addresses, and there's
  no IPv6. So the login and tool server aren't reachable from a pull request's code.
  Limits, accepted:
  - It has the internet, so a misled session can send out what it can see, unlike its comments, which are visible and go
    through the hub's policy. That's the checkout, the whole review clone with every pull request head fetched into it, a
    private repository's code among it, whatever this user can read under `/etc`, and what its tools return: `work_search`
    can name a private repository, so a session on a public pull request can read private text and send it. The snapshots
    aren't mounted in the shell, but its file tools read them, so the same goes for the tree of any repository in the organization.
  - It can fill the disk, as there's no quota.
  - The git store under an overlay is the clone the hub fetches into, which the kernel leaves undefined: odd git results
    inside, for the length of a command.
  - A kernel or bubblewrap bug would be a way out; the hub is not a stronger boundary than those.
- **A shell's GitHub token.** An action whose workflow grants `github` capabilities, and a launch that carries them, give a locked
  session with a shell an installation token of its persona's App, limited to the session's repositories and the
  permissions those capabilities need (`hubd/apps.py`, `permissions_for`). hubd writes it to a 0600 file in the session's
  folder and renews it while the session runs; the sandbox mounts that folder read-only and each command gets it as
  `GH_TOKEN`, and git as a credential for `https://github.com` only, read from the file and never on a command line. What
  fences it is the token's scope on GitHub, not `ghpolicy`: the command can do whatever the token allows. Pushing and
  merging are both contents write, so a grant that can push can merge. Whatever runs in the shell holds it: that includes a pull
  request's own code, which its tests run, so a session on a pull request from a fork keeps only its read capabilities, at start
  and at resume, and so does one whose pull request GitHub can't confirm as the repository's own (any covered one).
  A same-repository pull request's code can still use every capability the launch carries and send the token out. It
  works until it expires, up to an hour after its last renewal, also after the session ends. A launch with a list and no
  token doesn't start; one without a list gets none, as before. Full sessions are unchanged: they use the host's `gh`
  login, guarded by hubd and not limited by a token.
- **Resuming a session.** A session that has stopped keeps its record, tool token and checkout until
  you discard it, and Resume starts it again with its conversation. It needs a login, like starting
  one. Its rights are checked again against its action's workflow as it is now (for a session that can move, its current
  state's grant), and it refuses if they don't
  fit. The conversation itself comes back as it was, including any outsider's text it had read.
- **Personas on GitHub.** A persona with a GitHub App (`apps.toml`, made by
  `deploy/create-app.py`) makes its writes as that App: GitHub limits it to the App's
  permissions and the repositories it's installed on, and its name shows it's an agent. Its
  reads stay on the hub's login. hubd chooses the App from the session's tool token, and if it
  can't get a token the write fails rather than going out as you. Private keys stay on this
  computer, 0600. Full sessions and personas without an App post as you. The reviewer's App can
  approve, so if an approval ever counts toward merging, a misled reviewer could give one.
- **Results are handed in, then applied by you.** A session's own token can hand in one result of its action's type
  (`submit_result`), in a closed shape with every string capped; a labels result names only the items the session was started on.
  It changes nothing outside the hub. Only a login applies it, and hubd writes it only through the tools the producing action
  names for its result (`result_tools`, read from the action as it is now): the same `gh` command `label_issue` sends, `edit_issue`'s
  "Part of" line on an issue the organization wrote, or one review by the `pr_review_add` document, whose pull request must be the
  organization's and whose notes are a closed list. It goes out as that persona's App, as the session's own writes would. So
  `pr-review` no longer posts a review by itself and `issue-triage` no longer labels: you read what they hand in and press Post or
  Apply. A session started before this keeps its own tool list, so it may still post directly; its text is still an outsider's
  where it read one, so read a result's text before applying it.
- **Trusted folders.** Trusting a folder covers everything below it. `~/GlassineOS` holds no
  fork's tree: a pull request under a locked review is checked out in
  `~/.local/state/glassine-hub/sessions`. Sessions start in the `home` folder beside it, and only
  that one needs trusting. If you trust the parent, a `claude` you start by hand in a fork's
  checkout there would load its project settings: don't.
- **The workspace.** Full sessions share git objects and hooks with the main checkouts, and have
  your rights, so they could change either. What the hub itself does there is limited: it fetches,
  adds worktrees, and removes a session's own. A pull request under a locked review comes through
  a bare clone of the hub's own in `~/.local/state/glassine-hub/repos`, with no hooks, so nothing
  of a fork's touches the main checkouts or runs by being checked out. Filter drivers in your global
  git config, git-lfs for one, still run on that tree.
- **Agents in hub shells.** They have your user's rights by design. The tool annotations
  are a hint to the agent's permission prompt, not an enforcement. `hubd`'s policy applies
  to the tool server, not to what an agent does with `gh` in its own shell.
- **Workflow starts within the organization.** The policy allows them because managing them is
  the point.
- **Workflow inputs.** Whoever reaches the socket can start a workflow with inputs of their
  choice. Workflows must not put `inputs.*` directly into a `run:` step, or those inputs
  become code running with the repository's `GITHUB_TOKEN`.

## Workflow moves

A session whose workflow has more than one state can move between them (spec 012), by the machine or by your hand. What it may do is
its current state's effective grant and nothing else; `hubd/effects.py` applies each move to the running session.

- **Narrowing is at once.** What the new state doesn't grant goes from the session's tool token (the tool server refuses it on the next
  call) and from `grant.json` in its folder, 0600, which `hubd/grant_hook.py` reads before every tool use and refuses any tool not
  on it. The hook only refuses (exit 2) or says nothing, never allows, so the shell's sandbox hook still decides a command; it refuses
  when it can't read the file, and its command ends in `|| exit 2`, so one that can't start refuses too. A hook past its 10 s timeout
  is ended by Claude Code, which then runs the tool: for Claude Code's own tools the check is a guard there, and the tool server still
  refuses a hub tool by the token. A session whose grant can't be worked out after a move is locked: its token and the hook refuse
  everything, kept on disk across a restart of hubd, until a resume.
- **A session whose workflow can move never falls back to its first state.** Whether it can move is read from the definition its
  machine runs on. One whose machine record is lost or can't be read is refused (resume, a resume from the history) rather than given
  a fresh machine in the first state, whose grant may be wider than what it was in. A move while a resume is set up makes the resume
  start over from the new state, and a GitHub token made for a list that is no longer in force isn't written. A GitHub token is made again with fewer capabilities; the old one works until it expires, up to an hour. The
  session's record says what is in force, so a restart of hubd or a renewal doesn't give back what went. Nothing is added this way.
- **Widening is deliberate.** A move to a capability the instance has never held waits for your confirm, a `machine.widen` card in
  Needs you that hubd alone makes (`decision.add` and a token's `decision_request` refuse the kind). It names the move, what it adds,
  takes away and keeps, and marks the sensitive items and a full grant; approving it confirms that move and nothing else, and it ends
  at once. A move that adds anything, confirmed now or before in the instance, takes effect only by resuming the same conversation
  under a new launch with the new state's grant, once the session is at its prompt. A stopped session isn't started for it. A
  relaunch still waiting when hubd stops is lost: the session keeps the old launch until it is resumed, which takes the new grant.
- **A conversation keeps its access and its checkout.** A move to a state with other ones fails back: one that waits is declined,
  one that happened is rolled back (logged as the hub's), and the evaluation log says why. Resume refuses the same.
- **The words a move adds** are the definition's instructions, marked as the hub's, never text from a transcript.
- **A full session's state is guarded, not limited** (Guards, not limits): it has your rights in any state.
- **The notes** stay with sessions that can't carry them out: a workflow whose states can read them only loads if every state only
  reads (Notes).

## Device reports

`dev` on the host sends hubd a snapshot of a device's lock and state at each lock move, and hubd keeps the last one per device,
in its state folder, with the host's time. The hub never asks the device, runs no tests and doesn't take the lock. So:

- Anything on the socket can send a report, with no token. A forged one can't take or free the lock, which only `mkdir` on
  the device does, but it can mislead you and agents. So nothing says a bare "free" or "held": it's sentences with an age, and
  each answer ends "Only `mkdir` on the device decides". A by-hand `mkdir` doesn't report at all.
- What a report holds is capped and stripped of anything that draws nothing, by the same rule as a card. The hub keeps a small
  number of devices, so a stream of names can't fill the disk. Past that the oldest report goes, so such a stream can push out a real
  device's report until its next one, and a view without it says there's no report. A device's name can't leave the folder.
- A report file that can't be shown is left out at start, with a warning, and the device's next report replaces it.
- `purpose`, `notice` and the rest are free text, so the tool's answer marks them as data for agents. That's a hint to the
  agent and no more.
- `device_status` is by list, because a report's text is free. No locked action lists it, nor does the Steward, and hubd checks
  the list as well as the tool server. Full sessions and hub shells can read it. The page needs a login.

## The usage meter

The header's meter reads `status.json` in each session's own folder, which a status-line command in that session's settings writes from
Claude Code's status-line JSON. hubd never asks Claude or the network for it.

- **`usage.status` needs a login** (the `usage.` prefix in `Hubd.request`), and the page reads it through `/api/usage`, with no token path.
- **The command writes one file in its own folder.** Its path is fixed when the settings are written, it keeps at most 16 KiB and drops
  anything bigger whole, and it prints nothing into the session's terminal. A session runs as your user and could write the file
  itself: that can only change the meter's words, which say "usage not known" for anything they can't read as numbers.
- **The `ping` reply names hubd's socket path**, for the header's "connected to". Anything that can ask is already on that socket.

## The change feed and the Steward's pings

hubd keeps a feed of what changed in issues, pull requests and runs (`feed.sqlite` in its state folder), and pings each running
Steward with a count. The work sync records into it; the Steward reads it with `changes_since`.

- **Facts, not text.** A row is the item, what changed, old and new state, old and new head commit, a time, a login or nothing, and a link
  hubd builds itself. `hubd/feed.py` checks every field against a closed shape and drops what doesn't fit, so a title, a comment, review
  text or a log line, which can be an outsider's, can't reach the feed, whatever the app sends. `old` and `new` are from a fixed list for
  each kind of change (GitHub's own states, review decisions and run results, the checks words, or a count), and the repository is one of the
  organization's. What stays free is `actor`: a GitHub login, up to 39 characters (44 with an app's `[bot]`), which whoever owns the account chooses. A row can carry
  that much of an outsider's wording, so the Steward's persona and the tool's description say it is a name to look at and never words to
  follow. Anything on the socket can send a row, as it could send a device report, and the worst it does is mislead with a state or a login.
- **A ping is a count, labelled as the hub's.** `1 change since 15:02 UTC: 1 merged.` in a fixed vocabulary, with no repository, number or name,
  between two random lines, from `@hub`, which is no session's name. It uses the same paste as a message between sessions, and is not the
  Steward-to-session path, whose no-card rule is for read-only sessions. A count is only sent to a Steward that is idle, with nothing queued for
  it and an empty prompt: during a turn it isn't queued (it would be pasted after the Steward had read what it counts) and the next round, 30
  seconds on, asks again. A stopped session is never pinged and never started. Waking an idle one is checked, under the same lock, as starting a session is: it is refused while
  4 sessions the Steward started are working. The Steward is started by the person, so it is not one of the 4, and its pings pause while those 4
  work (which is when their pull requests change); the next round asks again and the feed holds everything. Each item with new comments counts once per sync, however many comments it got.
- **What a session may read decides the rows and the counts.** The Steward's workflow grants `all_repos`; a session without it, or the general tool
  token, gets public repositories only, in the feed, in the counts and in the ping. Whether a repository is public is asked of GitHub and
  kept for 10 minutes (1 minute when it didn't say); if GitHub doesn't say, it's private. The cursor is a number over every change, and when
  a read finds nothing it may see, the cursor goes to the newest change there is. So a session that can't read some learns how many changes it
  can't see and when they came: its cursor jumps by the count between two reads (1 to 7 after six private changes). It learns nothing else of
  them: no repository, number or text. The readers are the person's own sessions, so this is accepted. If more actions get `changes_since`
  without `all_repos`, each reader needs its own ids. The consequence of failing closed: a session
  limited to public repositories that reads while GitHub can't be asked about a repository doesn't see that repository's changes, and its
  cursor moves past them, so it doesn't see them later either. The Steward has `all_repos`, so this is for the general tool token and
  sessions without it. The cursor is not held back for a repository GitHub couldn't be asked about, because a deleted or renamed one would hold it back for good.
  The same loss happens to the first change in a repository that arrives while the answer from GitHub is awaited: the read's list of public
  repositories was made before it, and if that read finds nothing else, its cursor passes the change.
- **A cursor can't be past the end.** One a caller supplies must be one an answer gave: a number above the highest ever issued (counted by
  SQLite's sequence, which pruning doesn't lower) is refused, as the kept cursor only moves forward and one such would hide everything after it.
  A Steward's cursor starts at the newest change when the ping loop first sees it running, which is within 30 seconds of its starting: what
  happened before it existed isn't a reason to wake it. A read before that first look, or by a session the ping loop doesn't know, starts from the
  oldest change kept (up to 14 days or 20,000 rows). For anything older, the Steward reads the item lists.
- **Its own doing is marked, not hidden.** A write by a session's token (`gh` through hubd) marks the item for 15 minutes, and changes to it
  that arrive then are marked `own` for that session and left out of its counts. It can't tell a stranger's comment on the same item in
  that time from its own, so it errs toward calling it its own. Everything stays in the feed.
- **What waits to be sent can be lost, and is counted.** The app writes each change it sees to an outbox table in the same transaction as the
  item, so a failed sync tick or a restart loses none. It keeps at most 5,000: beyond that the oldest are dropped. Dropped and refused changes
  are counted in the work status (`feed_dropped`, `feed_refused`), and `feed_waiting` is how many wait. The outbox is in the work store, which
  is a cache dropped when its version changes: what waited in it then is lost, so a version bump should wait for `feed_waiting` to be 0.
  Changes to a run first seen finishing more than 2 days ago aren't sent: a pruned run that the latest-runs window returns again isn't news.
- **Nothing acts on a ping.** It asks for nothing and the persona says to re-read. Any write still asks first.
- **`changes_since` is by list,** read-only, on the Steward's only. Under your login the page reads all of it and moves nobody's cursor.

## Workflow signals and moves

A session's workflow moves on its own only on a signal: its own hook (a turn ended, it ended, a tool ran, a compaction
is coming), a change the feed stored for an item it covers or a pull request the hub has seen for it, or a hub event
such as a decision answered for it (`hubd/machinerun.py`).

- **A signal carries no text.** The hook (`hubd/machine_hook.py`) sends the session's own token and the hook event's name,
  never the tool's input or output, and hubd maps that name through a closed list; the shared tool token is no session and
  is refused. A feed signal is a feed row, which is already only facts. The hook sends one line and never waits for hubd,
  so a stopped or slow hubd costs a lost signal, never a held turn; only sessions whose workflow names a session signal get it.
- **Transcript text reaches the judge only as data.** The judge sees the rolling summary and the last turn inside its
  boundary-marked data blocks (FR-015, FR-017), nothing else of the transcript. A judge configured on a hosted
  chat-completions endpoint sends that text off this host to whoever runs the endpoint: choose one in `judges.toml` with
  that in mind; the default runs on the subscription, as the sessions do.
- **A move still needs its facts.** Words in a transcript (an issue body, a review comment, a log) that ask for a move can at
  most sway the judge's pick. The hub then checks every `requires` against what it knows itself (the counters, the feed, the
  pull requests it has looked up); a fact it can't tell doesn't hold either way, a failed or malformed verdict moves
  nothing, an exit with `approve` above `none` doesn't move on its own, and every evaluation is logged with each check
  and its value. Exits decided by hand or moved on request are never tried by a signal.
- **A request to move is the session's own, and only a proposal.** `request_move` reaches hubd's `session.request_move`
  with the session's own token, which names the session and its conversation: the request can't name another session, a
  token from an earlier conversation under the same name is refused, and the tool must be on the session's list. Only an
  exit of its current state marked `move = "on-request"` can be taken, and only if its `requires` hold; it is logged like
  any evaluation.
- **An approval is the maintainer's.** An exit that holds and whose `approve` names a level becomes a `machine.approve` card
  in Needs you, made by hubd alone (`decision.add` and a token's `decision_request` refuse the kind), one per session,
  state, version and exit. Approving it makes that move and nothing else, and only if the session is still in that state
  on that version and the exit's `requires` hold again; it ends at once, and ends unanswered if the session moves another
  way. The levels other than `me` name sessions that don't exist yet, so they ask the maintainer too.
- **Implementation leaves its states only with a pull request** (FR-012). The checks refuse a workflow with an exit, other
  than one by hand or to a final state, from a state whose grant has `push` to one without it, unless it requires
  `pr.open`. In `implement`, review drops `push`, so its token can't change the branch under review, and merge-ready asks
  first with `merge_pr`: a merge needs your decision for the head, as for any session on a list (Merges).

## The person's decisions

Goes and merge approvals, each a file in hubd's state folder, on disk before anything acts on it.

- **Only a login makes one current.** `decision.add`, `.approve`, `.deny`, `.end`, and "I've got the device" are behind the login check in
  `Hubd.request`. A session's token can ask whether one covers it, spend a run of one that does, ask for one on a card, and end a go, as
  that only narrows. A card can be narrowed by a go's actions and nothing else, and shows the session's reason as its words, not yours. A merge binds the head and base
  GitHub says at that moment: if GitHub can't say, nothing is recorded or approved, and a card whose base has moved is refused.
- **Who it answers to.** A decision for a named session answers only to that session's own token, and only for the conversation that
  held the name when it was asked for or recorded, as names come back. One whose conversation isn't known answers to nobody, and can't be
  recorded. A session can't choose who its card is for: it's always for itself. A hub shell's general token matches only `any`. Hubd knows that token from `auth.check_agent`'s check, and
  no token at all gets nothing.
- **`decision_check`, `decision_request` and `decision_end` are by list.** No locked action lists them, nor does the Steward, and hubd
  checks the list too, as a go's words and a card's reason are free text.
- **Needs you is a view, not a store.** `interaction.list` and `interaction.answer` are behind the login check in `Hubd.request` (the
  `interaction.` prefix), with no token path. The list only reads asks, decisions and new work; an answer is sent on to the source's own
  op (`ask` answer, `decision.approve`/`.deny`/`.end`, new work's dismiss) by the id's prefix, so it can't do what those can't, and a go is never
  approved "always". The `where` a page names is checked against a fixed list and kept as a claim, with your user as who answered.
- **"I've got the device"** is one read with no token, so `dev` can ask from anywhere. Anything on the socket can read that, and can't
  change it. It ends every recorded device go but an eye test, and survives a restart. It can't stop a running command.
- **The limit.** Full sessions run as your user, so one could write these files directly. This stops mistakes, relayed quotes and misled
  locked agents, not a session attacking its own user. With the hub down `dev take --go-said` is a rule with a trail in the lock record, not a
  control: nothing proves you said the words.

## Notes

The notes are kept for agents to read: what earlier sessions found, so the next one doesn't work it out again. They live on this
host only, and much of what they hold never passed the safety scan. The app's container mounts none of it.

- **Sessions that only read search them.** `notes_find` (`notes_tool.find`) is on the list of a locked action that only reads
  and hands in: no shell, no write or post tool, no `plan_work`, nothing that asks first. Its workflow lists it, and the library
  refuses to load one that lists it and doesn't fit, or fits and doesn't list it, so a new action that can post can't have it. Today
  that is `notes-compact`, `notes-sweep`, `knowledge-research` and the `new-*` drafters. hubd takes it from such a session's
  own token, from a full session's, and from the general token a hub shell holds. Full sessions and shells could read the
  files anyway. The page's own search (`notes.find`, `notes.status`, `notes.totals`) stays behind the login check. A session
  started before the tool was on its action's list keeps the list it started with, and a resume doesn't add to it (only the
  Steward's list is rebuilt from its workflow, and that has no `notes_find`): it takes a new session.
- **A locked session gets the notes and not the archive.** The tool also indexes the sources set for this host: the old
  tree's docs and diaries, memory and transcripts, which never passed the safety scan and hold what tools were asked and what
  they answered. It has no filter, so `Notes.find` drops those rows (`archive, unreviewed`, and any state it doesn't know) from
  the search of a session whose token has a list, with the sources and warnings the tool names, which are paths on this host.
  A full session and a hub shell get every row.
- **What needs care is a note leaving.** A row can hold private detail, and nothing technical stops a steered session that
  can post from putting it in public: a comment is not scanned (`comment_issue` and `comment_pr` go straight to GitHub), the
  safety scan sees only what goes into git, and only the Steward's writes ask you first. So the tool is kept off the sessions
  that can post or send, which is a control: `issue-triage` (`comment_issue`), `pr-security-audit` (`comment_pr`), `pr-review`
  and `pr-security-audit` (a shell with the internet) and the Steward (writes that ask first). It is also kept off whatever
  holds `plan_work`, which only reads but puts a session's words in front of a planner as your own notes once you press
  Start: the actions above, `pr-explain`, `pr-merge-prep` and the `run-*` actions. What a session that has it reads leaves in
  what it hands in (drafts, a report, a result), which you read before anything is filed or applied, and in its own words,
  which the Steward can read with `session_summary`. `agents/private.md`, in every agent's prompt, asks it to leave a note out
  of anything public, in its own words too: that is a rule, not a control. Draft issues from a notes sweep are filed by you,
  in public, so read them for private details first. "Send to the Steward" works on them as on any drafts: only by your
  press, and then the Steward reads what they carry of the notes, and each issue it files still asks you. So read them
  before sending them too.
- **Planners.** The planner of a locked action has `notes_find` too, without the archive, and what it finds can end up in the
  brief it writes, which you read before the session starts, as with `work_search`. The planner of a full action has neither:
  a full session's brief comes from it, and a note can carry an outsider's text, as a work item can.
- **Not held by the line the other searches keep, so kept off instead.** `code_search`, the map and `work_search` don't give a
  session that can post private text by asking about a topic: with no repository named they search public repositories only
  (`hubd/reach.py`). `notes_find` has no such line. It searches every note by a word, so a session that can post and had it
  could find any note it liked, which is why it isn't on one, and why the shell is no way round it: `pr-review` and
  `pr-security-audit` can send what they can see to the internet with no visible post, and neither has the tool. Accepted, as
  for every file of yours: a full session and a hub shell can read all of the notes and the archive, and can also post and
  send.
- **Applying note operations is a login's alone.** A notes result is a closed list of operations (supersede, merge,
  distil, retract, answer, add), each checked against the tool's own shapes (topic `AREA/TOPIC`, ids `cN`, one-line words
  with nothing invisible). hubd builds each command from those fields and never takes one from the payload; the card shows
  it verbatim, and applying runs exactly it, through `result.apply` behind the login check, never by a token. Each is one
  `notes add` or `notes set`, its values after `=` or `--` so no text can be read as a flag. None deletes a note: what is
  replaced, retracted or closed stays in the topic's Log, as the tool keeps it (009 FR-006, 005 FR-021). The tool lints, scans
  and commits each write itself; a write it refuses stops the rest, which stay to apply again. Each operation's state is on
  disk as it starts and as it ends, so one that was running when hubd stopped, or that the tool didn't answer in time, is
  marked unknown, not pending: it never runs again until a login has looked at the topic and said it isn't there.
- **The tool stays a program.** hubd runs `tools/notes find` (and, for a login's press, `add` or `set`) from the workspace as a subprocess, never imports it, with a short
  environment, and what you typed follows `--`, so it's only ever words. It creates nothing: if the tool or `notes/` isn't there, hubd says
  so in words. The index is the tool's own 0700 cache, and hubd doesn't read it.
- **What you look for stays out of addresses.** The page sends it in a POST body and keeps it out of the location, which the Steward's
  panel reads, so it isn't in access logs or browser history. The answer isn't kept: not in the work store, not in the browser's storage; hubd keeps only your last search's counts per
  label and topic, in memory, for the totals; a session's search doesn't change them. Note operations a session proposes are kept like any result, in hubd's 0700 state.
- **Every row says what it is,** in words, and a row without a state says so, so a retracted theory can't pass as a fact.
- **The limit.** Anyone with the login reads everything the search covers. Full sessions run as your user and can read the same files, as
  `docs/workspace.md` says. The tool runs with hubd's rights, so whoever can write `tools/notes` in the workspace runs code as you, which a
  full session could do anyway.

## Merges

Every `pr merge` that goes through hubd needs one of two things, checked in `Hubd.request`, as the policy's `check()` sees only the arguments:

- **A login token, from the page.** A click binds the head the page showed, so a pull request that moved since fails.
- **An agent token with a matching decision:** repository, number and head, and for a decision made for one session, that session's. A locked session
  without `merge_pr` on its list has no use for one. Allowing a `merge_pr` card records a decision for its head and that session, for as long as
  the card's grant lasts. No answer from before counts: a grant alone doesn't merge, and neither does a yes in a conversation.

So an agent session's merge through hubd goes ahead only under a decision you approved for its current head (006 FR-010); every other merge
the app makes is your own Merge… on the work item. That is a rule of hubd's path, not of the session: a full session, `run-fix`'s among them,
runs as your user and can read the shells' general token, so it could merge around hubd (the limits below). The Queue view merges nothing: approving a set there records that decision.

Both need `--match-head-commit` with the head in full, and hubd compares it with the decision's. Only the form the app builds passes, so no `--auto`.
hubd also reads the pull request before an agent's merge: a moved head ends the decision, and another base refuses it. The decision is marked on disk
before the merge runs and then records how it went. A merge GitHub refuses, for red checks or a conflict, doesn't spend it. One whose outcome isn't known
does, and says so, and that includes hubd stopping during it.

The limits:

- **A retarget between hubd's read and the merge isn't caught,** as `gh` can't name a base. A move of the head is, by GitHub.
- **Full sessions run as your user,** so one could merge with its own `gh`, or write the decision's file. For sessions on a list this is a limit. For full
  sessions and hub shells it's a guard: it makes them stop and ask, which catches mistakes and relayed quotes, and doesn't hold against a session attacking its own user.
- **GitHub doesn't back this up on private repositories.** Branch protection isn't available to them on the organization's Free plan, so hubd is the
  only check there, and only for what goes through it. On public repositories it could be added. With an admin login `gh` could bypass it, which the policy
  refuses (`--admin`), but GitHub itself only holds admins to rules that are set to include them.
- **A click has no read of its own,** so a retarget since the page loaded isn't caught, only a moved head.
- **A card and a terminal differ.** A full session whose `merge_pr` prompts shows a card. Allowing that makes a decision, as on any card. Saying yes to
  the same prompt in its terminal doesn't, so hubd refuses the merge until a decision exists.
- **Both have to be restarted together.** Nothing enforces it. An old app with a new hubd is refused, and a new app with an old hubd merges unenforced.
- **"Approved" means your decision,** never a GitHub review, which a reviewer App can give.

## Editing issues and comments

`edit_issue`, `tick_item` and `edit_comment` are on the Steward's `asks_first` list and on no other action's, and none is on any allowed
list: each call asks you on a card, and the tool server checks your yes (`ask.grant_use`) before the app runs it. A planner, a locked session that
can post, and a read-only one never see them. Full sessions list every tool, as they do any other. A test reads every action's grant for this.
They are marked as hard to undo. What they refuse is checked in the app, on the text GitHub has at that moment and not on the work store's:

- **A guard on what was read.** `get_issue` returns a `version`, a hash of the title and body. `edit_issue` and `tick_item` need it as `expected`,
  and if the issue has changed since, nothing is written and the refusal shows what differs, from the text the hub gave out. The person edits these
  bodies too. While the work store serves reads, `get_issue` (and the page's `?for=edit`) asks GitHub for the title and body as well (one more call; the
  dashboard's own view still asks it nothing), and gives those and their version, not the store's, which can be a sync behind: a version of text the person had already changed would be refused again at every retry. If
  GitHub doesn't answer then, there is no `version` and so nothing to edit by. A refusal for a change is found only after the person allowed the card. A restart of the app makes it forget what it gave out, and then the refusal says only to read again. The check and the write are two
  calls to GitHub, so a change in between isn't caught.
- **Whose issues.** Only issues whose author GitHub marks as the organization's own (`OWNER` or `MEMBER`). Another person's is refused, and so is
  a pull request. That doesn't catch outside text pasted into an organization member's issue, or an issue filed by an App, which is refused too,
  as GitHub doesn't mark it as a member's. Edits go out as the Steward's persona, like its comments.
- **Nothing is deleted or emptied.** A body, title or comment can't be blank, and a body that loses more than half its text needs a `reason`,
  which is part of the call and so on the card. hubd can't know the old length, so that one is found after the person allowed the card: the tool's
  text tells the Steward to always give a `reason` when it cuts. There is no delete. `tick_item` changes one box named by its exact text and refuses none or two,
  ignoring boxes in fenced code blocks, closed as CommonMark closes them. A fence indented four or more spaces, in a list item, isn't seen, so a box in one counts. GitHub keeps an edit's history, and each result carries the previous text so the edit can be put back.
- **Comments it posted itself.** `comment_issue` records the id, the session's name and its instance, in the work store. The instance is the session's
  own id from hubd (the Claude session id), which a name is not: the Steward is always `steward`, and a name is used again once its folder is gone. A
  resumed session keeps its id. `edit_comment` refuses any comment that isn't recorded, one posted by another session or by an earlier or later session of
  the same name, one for which hubd named no instance, and one that isn't on the issue named. The edit is a GraphQL document, and hubd checks that the comment's node is
  in the organization, as for review threads. A comment posted from the page can't be edited by a tool.
  **A call with no session isn't held to one.** That is the page, which is your login, and the shared agent token that hub shells hold, which has no tool
  list and so no card either: either can edit any comment the hub recorded, whichever session posted it. They have your rights, as for every other tool; a
  test pins it.
- **What the card shows is the call.** For `edit_issue` that is the whole new text, not its difference from the old. The Steward is told to say
  what it changes and why, but that is its word. `tick_item` is small enough to read. Before asking, hubd refuses a call the tool would refuse
  anyway: no `expected`, a blank body, a `checked` that isn't true or false, and a title that the command policy refuses (one shaped like `owner/repo`, or
  starting with a link outside the organization).
- **Text read in a private repository in a public edit.** Nothing technical stops it, as for `comment_issue`: the rule in `agents/private.md`
  is the one measure. An issue's text and the comments an edit is based on may be an outsider's, so they are data, and an edit isn't made because
  one says to; here too that is a rule in a prompt and the card, and the tools would carry out an edit a misled Steward asks for and you allow.

## The work item's GitHub actions

The black button on an issue, pull request or run (spec 006) acts on GitHub as you: the page's routes call `gh` through hubd with no
agent token, so it runs on the host's own `gh` login. The page passes its login token along. hubd checks it only for a merge (see "Merges");
for the other actions it is carried so a later check needs no change in the app. No tool calls these, so no session reaches them.

- **`pr edit` changes labels and nothing else.** ghpolicy takes it with `--add-label`/`--remove-label` and `-R`, one number, and at least
  one label. A title, body, body file, base, reviewer, assignee or milestone is refused, so the author's text and the review routing stay theirs.
- **`pr reopen` takes no comment,** so it reads no file and posts no text: one number and `-R`.
- **An issue's assignee is only you, added.** `issue edit --add-assignee` takes only `@me`, and `--remove-assignee` is refused. `issue create`
  takes `--assignee`/`-a` only as `@me`, in any spelling. This narrows what passed before; nothing in the app named anyone else.
- **Three reads for the view,** all `gh api`, read-only like the rest: `compare/<base>...<head>` for how far behind a pull request is, the
  repository's `labels`, and a run's `actions/runs/<id>/jobs` for its failed step. `compare` is the one path where three dots aren't refused as
  traversal: neither ref may hold two dots of its own or end in one.
- **Merge is still hubd's merge path.** The menu's Merge… is the same `pr merge --match-head-commit` with your login as before. Why it is off
  (checks running or failed, not approved, threads open) is shown, not enforced: hubd doesn't refuse a merge over a review state, and GitHub's branch
  protection is what holds there.

## The queue view

A tab under Work, over the work store and your decisions. It merges, reviews and starts nothing, and has no tool: a session has `decision_request` to ask.

- **Approving records a merge decision** through the same login-checked `decision.add` and `decision.approve` as the decision cards in Needs you, for the head the
  page showed. hubd asks GitHub for the head at that moment and refuses if it has moved, so a stale page can't approve what you didn't see. If
  GitHub can't say, nothing is recorded.
- **A pull request's text can't approve anything.** Anyone who can open a pull request writes `Set:` and `Tested:`, and a stranger's can join a set by
  name. So the page says they're what the text says, shows the author, and an approval binds one repository, number and head, never a set.
- **Text from GitHub stays text:** titles, reasons and a blocker's words are shown escaped, and none of it reaches an agent from here.
- **"Approved" is your decision.** GitHub's reviews sit in their own field and count for nothing here, as a reviewer App can give one.
- **A blocker is shown, not enforced.** hubd doesn't refuse a merge or an approval over an open `blocks-merge` issue, the row shows it,
  and only a link in the pull request's own text ties one to a row. A link with a closing word, as in `Fixes #2`, shows as "It says it fixes" and not as Blocked. That's the author's word too, so a stranger can lose the badge that way, and the issue stays listed at the top. Every open blocker is listed at the top whatever links to it. Labels are the
  only thing that makes one, and only those who can triage set labels.
- **What a current approval allows.** One from this page is for any session: a session with `merge_pr` can then merge that head, once. "Take it back" ends it. Approving a head again while one stands keeps the one you have, so there's only ever one to take back.

## Past sessions and cleanup

- The history tab shows transcripts to whoever is logged in, for sessions the hub ran only. A transcript can hold
  anything the session read, an outsider's text included, and it's shown as plain text.
- A resume reads the session's rights from its action's workflow as they are now (its current state's, for one that can move). A restored checkout comes from GitHub:
  uncommitted files from a removed worktree don't come back, so the hub doesn't remove one that has them. Ignored files
  count too: a full session holding more than 1 MiB of them stays when it ends, and discarding it has to name them on a second card.
- `agent.worktrees` (a login op) lists the folders a plain shell can start in for a repository: its workspace checkout and
  the session worktrees of it. Paths only; a login could already start a shell in any folder the user can.
- Cleanup looks at each row again when you confirm, whatever the page sent. It removes only what the hub started,
  with no uncommitted, ignored or unpushed files, no open pull request, no running session and no tmux shell whose pane is in it. It doesn't use
  `--force`, so git has the last word. If GitHub can't say, the row stays. Worktrees the hub didn't start are listed
  and never removed. This check can't see files added between it and git's own, which git's refusal covers for
  anything but ignored files.

## The design view

- A design session's boards run their own JavaScript. They run only in a headless browser on the host, in GlassineOS/ui's
  `tools/boards stream`, inside a container without network (`BOARDS_NETWORK=none tools/in-alpine`). The hub's page gets
  PNG pictures and words and draws the pictures on a canvas: no board markup, frame or script reaches it, so a board can't
  read the hub's cookies or call its API. The container can't reach the hub's port either.
- The renderer's tools come from a checkout of GlassineOS/ui at the release in `app/ui.ref`, in hubd's cache. The session's
  worktree is only data: the design folder, its Interleaf and its web form. A session can change its boards, not the program
  that renders them.
- The WebSocket has the terminal's rules: a login cookie and the hub's own origin. hubd checks the login again, and that the
  session is a design session whose worktree is there.
- What the renderer reports (the page's address, the board, voice, scheme and pen) is steered by a board's code. hubd passes
  only values of the design folder and its web form, never the address, and the page shows them as text. Viewer input reaches
  the renderer only as commands of known shape, each field checked.
- `design_open` and `design_view` act on the caller's own design view, found from its token, never from a name.
- At most three renderers run. hubd stops one when its session has ended and nobody has watched for ten minutes, before its
  worktree is removed, and removes leftover containers (any mounting its tools checkout) when it starts.

## The work store

The text of issues, pull requests and comments the login can read, private repositories
included, is kept on disk in the app's cache directory, readable by the user the hub runs as.
A compromised app could already read this through hubd. Deleted items leave it at the next
complete pass, kept answers included; other kept answers age out after 30 days.

`work_search` hands this text to agents, and outsiders can write it. It's more exposed than
`get_issue`, which returns the object you name: search returns whatever matches, so a comment
worded to match a likely query can reach a run about something else. So:

- Without a repository named, the tool server searches public repositories only: an agent that
  can post in public doesn't get private text by asking about a topic. It can still name a
  repository, so this limits finding text, not access to it, and the repository copies give any session a private
  repository's files when it names one. The Steward is the exception: its token
  reads every repository, and its rows say which are private. Each write it tries asks you first: see below.
- Drafting with Claude runs `claude -p` with read tools only, and the text only fills a box you post from.
  It reads outsiders' text, so a draft can be wrong or say what a comment asked it to: read it first. It has
  no `work_search`, because a draft may go into a public repository.
- A session held to a list sees only that list in `tools/list`, so it doesn't spend turns being refused. This is
  a convenience: what enforces the list is the token check on each call and `--allowedTools`.
- The hub types into a session only for a login: a preset button's text with a checked item name, Esc, or the words you
  type in its message field (`agent.say`, any Claude session, the Steward included). No tool call and no session's token reaches
  this. It pastes only once the session's turn has ended with its prompt empty, as Enter could answer a question or send a draft.
  Your words go to tmux on stdin, never as an argument, so the process list doesn't show them; they're 1 to 4,000 characters
  with no control characters, which could end the bracketed paste, and none that draw nothing (zero-width and bidi marks, tag
  characters, emoji selectors), which could carry words you can't see in text you pasted: a message holding one is refused,
  with where it is. A login could already type into any session through its terminal, so the field adds no reach: it adds a
  queue that waits for the turn to end. The words arrive as your turn, so a session treats them as yours: don't paste an
  outsider's text there unread.
- Where you are in the hub joins each of your turns in a session (`agent.context`, a login op): the screen, the open item,
  and the repositories chosen on the page. hubd checks each against the same patterns as elsewhere (a repository name is a
  name of at most 100 characters, as on GitHub, each once, at most 10), writes the line from the checked values only, and answers with the chips the Steward panel
  shows, made from the same values (010 FR-004): more than three repositories are told, and shown, only as a count. No tool
  call or session token sets it. A name in the address is only a name: the line says what you chose, not what it holds.
  The line is one per session and the last page to write it wins, so the panel shows the chips `agent.state` gives for the
  line on disk: hubd's own for the line it last wrote, and none when the file is anything else. That file is in the
  session's folder, so hubd reads it as it reads a session's own files (no link followed, nothing but a regular file, no
  more than the line's length) and only compares it: what it holds never reaches a page.
- A session's prompts and questions reach the hub as cards through a hook, which holds a connection to hubd. Only a login can
  answer: a session's token can add a card for itself, and close it, and nothing else. The hook prints what hubd worked out
  from the prompt, never what a page sent, and a card that's closed, or a second answer, changes nothing. A card shows the
  tool's real input and Claude's reason beneath it, and input too long to show can only be denied there, not allowed. Nothing
  answers in bulk. "Always allow" uses only Claude Code's own offers of a rule or of accepting edits, kept to that session,
  and says what it covers, wildcard included. When hubd stops waiting or restarts, nothing is approved, and the terminal's
  prompt stays. A locked session's terminal has no prompt, so its question is refused then, and it sees that. Locked sessions
  can ask, as a question only brings back text: it can't widen their tools or approve anything. Your answer is then something
  a misled session gets to act on, within its limits, so a card's question is its words, not the hub's.
- **New work: planner, session, drafts.** The planner and the session after it read text that can be an outsider's,
  so a briefing or a draft can carry an injected instruction or a false claim. The session's prompt marks the briefing
  as not yours. Neither has a shell or write tool and neither files anything. You read each
  draft before filing, and can change its title and body first (`work.edit`, a login op, a waiting draft of work that is not set aside, within a draft's limits; a new title follows the drafts that name it as their parent): none is chosen for you, a body prints every link and image address in full, with images flagged, and filing waits until each target is known to be public or private. GitHub may fetch an image's address when the issue is shown, even from a private repository. The session reads across the organization, so a draft for a public repository could quote
  something private: that's yours to catch when you read it. A suggestion from `plan_work` fills in the form,
  and its notes reach the planner and the session as yours once you press Start, so read them first. The same goes for "Start a fix session" on a findings result: the cause and fix are the session's words, and they fill the notes marked as that session's (SUGGESTED), in a box that shows them in full. A suggested full session (`suggest_session`) names its items, at most six and possibly across repositories (`covers`): hubd checks each as an item of the action's kind and holds the cross-repository ones to an action that opens its own pull request, and the card and Launch show every one before you press Start. The Steward gets drafts
  only when you hand them over, by tool and marked as data, and each issue it files still asks you.
- **The Steward's writes.** They're off its allowed list, so under dontAsk a write runs only when the hook allows it,
  and the hook allows only after you press Allow on the card. That isn't the only check: Allow leaves hubd a grant for that session, that
  tool and those exact arguments, good for one call and two minutes, and the tool server refuses the call without one. So a
  yes is needed whatever Claude Code does, and it can't be stretched to other arguments. Only a login answers a card. No
  answer in 10 minutes is a no. The card shows the call as it will run, which is all you approve; the Steward's reasons are
  in its terminal, and it can be wrong in a way you allow. A merge has its own rule: see "Merges". With a Steward App set
  up its writes go out as that App, and otherwise as you.
- The Steward starts sessions the same way. A locked action starts after you allow it, through the same planner and
  limits as a click, and that covers what it does within them. hubd refuses a full action on that path before it reaches
  you, because a misleading issue could shape its brief: you start those yourself. At most 4 run at once, and only the
  Steward's action can ask for a start. Its
  `session_summary` reads only sessions it started; what it reads there is data.
- The Steward can message sessions. Without a card that reaches only a session it started that has no write tool and no
  shell, from a list named in `hubd/agents.py`, so a misled Steward can't direct a review's rights at another pull request.
  Any other message shows on a card first, and hubd refuses invisible characters so the card shows all of it. A message
  arrives as a turn, marked as the Steward's between two random lines. Allowing one still lets a misled Steward ask for
  something, and then the target's own judgement is what's left.
- The planner of a full action has no `work_search`, as its words become a full session's brief.
  Locked actions and their planners do, and treat what it returns as data.
- Notes and pins come only from your request, and the planner's answer can't change them. A pin you add
  can still bring an outsider's text into a full session's planner, because you chose to point it there.
  The session's prompt gives your notes first and says the briefing below them isn't yours, whatever it
  claims, since a planner that read outsiders' text wrote it.

Search queries reach GitHub only as a scope and a time: hubd builds the query itself, keeping
it inside the organization. `gh api` takes one header, `If-None-Match` with an ETag.
