# Research: Hub app (spec 001)

Decisions for the open technical questions in `plan.md`. Each one says what was chosen, why,
and what else was looked at. Paths and line numbers are on branch `001-hub-app` at `c81fe71`.
Nothing here was tried for real: these are readings of the code, and the PR that builds each
decision says what it tried (browser, real `claude`, real GitHub).

Decisions the maintainer already made are not reopened here: sessions are full chats (FR-027);
agents merge only under an approved merge decision for the PR head (FR-107a), the Queue view stays
in Work; Decisions, Go and Active grants become Interaction cards and a filter in the Needs-you
modal; no Device page (device lock on Overview); a small budget meter in the header; navigation
Overview, Roadmap, Work, Knowledge, Notes, Sessions.

---

## R1. Where the persona family and display data live

- **Decision:** a new `agents/personas/families.toml`, read by `Library` like
  `steward-buttons.toml` (`hubd/agents.py:218`). One table per persona id:
  `name` (display name, e.g. "Code reviewer"), `initials` (1–2 letters), `family` (one of
  `build`, `review`, `investigate`, `write`, `organise`). `Library` refuses to load when a persona
  `.md` has no entry or a family is outside the five, so a new persona can't ship without one. The
  Steward is `organise` in the file but the app draws it with its own pen-blue "S" (FR-013); a plain
  shell is not a persona and has its own badge (FR-014).
- **Rationale:** persona `.md` files are pasted into the session's prompt
  (`_write_persona`, `hubd/agents.py:958`), so front matter would reach the model. A separate file
  keeps prompt text and UI metadata apart and is additive to the owned action/persona contract: a
  session already running never reads it.
- **Alternatives:** front matter in each `.md` (leaks into the prompt, needs stripping);
  hard-coding the table in `app.js` (the library is the owned contract, and `hubd` needs the family
  for `interaction.list` and history filters).

## R2. Action short names, result types, and the FR-059 table

- **Decision:** every action TOML gains `verb` (the spec's short name: review, address, fix,
  implement, triage, investigate, issue, sec, arch, road, docs, deps, compact, sweep, research) and
  `result` (`comment`, `pr`, `labels`, `findings`, `drafts`, `report`, `notes`). The table maps onto
  existing files like this:

  | verb | file | persona today | change |
  |---|---|---|---|
  | review | `pr-review.toml` | reviewer | `result = "comment"` (see R9) |
  | address | `pr-address-review.toml` | engineer | `result = "pr"` |
  | fix (PR) | `pr-fix-checks.toml` | engineer | persona `ci-fixer` added as first choice |
  | fix (run) | **new** `run-fix.toml` | ci-fixer | full, `checkout = "new-branch"` from the run's head branch |
  | implement | `issue-implement.toml` | engineer | `result = "pr"` |
  | triage | `issue-triage.toml` | triager | `result = "labels"` (see R9) |
  | investigate | `run-diagnose.toml` | ci-diagnostician | `result = "findings"` |
  | issue, sec, arch, road, docs, deps | `new-*.toml` | as today | `result = "drafts"` (exists: `submit_drafts`) |
  | compact | **new** `notes-compact.toml` | **new** archivist | `object = "notes"`, `result = "notes"` |
  | sweep | **new** `notes-sweep.toml` | docs-writer | `object = "notes"`, `result = "drafts"` |
  | research | **new** `knowledge-research.toml` | **new** researcher | `object = "knowledge"`, `result = "report"` |

  The actions the spec's table doesn't list (`pr-explain`, `pr-merge-prep`, `pr-session`,
  `pr-security-audit`, `issue-docs`, `issue-session`, `run-explain`, `run-flaky`, `run-slow`) stay
  in the library, with `result = "none"` where they only talk in the terminal, and appear under a
  "More…" menu in Launch, never as a row's blue button. **This departs from FR-059's "the action
  library has these actions"**: the spec reads as a closed list; removing working actions isn't
  asked for anywhere else. Said here before it's built.
- **"Kernel engineer (the repository's engineer)":** there is one `engineer` persona today. The
  display name can come from `config/repos.toml` (optional `engineer = "Kernel engineer"` per
  repository); the persona file stays the same. A per-repository persona prompt is out of scope.
