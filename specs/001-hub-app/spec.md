# Feature Specification: Hub app

**Feature Branch**: `001-hub-app`
**Created**: 2026-11-06
**Status**: Draft
**Input**: "The hub web app: what each view is for, the building blocks the views share,
and the rules that hold across them."

## Context

The hub is the place one maintainer uses to run GlassineOS. That means dozens of
repositories, their issues, pull requests and CI runs, a shared knowledge base and notes,
and many Claude Code sessions working at the same time. Sessions run in tmux on the host.
Each has a persona (Engineer, Code reviewer, CI investigator, ...) and works in its own git
worktree.

The maintainer is one person, and attention is the scarce thing. The hub's job is to:

- show what needs that person right now (a blocking permission, a question, a result to
  act on) wherever they are in the app, and let them answer it in place;
- turn any work item into work for an agent in a few steps (Launch), with a visible plan
  and a known kind of result;
- keep the GitHub actions the maintainer does as themselves (merge, close, label, re-run)
  one click from the item, never mixed up with starting an agent;
- make knowledge, notes and past sessions findable, and keep the host tidy (worktrees,
  old sessions);
- run beside a Steward, a long-lived planning session that sees what the maintainer sees.

The hub runs on the maintainer's machine. The web app talks to `hubd`, a host daemon that
holds the credentials and runs the sessions. Sessions reach the hub through a tool server.
The hub is used on a desktop browser and on a phone.

Four building blocks recur everywhere:

- **Item**: an issue, PR, CI run or roadmap item, written `repo#N` or `workflow #N`.
- **Launch**: the path from "I want an agent on this" to a running session.
- **Session**: a Claude Code (or plain shell) process with a persona, covered items and a
  terminal.
- **Interaction**: anything a session or the hub needs from the maintainer.

Related: `docs/orchestrator.md` (session and merge model), `SECURITY.md` (boundary),
`.specify/memory/constitution.md`.

## Views

Each view's purpose in one sentence:

- **Header**: always shows where you are, how many things wait for you, and the way to
  start new work.
- **Overview**: shows the state of every repository at a glance, sorted by what needs
  attention, plus who holds the device.
- **Roadmap**: shows planned work across repositories as columns by stage, with progress
  taken from linked issues.
- **Work**: lists PRs, issues and CI runs across the chosen repositories, grouped by what
  they need, with one suggested agent action per row.
- **Work item**: everything about one item (body, checks, conversation, diff or log, and
  the sessions on it), with agent actions and GitHub actions side by side.
- **Knowledge**: searches docs, work items and code, and starts research when search is
  not enough.
- **Notes**: finds and keeps tidy the shared notes, with each note's trust label in view.
- **Sessions › Running**: lists every live session and plain shell and opens any of them
  in full.
- **Sessions › History & cleanup**: resumes or reads past sessions and removes the
  worktrees they left behind.
- **Needs you**: the single list of everything waiting for the maintainer (prompts,
  questions, decisions, results, suggestions), answerable in place.
- **Launch**: turns a brief into a planned, running agent session with a known result.
- **Steward**: a side panel with the planning session that sees the current view and
  proposes work.
- **Phone**: the same app at phone width, with the header and Steward folded for one hand.

## User scenarios

### Scenario 1 – Answer a blocking prompt from any screen (Priority: P1)

**Given** a session is waiting for permission to run `git push`, and the maintainer is on
Knowledge
**When** they press the yellow "Needs you 1" button in the header and choose "Allow" on
the permission card
**Then** the session continues, the card shows "allowed" in the "handled in this view"
line, the count drops to 0, and the yellow is gone from the header.

### Scenario 2 – Launch an implementer on two issues from a suggestion (Priority: P1)

**Given** the Steward has posted a suggestion "implement kernel#204 and kernel#219
together"
**When** the maintainer opens it from Needs you, checks the brief, picks the planner model,
reads the plan and presses "Start"
**Then** an Engineer session runs that covers both issues; both items show its
SessionChip; the session is embedded in the view it was started from; and the suggestion
card shows "started".

### Scenario 3 – Review a PR, then merge it yourself (Priority: P1)

**Given** a PR whose checks passed
**When** the maintainer launches "review" from the Work item, reads the resulting review
summary and inline notes and posts them, then uses the black "Merge…" split button and
confirms "squash"
**Then** the review is posted as a comment by the reviewer session's result, the PR is
merged on GitHub as the maintainer, and no agent took the merge step.

### Scenario 4 – Fix a failing CI run (Priority: P1)

**Given** a run in the Failed group on Work
**When** the maintainer presses the row's blue "fix" button (or "investigate" on the run
page)
**Then** the investigate result shows the cause and the smallest fix, with a button to
start a fix session; the fix session's draft PR says "Closes …" for each covered issue.