- **Ceiling vs item kind (FR-058):** the action's `object` already decides this (`validate`,
  `hubd/agents.py:248-268`). Launch adds a check across `covers[]` (R4): every covered item must be
  of the action's object kind, and the refusal says which item and why.
- **Rationale:** smallest change to an owned contract; old sessions keep their action text.
- **Alternatives:** renaming files to the short names (breaks history rows and resumes that name the
  old id: `hubd/history.py`); a separate verb→file map in the app (two sources of truth).

## R3. One Interaction model: a projection, not a new store

- **Decision:** a hubd read op `interaction.list` (behind the login check at
  `hubd/server.py:200`) that projects four existing sources and one new one into one shape
  (`data-model.md` § Interaction):
  - `Asks` (`hubd/asks.py`, memory) → `permission` / `question`;
  - `Decisions` (`hubd/decisions.py`, disk) → `decision` (Go and merge);
  - `NewWork` offers (`hubd/newwork.py`, disk) → `suggestion`; finished drafts → `result` of type
    `drafts`;
  - **new** `Results` store (R8) → `result` of the other types.

  Ids keep their source as a prefix (`a:`, `d-…` as today, `w:`, `r:`) so an answer goes to the
  existing op for that source: `ask.answer`, `decision.approve|deny|end`, `work.*`, `result.*`. A
  new `interaction.answer` op only dispatches; it adds no rule of its own.
- **Status mapping (FR-032):** asks keep their states, with `stopped` shown as `ended`; decisions
  `requested` → `pending`, `current`/`using` → `allowed` (shown under Active grants), `ended` after
  approve → `ended`, ended without approval → `denied`, expired request → `timeout`; offers
  `offered`/`planned` → `pending`, `planning`/`starting`/`running`/`started` → `started`,
  `dismissed` → `dismissed`; results `pending` → `pending`, applied → `answered`, set aside →
  `dismissed`. "always" stays the ask's own Always (FR-033). An eye-test Go can't be granted as
  "always" (`decisions.py` `EYE_TEST`, already refused).
- **Who and where (FR-041):** every settle records `by` (the login user, or `terminal`) and `where`
  (the view the page sent: one of the closed `SCREENS` list, plus `Needs you`, `SessionView`). `where`
  is a page claim, checked against the list and shown as such, never trusted for anything.
- **Live updates (FR-043, SC-002):** the app polls `interaction.list` every 3 s, as `Hub` polls
  `asks` today (`app/hub/static/app.js:2763`). Answers made in the terminal show within one poll.
  No push channel is added.
- **Rationale:** the stores have different lifetimes on purpose: an ask lives only while its hook
  holds a connection (`asks.py:1-9`); decisions and drafts survive restarts. Merging them would
  change what a running session's hook sees. The seam already exists: `Hub` sums three sources into
  `asks.waiting` (`app.js:2777`).
- **Alternatives:** one new on-disk interaction table (rewrites asks' hook protocol and the
  decision rules; risks sessions already running); keeping three lists in the app (no single status
  vocabulary, no "handled in this view").

## R4. Session `covers[]`, `prs[]`, `view`, `origin`

- **Decision:**
  - `covers` is a new config field: a list of up to 6 `{repo, number}` items (the first is the
    primary). `validate` (`hubd/agents.py:248`) checks each like the current `repo`/`number` and
    keeps `repo`/`number` = the first item, so `_prompt`, `_name`, `_checkout` and every reader of
    `config["repo"]` keep working. `also_numbers` stays readable for old `session.json` files and is
    folded into `covers` by `describe()`; new starts write only `covers`. Items in other repositories
    get a read-only snapshot through the existing `request_repository` path when the action has file
    tools, and are listed in the prompt; the worktree is the first item's (FR-056). `MAX_ALSO` (5)
    stays the limit of extra items.
  - `prs` is **derived, not stored**: for a session with a branch, `_pr_of(repo, branch)`
    (`hubd/agents.py:1903`) per covered repository, cached in memory for 60 s. For `address`/`fix`
    on a PR, the PR is the covered item itself.
  - `view` (`embedded` | `background`) and `where` (the view it's embedded in) are written to the
    session folder as `view.json` by a new `agent.view` op. Today this is browser state
    (`phases` in `WorkLists`, `app.js:1031`), so "N sent to background" can't survive a reload.
  - `origin` is the Launch record id (R6) plus a copy of its `from` (view, item, by): a session
    started before this change has `origin = null` and shows "started before origins were kept".
  - `permission_mode` is read from the action (`hubd/agents.py:947`) and returned by `describe()`.
- **Rationale:** a closed `_FIELDS` set (`agents.py:98`) makes the addition explicit; deriving PRs
  avoids a second source of truth that drifts after a force-push or a closed PR.
- **Alternatives:** storing `prs` when a session opens one (needs a hook on `gh pr create` inside a
  full session's own shell, which the hub doesn't see); `covers` as "also_repos + numbers" (two
  parallel lists that can disagree).

## R5. Typed messages (FR-027)

- **Decision:** a new `agent.say` op (`name`, `text`, `where`), behind the login check at
  `hubd/server.py:200`, calling `Agents._send(name, text)` (`hubd/agents.py:1249`) with `by=None`.
  The web API adds `POST /api/agents/say`. `press` stays for preset buttons. `_send` already refuses
  control characters and text over 4000 characters and queues while a turn runs.
- **Fix needed for "never as a command-line argument":** `Shells.paste` passes the text as an
  argument to `tmux set-buffer -- text` (`hubd/shells.py:118`), so it is visible in the process
  list for the life of that tmux call. The PR switches it to `tmux load-buffer -b <buf> -` with the
  text on stdin. That also changes the path the Steward's buttons and session-to-session messages
  use, which is fine: same buffer, same paste.
- **Transcript:** the words arrive as a normal user turn, so Claude Code's transcript holds them as
  the person's; the Steward's `UserPromptSubmit` hook still adds the screen context
  (`agents.py:858`). History's transcript view labels user turns "You".
- **What changes in the docs:** `docs/orchestrator.md:146-156` ("Buttons", "Any session") and a
  `SECURITY.md` paragraph: a login could already type into any session through the terminal
  WebSocket (`app/hub/web.py:363-410`, `app.js:1328`), so the message field adds no reach; it adds a
  queue that waits for the turn to end. The test `test_the_page_says_only_a_button_and_an_item_to_a_session`
  (`tests/test_app.py:768`) asserts `/api/agents/send` is a 400 and must change in the same PR.
- **Alternatives:** sending keystrokes through the terminal socket (no queueing, could answer a
  question mid-turn); a `text` field on `press` (mixes the preset rule with free text).

## R6. Launch records: generalize NewWork

- **Decision:** every Launch, for every action kind, is a record in the existing `NewWork` store
  (`hubd/newwork.py`, folder `state/newwork`), extended with fields (`data-model.md` § Launch). The
  record's `state` is the stage: `brief` lives only in the page; a record is made when planning
  starts (FR-057 "every Launch is recorded"); `planning` → `planned` → `starting` → `running`
  (or `started` for item sessions, as today, `hubd/server.py:787-790`) → `done` with a result →
  `filed`/`dismissed`; `failed` on any error. Records carry `v: 2`; records without `v` read as
  today.
- **What moves:** item actions plan in the browser today (`plans` Map, `app.js:540`; `agents.plan`
  via `agent.plan`). They now go through `work.start` with `covers`, and `work.start`'s refusal of a
  `number` (`hubd/server.py:829-830`) is replaced by the FR-058 kind check. `agent.plan`/`agent.start`
  stay for one release so a page loaded before the deploy still works, then go.
- **Plan steps (FR-053):** the planner schema (`Library.schema`, `hubd/agents.py:233`) gains
  `steps: [{what, touches: [string]}]` (at most 12 steps, 8 touches each, 300 characters). Steps are
  planner text and go into the prompt below the existing "prepared by a planner" banner
  (`agents.py:829-831`).
- **Background (FR-055):** the record has `background: bool`, set by `work.background`; the toast
  and Needs you read it. The session's own `view.json` (R4) follows.
- **Restart:** `_after_restart` (`newwork.py:82`) already fails `planning`/`starting`; the same
  applies to item launches.
- **Rationale:** the store already has the stages, on disk, survives restarts, and is what
  suggestions use; two stores would mean two "started" rules.
- **Alternatives:** a new `launches` module (duplicates `_after_restart`, pruning, Steward
  notifications); keeping item plans in the browser (no FR-057 record, lost on reload).

## R7. Usage budget meter (FR-086a)

- **Decision:** hubd adds a `statusLine` command to each session's settings (where `_hooks` writes
  the hooks, `hubd/agents.py:841`) that copies Claude Code's status-line JSON to
  `<session>/status.json`. A new `usage.status` op reads the newest one: if it carries rate-limit
  fields (a used percentage and a reset time), the meter shows those; otherwise it sums today's
  `cost.total_cost_usd` across sessions and planner runs and compares it with an optional
  `HUBD_DAILY_USAGE_USD` allowance; with neither, the meter says "usage not known". It is low at
  80 % and says so in words (FR-086a). The GitHub API budget (`Budget`, `app.js:2415`) leaves the
  header and moves to Overview's stats line.