### Scenario 5 – Research a question (Priority: P2)

**Given** a Knowledge search for "why LUT version 3" returns no good hits
**When** the maintainer pins two passages, presses "Research this…" and plans a research
session
**Then** the session ends with a report (answer, what could not be settled, sources,
follow-ups); the report lands in Needs you › Results ready and can be saved; Knowledge
lists it under reports, where it can be opened or followed up.

### Scenario 6 – Grant a Go for a device run (Priority: P2)

**Given** a session asks for a Go (reboot and load test) and the device is free
**When** the maintainer opens the Go card in Needs you, sets "ends after 3 runs" and
approves it
**Then** the grant appears under the Needs you "Active grants" filter, the session's runs
count down, and Overview shows the device lock holder while the session holds the lock.

### Scenario 7 – Clean up old worktrees (Priority: P2)

**Given** twenty worktrees under `~/hub-worktrees`, some for merged PRs
**When** the maintainer opens History & cleanup, presses "Select safe" and removes them
**Then** only the worktrees with no uncommitted work and a merged or closed PR are
removed; each row showed the exact command first; the rest stay.

### Scenario 8 – Use it on a phone (Priority: P2)

**Given** the hub is open on a 390 px wide phone
**When** the maintainer opens the menu, goes to a Work item and answers a question from
the Steward's floating button
**Then** nothing scrolls sideways, the header shows only "New" and "Menu", the Steward
opens as a full sheet, and every control can be tapped.

### Scenario 9 – Keep notes useful (Priority: P3)

**Given** the Notes topic "epd" has many HISTORY and duplicate notes
**When** the maintainer runs "Compact…" on that topic
**Then** an Archivist session returns note operations (merge, distil, supersede, ...),
each with its exact `notes` command; applying them changes labels and merges notes, and
deletes nothing.

### Scenario 10 – Resume a past session (Priority: P3)

**Given** a finished session whose worktree was removed
**When** the maintainer finds it by searching transcripts in History and presses
"Restore & resume"
**Then** the worktree is recreated on the session's branch and the session resumes with
its earlier conversation.

### Scenario 11 – File an issue or start a workflow by hand (Priority: P3)

**Given** the maintainer is on Work
**When** they use "New issue…" (or "Run workflow…") from the black split button and fill
in the form
**Then** the issue is created (or the workflow is dispatched) as the maintainer. The issue
form also offers "Let Claude write it instead", which opens Launch with the issue-writer
action.

## Requirements

Requirements are one testable statement each. Shared building blocks come first, then
each view, then the rules that apply across views.

### Building block: Item reference and ItemPill

- **FR-001**: Every item is referred to by a stable reference: `repo#N` for issues and
  PRs, `workflow #N` for runs, and the roadmap item reference for roadmap items.
- **FR-002**: An ItemPill shows the item kind icon, the reference and (when there is room)
  the title, and opens the Work item view when activated.
- **FR-003**: An ItemPill shows the item's state (open, draft, merged, closed, failing,
  running) by its outline and icon, never by a background colour.
- **FR-004**: An ItemPill can be removable (shows a remove control) where it stands for a
  selection, such as a Launch brief's covered items.

### Building block: ItemPicker and RepoPicker

- **FR-005**: The RepoPicker lets the user pick one or many repositories by typing a
  filter, and offers "All repositories" where a view allows it.
- **FR-006**: The RepoPicker shows recent and pinned repositories first, then the rest
  grouped by layer.
- **FR-007**: No view shows all repositories as pills or chips at once (scale rule). A
  selection of more than 3 repositories is shown as a count ("5 repos") that opens the
  picker.
- **FR-008**: The ItemPicker finds items by reference or by words in the title, across
  the selected repositories, and returns one or many items.
- **FR-009**: The ItemPicker shows each candidate as an ItemPill with its state and
  repository.
- **FR-010**: Both pickers can be used fully by keyboard (type, arrows, Enter, Esc).

### Building block: PersonaBadge

- **FR-011**: Every persona belongs to exactly one family: build, review, investigate,
  write or organise.
- **FR-012**: A PersonaBadge shows the persona's initials on its family tint (build
  #d6e2ff, review #eadcff, investigate #ffd9b8, write #d4efdc, organise #e2e2e2), with
  the persona name as its accessible label.
- **FR-013**: The Steward's badge is a pen-blue "S" and is never used for another
  persona.
- **FR-014**: A plain shell has its own badge that is not a persona family.
- **FR-015**: A family legend is available wherever badges appear in a list (Sessions ›
  Running).

### Building block: SessionChip

- **FR-016**: A SessionChip shows a session's PersonaBadge, a short name and its state
  (RUNNING, WAITING, DONE, ATTACHED).