- **Consumed contract:** the status-line input is Claude Code's, not pinned (constitution,
  Contracts). Which fields the installed version sends must be tried with a real `claude` in that
  PR; until then the code path that reads them is marked untested.
- **Alternatives:** parsing transcripts for token counts (no prices, no allowance); a manual figure
  only (always stale); leaving the GitHub budget in place (it is not what FR-086a asks for).

## R8. Results: one store, handed in by a tool, applied by a login

- **Decision:** a new `hubd/results.py` store (`state/results/<id>.json`, 0700, pruned like
  `newwork`), a new tool `submit_result(type, payload)` that validates the payload against a closed
  shape per type (`data-model.md` § Result) and refuses any type other than the session's action's
  `result`. `drafts` keeps `submit_drafts` (unchanged for running sessions). Applying a result is a
  login op `result.apply` that runs the write **under the session's own scope**: it checks that the
  producing action lists the tool the write needs (`review_pr`, `label_issue`, `edit_issue`, …) and
  goes out through the same path as that tool, so a result can never do more than its session could
  (FR-061, FR-177). The person's press is the go-ahead; the write goes out as the persona's App when
  there is one (`SECURITY.md` "Personas on GitHub"), else as the person.
- **Per type:** `comment` → one review with inline notes (needs a GraphQL document, R10);
  `labels` → `label_issue` per issue plus "Part of" via `edit_issue` with its `expected` guard;
  `findings` → nothing to apply, "Start a fix session" opens Launch; `report` → `result.keep` marks
  it saved for Knowledge (stays in hubd state, never committed anywhere); `notes` → `notes.apply`
  (R12); `pr` → nothing to apply, the card links the PR from `prs[]`.
- **Rationale:** the drafts flow (`submit_drafts` → nothing filed until you choose,
  `docs/orchestrator.md:88-108`) is the proven pattern; reusing the session's scope keeps the ceiling
  enforced in one place.
- **Alternatives:** the session posts directly as today and the card only shows what it did (no
  "Post" step, contradicts FR-064/FR-065); applying as the person with no scope check (a result
  could exceed its action).

## R9. Departures this forces on running actions (say before building)

- **`pr-review` posts its own review today** (`agents/actions/pr-review.toml`, tool `review_pr`).
  With `result = "comment"` it hands in the summary and inline notes and the person presses Post
  (FR-064). New sessions lose `review_pr` from their tool list and gain `submit_result`; a session
  already running keeps the tools it started with (its scope is frozen in its token,
  `agents.py:496`), so it may still post directly. **Needs the maintainer's yes before the Launch
  backend PR**: it changes what an existing action does.
- **`issue-triage` labels directly today.** Same change, `result = "labels"`, same rule for running
  sessions.

## R10. GitHub calls: reads under the allowed `gh api` path, three new write shapes