- **FR-017**: A SessionChip for a session that waits for the maintainer is marked yellow
  and says how many things wait.
- **FR-018**: Activating a SessionChip opens that session: in place where the view embeds
  sessions, otherwise in Sessions › Running.
- **FR-019**: Wherever an item is shown with sessions, every session that covers the item
  or has a PR for it is listed as a SessionChip.

### Building block: SessionView

- **FR-020**: A SessionView has three modes: full (Sessions), embedded (inside a Work
  item) and compact (Steward panel).
- **FR-021**: The SessionView header shows the PersonaBadge, the persona name, the model,
  the state, the branch and the origin (where and why it was started), tinted with the
  persona's family tint.
- **FR-022**: The SessionView shows the covered items and PRs as ItemPills.
- **FR-023**: When a session covers more than one item, an "Also on these items" switcher
  shows the other items and opens them.
- **FR-024**: The SessionView shows the live terminal of the session on night paper
  (#121212), scrolled to the end, with the user's scroll position kept while new output
  arrives.
- **FR-025**: Pending interactions for that session are shown inline above the terminal
  and can be answered there, with the same effect as answering them in Needs you.
- **FR-026**: A SEND row offers the session's preset reply buttons and Esc.
- **FR-027**: Every Claude session, the Steward included, is a full chat: the SessionView
  has a message field, and what the maintainer types is sent to the session as their
  message. Only the logged-in maintainer can send, the text reaches the session through
  hubd as typed input (never as a command-line argument), and the transcript shows it as
  the maintainer's.
- **FR-028**: A "Session spec" disclosure shows the persona, action, model, permission
  mode, ceiling, covered items, worktree path, branch and start command.
- **FR-029**: A session can be switched between embedded and background; a background
  session leaves the view and is counted in the view's "N sent to background" line.
- **FR-030**: A session can be stopped from its SessionView only after a confirmation.

### Building block: Interaction

- **FR-031**: An interaction has a kind: permission, question, decision, suggestion or
  result.
- **FR-032**: An interaction has a status: pending, allowed, always, denied, answered,
  started, dismissed, terminal (answered in the terminal), timeout or ended.
- **FR-033**: A permission card shows the tool, the exact command or file, the session and
  how long it has waited, with Allow, Always (for this session) and Deny.
- **FR-034**: A question card shows the question and the session's offered answers as
  buttons.
- **FR-035**: A decision card (a Go or a merge decision) shows what is asked, by which
  session, and its scope; approving it is recorded as the maintainer's word only when it
  comes from the logged-in maintainer.
- **FR-036**: A Go card lets the maintainer set the allowed actions (reboot, suspend, load
  test, close apps, eye test), the device, and when it ends (after N runs or after N
  hours).
- **FR-037**: A Go card for an eye test says that the maintainer must look at the device,
  and is never granted as "always".
- **FR-038**: A merge decision card names the PR and the head commit it applies to; it
  stops applying if the PR head changes.
- **FR-039**: A suggestion card names the action, the persona and the items, and offers
  "Launch…" (opens Launch prefilled) and "Dismiss".
- **FR-040**: A result card shows the result type and a summary, and opens the result
  actions for its type (FR-062 to FR-068).
- **FR-041**: Once handled, an interaction shows its final status, who handled it and
  where, and stays visible in the "N handled in this view" line until the view is left.
- **FR-042**: Permission and question cards are blocking; they are the only kinds shown
  yellow (FR-164).
- **FR-043**: Answering an interaction anywhere (card, SessionView, terminal) updates
  every other place it is shown within 5 seconds.

### Building block: Feed

- **FR-044**: A Feed lists interactions in three groups: Blocking, Suggested and Results
  ready, in that order, oldest first within Blocking.
- **FR-045**: A Feed can be filtered to All, The Steward or Other sessions.
- **FR-046**: A Feed has a dense mode with one line per interaction.
- **FR-047**: Each card in a Feed links to its session and its items.

### Building block: Launch

- **FR-048**: Launch can be opened from the header ("＋ New work"), a Work row, a Work
  item, a suggestion, Roadmap, Knowledge or Notes, prefilled with the action and items of
  that place.
- **FR-049**: Launch goes through five stages: brief, planning, plan, run, result. The
  current stage is always visible.
- **FR-050**: The brief stage shows the action, the persona, the covered items (ItemPills,
  added with the ItemPicker), the repositories (RepoPicker), the model and an optional
  note.
- **FR-051**: The brief stage shows the action's result type and ceiling in plain words
  ("ends with a draft PR", "read-only, posts a comment").
- **FR-052**: The planning stage runs a planner on a chosen planner model (Opus, Sonnet or
  Haiku) and shows its progress.
- **FR-053**: The plan stage shows the planned steps and the files or items each step
  touches; the maintainer can edit the brief and plan again, or start.
- **FR-054**: The run stage shows the session in a compact SessionView with its inline
  asks.
- **FR-055**: At any stage after planning, Launch can be sent to the background; a toast
  confirms it and links to the session, and later asks and the result arrive in Needs
  you.
- **FR-056**: A covered item list may span repositories; the session's worktree is created
  in the repository of the first item, and the others are listed as covered.
- **FR-057**: Every Launch is recorded (who, when, from where, action, items, model,
  plan) and the record is shown as the session's origin.
- **FR-058**: Launch refuses to start when an action's ceiling forbids the item kind (for
  example "implement" on a run) and says why.