- **Reads, no policy change:** `gh api repos/GlassineOS/<repo>/(.*)` is already allowed read-only
  (`hubd/ghpolicy.py:50-54`). Used for the behind count (`compare/<base>...<head>`), workflow inputs
  (`contents/.github/workflows/<file>?ref=<ref>`, parsed in the app container with a small YAML
  subset reader for `on.workflow_dispatch.inputs`; no YAML library), repository labels (`labels`),
  and the failed step of a run (`actions/runs/<id>/jobs`). Each new path shape gets a line in
  `tests/test_ghpolicy.py` `ALLOWED` and a traversal case in `REFUSED`. `reviewDecision` is already
  in `_PR_FIELDS` (`app/hub/github.py:25`).
- **New allowlist entries (ghpolicy change, tests in the same PR):**
  1. PR labels: `pr edit <n> --add-label/--remove-label` — `pr edit` is not in
     `_COMMANDS["pr"]` (`ghpolicy.py:30`). Allowed only with `--add-label`/`--remove-label`, refused
     with `--title`, `--body`, `--base`, `--add-reviewer` etc. (If `gh issue edit` on a PR number
     is found to work with the installed `gh`, that path needs no entry; to be tried for real.)
  2. "Assign to me": `issue edit <n> --add-assignee @me` already passes `_check_flags`; it gets an
     allowed case and a refused case for any other login.
  3. Reopen a PR (FR-073 "Close/Reopen"): `pr reopen` is not in `_COMMANDS["pr"]` either; added
     with an allowed case and a refused `--comment-file` case.
  4. Inline review comments for a comment result: a new GraphQL document
     `hubd/graphql/pr_review_add.graphql` (`addPullRequestReview` with `threads`), whose pull request
     id is checked to belong to the organization like the existing content-id checks.
- **Rationale:** the policy is an allowlist of what the app runs; reads through the existing path
  need no widening, writes are named one by one.
- **Alternatives:** `gh api -X POST` for reviews (would make `gh api` writable, against
  `ghpolicy.py:13-16`); reading workflow files from the hub's seed copies (`hubd/seeds.py`) —
  possible, but can lag the branch the person picks.

## R11. Device lock on Overview (FR-089)

- **Decision:** Overview's device card shows the lock line from `device.status`
  (`hubd/devices.py:185` `_lock_words`, read with a login as `/api/device` does today) and
  `decision.holding` (`hubd/server.py:171`) for "you hold it". It links the Go in force when the
  report names one. No structured `free`/`held` field is added: `devices.py:8-10` keeps reports in
  words on purpose, since anything on the socket can send one. `DeviceView` (`app.js:2426`) and the
  `device` nav entry go in the Header PR; the card lands in the same PR so the information never
  disappears.
- **Alternatives:** a structured lock field (against the module's forged-report rule).

## R12. Notes upkeep: totals and applying operations

- **Facts:** the `notes` CLI (workspace repository, consumed) has `add`, `set` (`--replaces`,
  `--retract`, `--close`, `--by`, `--why`, `--open`), `lint` and `find --json`. hubd runs only `find`
  (`hubd/notes.py:107-131`). There is no `merge`, `distil`, `flag` or totals command.
- **Decision:**
  - **Operations** map onto existing verbs, each an exact command shown on the card: `supersede` →
    `notes set TOPIC WORDS --replaces ID`; `retract` → `notes set TOPIC --retract ID --why …`;
    `answer` → `notes set TOPIC WORDS --close ID --by ID`; `status` → `notes set TOPIC --open|…`;
    `merge`/`distil` → one `notes add` (the merged text) followed by `notes set --replaces` for each
    merged id; `flag` → `notes set TOPIC --open --why …`. None deletes (FR-068). hubd gains
    `notes.apply(op)` behind the login: a closed op list, every argument checked
    (topic `[a-z0-9-]+`, ids from the tool's own format, words after `--`), run as `find` is run
    (`-I`, fixed env, no shell). A `SECURITY.md` "Notes" paragraph change in the same PR: this is
    hubd's first notes write.
  - **Totals per label and topic (FR-136):** need a `notes stats --json` command in the workspace
    repository. That is a change in another repository (constitution IV); until it lands, the flyout
    shows totals counted from the last search's rows and says so. Filed as a dependency in the Notes
    PR.
- **Alternatives:** hubd reading `notes/` files itself (they never passed the safety scan,
  `hubd/notes.py:3-8`, and the format is the tool's business).

## R13. Knowledge domains and research reports

- **Decision:** Knowledge searches Docs (`app/hub/docsearch.py`) and Work items
  (`github.work_search`, `app/hub/github.py:276`) in parallel and shows Code as "planned" (FR-124;
  `hubd/codesearch.py` exists for agents but is out of scope for the page, spec "Out of scope").
  "Meaning / exact" maps to the semantic search vs the work store's word filter. Pins are page state
  until a research Launch takes them as `pins` (`PIN_KINDS`, `agents.py:140`; `docs` and `ref`
  kinds). Reports are `report` results (R8) with `kept: true`; Knowledge lists kept reports, newest
  first, 20 then more. Index states come from `docs.status` and `work.status`; "Run docs CI now" is
  `docs/reindex`, "Ingest now" is `work/sync`, both existing.
- **Rationale:** both indexes and both triggers exist; Knowledge is a view over them, not a new index.
- **Alternatives:** searching code from the page too (out of scope in the spec, and it widens what the page
  reveals about private repositories); one combined index (a change in `GlassineOS/search`, another repository).

## R14. Roadmap columns and progress (FR-095, FR-096)

- **Decision:** the four columns map from the project's Status options by name (Planned ← "Todo",
  "Planned", "Backlog"; In progress ← "In progress"; In review ← "In review"; Done ← "Done"),
  configured in `config/` with that default; an unknown option goes to Planned with a note. Progress
  per repository counts the GitHub sub-issues already rolled up (`_rollup_subs`,
  `app/hub/github.py:1104`) **plus** open and closed issues whose body has a "Part of
  hub#N" line, found in the work store (`WorkStore.with_bodies`, `app/hub/workstore.py:331`),
  counted once per issue. Filed drafts write "Part of" without a sub-issue link
  (`docs/orchestrator.md:94-95`), so without this they'd never count.
- **Rationale:** the hub's own filing writes Part-of lines, so counting only sub-issues undercounts the
  hub's own work.
- **Alternatives:** sub-issues only (misses filed drafts); making the filer create sub-issue links (a
  GraphQL mutation and a policy entry, and old issues still wouldn't count).

## R15. Remembered per-viewer state

- **Decision:** `localStorage` with try/catch, as the Steward rail does (`app.js:2659`): Work's
  repository selection (FR-099), Steward width (FR-154), RepoPicker recents and pins (FR-006).
  Nothing that must be shared or reliable. Work's filter stays in `sessionStorage` as today.
- **Rationale:** one maintainer; these are conveniences, and the pattern is already used.
- **Alternatives:** settings kept in hubd (a new login op and store for state that can be lost harmlessly).

## R16. Front-end structure

- **Decision:** `app.js` stays one file (no build step; vendor libraries pinned in
  `app/fetch-vendor.sh`). Shared components go in one section near the top, after the helpers
  (`app.js:120-220`), with a comment heading each. CSS adds tokens for the family tints and the
  night-paper terminal to `:root` (`style.css:14-21`), with dark-mode values.
- **Static checks:** `tests/test_app.py` already reads `app.js` as text to pin NAV
  (`tests/test_app.py:914-939`). The yellow rule (FR-164) becomes a test that `--mark` and `#ffd86b`
  appear only in rules whose selectors name waiting states (`.waiting`, `.mark`, `[data-waits]`).
- **Alternatives:** splitting into ES modules (a later, separate change; every PR here would
  conflict with it).

## R17. Phone layout

- **Decision:** CSS at `@media (max-width: 760px)` (the spec's breakpoint; `style.css` uses 720 px
  and 1000 px today, lines 279 and 284 — 720 becomes 760). The header renders "New" and "Menu"; Menu
  is a sheet with the nav, Needs you and the user line. Modals become full sheets by one class. The
  Steward becomes a floating button. Diffs, logs and terminals scroll inside their own box
  (`overflow-x: auto`); the page never does. Tested by hand at 390 px.
- **Rationale:** the spec names 760 px; one phone breakpoint keeps the rules in one block.
- **Alternatives:** keeping 720 px (contradicts FR-160); a JavaScript layout switch (CSS does it without
  a redraw, which matters on e-ink).