### Building block: Actions and result types

- **FR-059**: The action library has these actions, each with a fixed persona, result
  type and ceiling:

  | Action | Persona | Result | Applies to |
  |---|---|---|---|
  | review | Code reviewer | comment | PR |
  | address | Kernel engineer (the repository's engineer) | pr | PR |
  | fix | CI fixer | pr | PR, run |
  | implement | Engineer | pr | issue |
  | triage | Triage | labels | issue |
  | investigate | CI investigator | findings | run |
  | issue | Issue writer | drafts | new |
  | sec | Security auditor (Fable) | drafts | new, repository |
  | arch | Architect | drafts | new |
  | road | Steward | drafts | new, roadmap item |
  | docs | Docs writer | drafts | new, roadmap item |
  | deps | Release steward | drafts | new |
  | compact | Archivist | notes | notes |
  | sweep | Docs writer | drafts | notes |
  | research | Researcher | report | Knowledge |

- **FR-060**: Each action has a default model (Fable, Opus, Sonnet or Haiku) that the
  brief can change.
- **FR-061**: An action's ceiling (read-only, comment, branch + draft PR) is enforced by
  the session's permissions, not only shown.
- **FR-062**: A drafts result lists draft issues; each can be filed as is, edited and
  filed, or sent to the Steward.
- **FR-063**: A pr result is a draft PR whose body says "Closes …" for each covered issue,
  with a link to it; for address, it is new commits on that PR's branch only.
- **FR-064**: A comment result shows the review summary and the inline notes and posts
  them on "Post", as a review comment on the PR.
- **FR-065**: A labels result shows the proposed labels and "Part of" lines per issue and
  applies them on "Apply".
- **FR-066**: A findings result shows the cause and the smallest fix, and offers "Start a
  fix session" (opens Launch with fix prefilled).
- **FR-067**: A report result shows the answer, what could not be settled, the sources,
  and follow-ups; it can be saved to Knowledge.
- **FR-068**: A notes result lists note operations (merge, distil, answer, supersede,
  status, retract, flag), each with its exact `notes` command; the operations can be
  applied one by one or all, and none of them deletes a note.

### Building block: GhActions (black split button)

- **FR-069**: GhActions is a black split button labelled with its main action and the
  caption "On GitHub, as {user}"; the arrow opens the other actions.
- **FR-070**: Every GhActions action runs on GitHub as the logged-in maintainer, never as
  an agent.
- **FR-071**: A disabled GhActions action stays in the menu and says why it is disabled.
- **FR-072**: Merge and Close (and Cancel run) ask for confirmation before they act.
- **FR-073**: For a PR, GhActions offers: Merge… (squash, merge commit or rebase), Mark
  ready (draft PRs only), Update branch (shows how many commits behind), Labels…,
  Close/Reopen, and Open on GitHub.
- **FR-074**: Merge… is disabled while checks are running, while the PR is not approved,
  or while review threads are open, and names which of these applies.
- **FR-075**: For an issue, GhActions offers: Close as completed, Close as not planned,
  Reopen, Labels…, Assign to me, and Open on GitHub.
- **FR-076**: For a run, GhActions offers: Re-run failed jobs, Re-run all, Cancel run,
  Download full log, and Open on GitHub.
- **FR-077**: On Work, GhActions offers "New issue…" and "Run workflow…".
- **FR-078**: New issue… asks for the repository (RepoPicker, one), title, description,
  an optional "Part of" item and labels, and offers "Let Claude write it instead", which
  opens Launch with the issue action and what was typed as the brief.
- **FR-079**: Run workflow… asks for the repository, a workflow that can be started by
  hand, a branch or tag, and the workflow's inputs with their types (choice, boolean,
  text).
- **FR-080**: When a repository has no workflow that can be started by hand, Run
  workflow… says so instead of showing an empty form.
- **FR-081**: After a GhActions action, the item view refreshes and shows the result (for
  example "Merged by {user}") within 10 seconds.

### Header

- **FR-082**: The header shows the navigation: Overview, Roadmap, Work, Knowledge, Notes,
  Sessions, with the current view marked.
- **FR-083**: The header shows a "Needs you N" button; it is yellow only when N > 0 and
  something is blocking, outlined when N > 0 and nothing blocks, and plain when N = 0.
- **FR-084**: The "Needs you" button opens the Needs you modal from any view.
- **FR-085**: The header shows "＋ New work", which opens Launch with an empty brief.
- **FR-086**: The header shows the logged-in user and the hubd address it is connected
  to, and shows plainly when hubd cannot be reached.
- **FR-086a**: The header shows a small usage budget meter: how much of the sessions'
  usage allowance is used, in words as well as a bar, and says plainly when it is low.

### Overview

- **FR-087**: Overview shows a Needs-you card with the count, the breakdown by kind, and
  the longest wait; it opens Needs you.
- **FR-088**: Overview shows four stats: running sessions, open issues, open PRs (with
  how many fail), and Knowledge (indexed documents).
- **FR-089**: Overview shows the device lock state: free, or held by whom (session or
  maintainer) since when, and for which Go if any.
- **FR-090**: Overview lists the repositories grouped by layer, each layer sorted by
  attention (failing runs, waiting sessions, open PRs, then recent activity).
- **FR-091**: Each layer shows 5 repositories, then "Show N more".
- **FR-092**: Overview has a text filter, a "Needs attention only" switch, and "Collapse
  all" / "Expand all".
- **FR-093**: Each repository row shows the strip of recent CI runs, the last commit, the
  time of the last activity, the sessions on it (SessionChips) and "Launch…".
- **FR-094**: Repositories not assigned to a layer are listed on an "Unplaced" line.

### Roadmap

- **FR-095**: Roadmap shows roadmap items in four columns: Planned, In progress, In review,
  Done.
- **FR-096**: A roadmap card shows the reference and target, the title, a progress bar per
  repository computed from the issues that are "Part of" it, who works on it, and its
  SessionChips.
- **FR-097**: A roadmap card offers "Plan issues…", which opens Launch with the road
  action on that item.
- **FR-098**: Opening a roadmap card shows the Work item view for it, with the actions
  road and docs.

### Work

- **FR-099**: Work has a RepoPicker that allows "All repositories" and remembers the last
  selection per viewer.
- **FR-100**: Work has kind tabs: PRs, Issues, Runs, each with a count for the current
  selection.
- **FR-101**: PRs are grouped into: Needs you, From agent sessions, Everything else.
- **FR-102**: Issues are grouped into: Untriaged, In sessions, Backlog.
- **FR-103**: Runs are grouped into: Failed, Running, Recent.
- **FR-104**: Each row shows the kind icon, the reference, the title, a sub-line (Part of,
  size, author or trigger, duration, age), the state badge and the SessionChips.
- **FR-105**: Each row has one blue action: fix if failing, address if reviewed with
  changes requested, triage if untriaged, otherwise the kind's default (review for PRs,
  implement for issues, investigate for runs).
- **FR-106**: Work has GhActions for kind "work" (FR-077).
- **FR-107**: Work also offers a "Queue" view of open PRs grouped into merge sets, in
  order; approving a set asks for a merge decision (FR-038).
- **FR-107a**: An agent session may merge a PR only under a merge decision the maintainer
  approved for that PR's current head commit (FR-038); every other merge is the
  maintainer's own Merge… (FR-073).

### Work item

- **FR-108**: The Work item view shows a breadcrumb (Work › repository › reference), the
  state, the title and the reference.
- **FR-109**: The view shows GhActions for the item kind next to the title.
- **FR-110**: A Details flyout shows: Part of, branch, size, author, labels, assignee,
  trigger, runner, target, repositories, updated, and changed files, as they apply to the
  kind.
- **FR-111**: A facts line shows the most important facts in one line (for example
  "+288 −31 · 4 files · 3 behind · checks passing").
- **FR-112**: A "Launch on {reference}" row shows the blue action buttons that apply to
  the kind, the best one as primary, plus "New work from this…" (opens Launch with the
  item as context).
- **FR-113**: The view shows the item body rendered as Markdown and the checks as chips.
- **FR-114**: A PR has two tabs: Conversation and Files changed.
- **FR-115**: Conversation lists review threads; each can be ticked, and "Address N
  threads…" opens Launch with the address action and those threads.
- **FR-116**: Conversation has a comment box with "Post" and "Draft with Claude", which
  opens Launch with the review action and a comment result.
- **FR-117**: Files changed lists the files with added and removed line counts; each file
  opens to its diff hunks with line numbers and the inline review notes at their lines.
- **FR-118**: A large file shows "Large file — load the diff" instead of the diff until
  asked.
- **FR-119**: A run shows the log of the failed step, with the error lines marked, and a
  link to the full log.
- **FR-120**: A "Sessions on {reference} · N" section has persona tabs, one per session,
  each showing the session as an embedded SessionView.
- **FR-121**: The section shows "N sent to background" when sessions on this item run in
  the background, with a link to each.
- **FR-122**: When no session covers the item, the section shows a suggestion interaction
  for the best action.

### Knowledge

- **FR-123**: Knowledge has a search box with a meaning / exact switch.
- **FR-124**: Knowledge searches three domains: Docs, Work items and Code; a domain that
  is not indexed yet is shown as "planned" and cannot be chosen.
- **FR-125**: Knowledge has a RepoPicker (many), an "Open only" switch for work items, and
  a ranked or grouped-by-repository layout.
- **FR-126**: A result card shows the kind, the title, the score, a snippet with the
  matched words marked, SessionChips (for work items), "Open" and "Pin as context".
- **FR-127**: "Try" chips offer example searches when the box is empty.
- **FR-128**: When a search has no good hits, Knowledge offers to research the question.
- **FR-129**: "Research this…" (with the number of pins) opens a flyout with the research
  question, the scope, the pins and "Plan a research session…" (Launch, research action).
- **FR-130**: The flyout lists earlier research reports; each can be opened or followed up
  (Launch with the report as context).
- **FR-131**: The flyout shows each index with its state and age: Docs ("Run docs CI
  now"), Work items ("Ingest now"), Code (planned).

### Notes

- **FR-132**: Notes searches by words only; the search runs on a button press, accepts at
  most 500 characters, and is not kept in the address bar.
- **FR-133**: Notes shows 20 rows, then more on request up to 100; past 100 it shows a
  limit box with a copyable `notes` command that lists everything.
- **FR-134**: Each row shows the trust label (CURRENT, OPEN QUESTION, HISTORY, RETRACTED,
  ARCHIVE·UNREVIEWED, NO STATUS), the title, the topic and the date; a long row can be
  expanded.
- **FR-135**: Notes shows these states: empty (with the label legend), no results, more
  available, limit reached, notes tool missing, notes tool failed (with the tool's
  message), warnings, and an "indexing" badge while the index updates.
- **FR-136**: A "Keep notes useful" flyout shows totals per label and per topic, and
  offers "Compact…" and "Sweep…" for all notes or per topic.

### Sessions › Running

- **FR-137**: Running lists sessions in groups: embedded in a view, in the background,
  finished with tmux still open, and plain shells.
- **FR-138**: Each row shows the PersonaBadge, the state, "N waiting", a sub-line (origin,
  model, age), "⇄ also on" items and the covered items.
- **FR-139**: The list can be narrowed to badges only; the selected session opens in a
  full SessionView beside it.
- **FR-140**: Running offers "＋ Plain shell" (a shell in a chosen repository's worktree)
  and "Resume a past session" (opens History).

### Sessions › History & cleanup

- **FR-141**: History lists past sessions with persona, items, outcome, start and end,
  and can be filtered by persona, repository and outcome.
- **FR-142**: History searches the transcripts of past sessions by words.
- **FR-143**: A past session offers "Resume" when its worktree exists and "Restore &
  resume" when it was removed; both show a busy state, and a session already running
  again says so instead.
- **FR-144**: A past session offers "Transcript", which opens its full transcript
  read-only.
- **FR-145**: Cleanup lists every worktree under `~/hub-worktrees` with its repository,
  branch, PR state, uncommitted changes and age.
- **FR-146**: Each cleanup row shows the exact command that removing it will run.
- **FR-147**: "Select safe" selects only worktrees with no uncommitted changes, no running
  session and a merged or closed PR.
- **FR-148**: A setting "Remove automatically 7 days after the PR merges" can be turned on
  and off.

### Needs you

- **FR-149**: Needs you opens as a modal from the header on any view, and as a sheet on
  phone.
- **FR-150**: Needs you shows every pending interaction (permission, question, decision,
  suggestion, result) as a Feed (FR-044 to FR-047).
- **FR-151**: Needs you has an "Active grants" filter that lists approved Go and merge
  decisions still in force, with what is left (runs, hours) and "End now".
- **FR-152**: Needs you can be filtered to one session (used by the Steward's waiting
  strip).
- **FR-153**: Closing Needs you returns to the same place in the view below.

### Steward

- **FR-154**: The Steward is a side panel on the right that can be resized between 320
  and 760 px; the width is remembered per viewer.
- **FR-155**: The Steward panel is open by default on Overview, Roadmap, Work and Work
  item, and collapsed by default on Sessions, Knowledge and Notes.
- **FR-156**: The Steward shows the session in a compact SessionView with its model and a
  model select.
- **FR-157**: SEES chips show what the Steward is told about the current view (the view,
  the selected repositories, the open item).
- **FR-158**: A waiting strip shows how many interactions from the Steward wait, and
  opens Needs you filtered to the Steward.
- **FR-159**: "＋ Plan new work with the Steward" sends the current view's context to
  the Steward as a request; the maintainer can add their own words (FR-027).

### Phone (≤ 760 px)

- **FR-160**: At 760 px wide or less, the header shows only "New" and "Menu"; Menu holds
  the navigation, Needs you and the user line.
- **FR-161**: At phone width the Steward is a floating button that opens it as a full
  sheet.
- **FR-162**: At phone width, views use a single column with 16 px side gutters, and no
  page scrolls sideways (wide content such as diffs and terminals scrolls inside its own
  box).
- **FR-163**: At phone width, Launch, Needs you and flyouts open as full sheets.

### Cross-cutting rules

- **FR-164**: Yellow (#ffd86b) marks only things that wait for the maintainer; no other
  state uses it.
- **FR-165**: Severity is shown by outline, not colour: double = high or failed, heavy =
  medium or blocked, solid = low, dashed = info, running or draft.
- **FR-166**: Pen blue (#2747b8) marks the one primary agent action of a place (Launch
  and the actions that start an agent) and the Steward; GitHub actions done by the
  maintainer are the black split button; the two are never combined in one control.
- **FR-167**: Ink (#111) on paper is the base; terminals use night paper (#121212).
- **FR-168**: Every control has an accessible name; state is never shown by colour
  alone; focus is always visible.
- **FR-169**: Every view can be used by keyboard alone; modals and sheets trap focus and
  close on Esc.
- **FR-170**: Text and controls meet WCAG 2.2 AA contrast, and touch targets are at least
  44 × 44 px on phone.
- **FR-171**: Animations are off when the viewer asks for reduced motion, and the app
  stays usable on an e-ink browser (no motion needed to understand state).
- **FR-172**: Lists that can grow past one screen show a count and load more on request;
  no view loads all items of all repositories at once.
- **FR-173**: Live data (sessions, interactions, terminals) updates without a page
  reload; the app shows when it is out of date or disconnected.

### Security and trust

- **FR-174**: The browser never holds GitHub or Claude credentials; every GitHub action
  and every session runs through hubd.
- **FR-175**: Every GitHub write an agent session asks for goes through the hub's policy
  allowlist, which refuses anything not listed.
- **FR-176**: A decision counts as the maintainer's word only when it is approved by the
  logged-in maintainer in the app, never from agent or tool text.
- **FR-177**: Text written by an agent (cards, reports, suggestions) never widens what an
  agent may do.
- **FR-178**: The app accepts requests only from the logged-in maintainer and binds to
  the local host unless set otherwise.

## Contracts

| Contract | Owned / consumed | Version | Spec location |
|---|---|---|---|
| Web API (`/api/...`, used by the app only) | Owned, internal | Unversioned; changes ship with the app | `app/hub/web.py` |
| hubd unix socket (requests from the web app) | Owned, internal | Unversioned; web app and hubd ship together | `hubd/` |
| Tool server tools (MCP, used by running sessions) | Owned | Not versioned; changes must stay safe for sessions already running | `app/hub/tools.py`, `docs/orchestrator.md` |
| Action and persona library | Owned | Not versioned; same rule as tools | `agents/actions/`, `agents/personas/` |
| `gh` CLI / GitHub API | Consumed (GitHub) | Installed version; not pinned | `ghpolicy.py` allowlist |
| Claude Code CLI | Consumed (Anthropic) | Installed version; not pinned | `hubd/agents.py` |
| Search index (docs, work items) | Consumed (GlassineOS search) | As deployed | search repository |
| `notes` CLI | Consumed | Installed version | `hubd/notes.py` |

New or changed owned surfaces this spec needs: session `covers[]` and `prs[]`, session
view/origin, interactions with results, Launch records, and the research and compact
actions (see Implementation notes).

## Device scope and risk

No device risk. The hub never touches devices. It shows device-related decisions (Go
cards) and the device lock holder (FR-089) as data reported by sessions and the lock. It
does not take the lock, flash, reboot or connect to a device itself. Granting a Go gives
a session permission to act within that Go's scope; what the session does on the device
is governed by the device repositories' own rules.

## Acceptance

Host level, in this repository (`make check`: `node --check` on the app plus `pytest`):

- Web API tests for each view's data (Overview attention order and "Show N more"; Work
  groups and the row action rule FR-105; Roadmap progress from Part-of; Notes limits
  FR-132/FR-133; cleanup "Select safe" FR-147).
- hubd tests with the fake Claude CLI: Launch stages and records, covers across
  repositories, background hand-off, interactions with every status, results per type,
  decisions (Go scope and end, merge head check, eye test never "always").
- Policy tests: every GhActions action maps to an allowed `gh` call made as the
  maintainer; disabled reasons (FR-074); agent requests outside the allowlist refused.
- Tool server tests: the new tools and the changed ones keep working for a session
  started before the change.
- Static checks on the app: navigation items, the yellow rule (FR-164) applied only to
  waiting states.
- hubd tests for typed messages (FR-027): refused without a logged-in maintainer, sent as
  typed input, recorded as the maintainer's.

Browser check (by hand, recorded in the PR, at 1440 px and 390 px wide):

- Header, Needs you modal from every view, Launch through all five stages, Steward resize
  and collapse defaults, Work item tabs and diff, terminal rendering and scroll keeping,
  phone menu and sheets, no sideways scroll, keyboard-only pass, reduced motion.

Product level: none. The hub is not part of a device image.

## Out of scope

- Any action on a device (flashing, rebooting, taking the device lock) by the hub itself.
- A device page or device control panel.
- Code search as a working domain in Knowledge (shown as planned until the code index
  exists).
- More than one maintainer, roles or sharing the hub with others.
- Editing files or pushing commits by hand from the app.
- Running sessions on another machine than the hub's host.

## Success criteria

- **SC-001**: From any view, a blocking interaction can be answered in at most 2
  activations (open Needs you, choose the answer).
- **SC-002**: A new interaction shows in the header count and in Needs you within 5
  seconds of the session raising it.
- **SC-003**: From a Work row or suggestion, a session can be started in at most 4 steps
  (open Launch, plan, read plan, start).
- **SC-004**: 100 % of GitHub actions in the app are reached through the black split
  button, and 100 % of disabled ones state a reason.
- **SC-005**: 0 GitHub writes are made by agents outside the policy allowlist (policy
  tests cover every listed call and at least one refused call per kind).
- **SC-006**: With 60 repositories and 500 open items, Overview and Work render their
  first screen in under 2 seconds on the host.
- **SC-007**: At 390 px wide, no view scrolls sideways and every control is at least
  44 × 44 px.
- **SC-008**: Cleanup's "Select safe" never selects a worktree with uncommitted changes
  or a running session (tested on fixtures with each case).
- **SC-009**: No view shows more than 3 repository pills at once.
- **SC-010**: The keyboard-only browser pass completes every P1 scenario without a mouse.

## Implementation notes

Existing code to reuse:

- Web app (`app/hub/web.py`, `app/hub/static/app.js`) already has views for overview,
  roadmap, work lists, issue/PR/run detail, new issue, workflow dispatch, docs search,
  terminal, session spec, new work and launch forms, inbox, past sessions, cleanup,
  plain shells, decisions, the merge queue, notes and the Steward panel. Navigation tests
  in `tests/test_app.py` pin the current menu and must change with FR-082.
- hubd (`hubd/agents.py`) runs sessions in tmux (`-L glassine-hub`) with worktrees under
  `~/hub-worktrees`. Input from the page is preset keys only (`press`, page sends the id,
  never the words); FR-027 replaces that rule, so `SECURITY.md` and `docs/orchestrator.md`
  change in the same pull request.
- `hubd/decisions.py` has Go and merge decisions with scope, run and hour limits, head
  checks and the eye-test rule; this backs the decision cards and Active grants.
- `ghpolicy.py` is the fail-closed allowlist; `app/hub/github.py` has issue/PR/run
  reads, sub-issue rollups and work search.
- `app/hub/tools.py` has about 50 tool server tools (including suggest_session,
  plan_work, docs_search, work_search, code_search, decision_request, merge_pr).
- `agents/actions/*.toml` and `agents/personas/` hold the action and persona library;
  `tests/test_agents.py` has a fake Claude CLI; `tests/dev_hubd.py` runs a dev hubd.

Backend that is missing:

- Sessions: `covers[]` across repositories (today only extra numbers in one repository)
  and `prs[]`; the view (embedded or background) and the origin; permission mode in the
  session fields.
- Interactions: one model for permission, question, decision, suggestion and result,
  with the statuses in FR-032 and result payloads per type.
- Launch records (FR-057) and the planning and plan stages as hubd state.
- Actions `research` (report result) and `compact` (notes result); persona family on each
  persona.
- Knowledge: search across domains with pins, research reports stored and listed, index
  state and the "Ingest now" / "Run docs CI now" triggers.
- Notes upkeep: totals by label and topic, and applying note operations (hubd has status
  and find only).
- Roadmap progress per repository from "Part of" (issue fields have no Part-of today; the
  sub-issue rollup can feed it).
- GitHub: PR approval, behind count, review threads with ticks, diff hunks, failed-step
  logs, workflow inputs, and the GhActions writes made as the maintainer.
- Device lock state for Overview (read only).
- `tests/dev_hubd.py` hard-codes the tool server port; parallel test runs need it
  configurable.
