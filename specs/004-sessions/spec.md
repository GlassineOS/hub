# Feature Specification: Sessions

**Feature Branch**: `001-hub-app`
**Created**: 2026-11-06
**Status**: Draft
**Input**: "Sessions: the session view (full chat with typed messages), what a session knows (covers, PRs, view, origin), Sessions › Running, and History & cleanup."

## Context

A session is a Claude Code session (or a plain shell) with a persona, covered items and a
terminal. Each runs on the host in its own git worktree. This spec defines the
**session view** (the full chat with a session, in three sizes), what a session knows about
itself (the items and pull requests it covers, where it is shown, where it came from),
**Sessions › Running**, and **Sessions › History & cleanup**, which resumes past sessions
and keeps the host tidy.

It uses App frame (001), the persona badge, item pill and session chip (Building blocks,
002) and inline interactions (Needs you, 003). Launch (005) starts sessions and records
their origin; the Steward panel (Steward, 010) shows its session in the compact
session view.

### Views

- **Session view**: shows one session in full (Sessions), embedded (inside a Work item) or
  compact (Steward panel), as a chat with its live terminal.
- **Sessions › Running**: a tree of the running workflows and their sessions beside tabbed,
  tiled session views.
- **Sessions › History & cleanup**: resumes or reads past sessions and removes the
  worktrees they left behind.

## User Scenarios & Testing

### User Story 1 - Clean up old worktrees (Priority: P2)

The maintainer removes the worktrees that are safe to remove, and only those.

**Why this priority**: Worktrees pile up with every session; removing the wrong one
loses work.

**Independent Test**: With a mix of worktrees (merged, open, with uncommitted changes,
with a running session), use "Select safe" and remove.

**Acceptance Scenarios**:

1. **Given** twenty worktrees in the hub's worktree folder, some for merged pull
   requests, **When** the maintainer opens History & cleanup, presses "Select safe" and
   removes them, **Then** only the worktrees with no uncommitted work and a merged or
   closed pull request are removed; each row showed the exact command first; the rest
   stay.

---

### User Story 2 - Resume a past session (Priority: P3)

The maintainer picks up a finished session where it stopped.

**Why this priority**: Useful, but most work starts fresh from Launch.

**Independent Test**: Remove a finished session's worktree, then find and resume it.

**Acceptance Scenarios**:

1. **Given** a finished session whose worktree was removed, **When** the maintainer finds
   it by searching transcripts in History and presses "Restore & resume", **Then** the
   worktree is recreated on the session's branch and the session resumes with its earlier
   conversation.

### User Story 3 - See every workflow and who works for whom (Priority: P1)

The maintainer opens Sessions and sees each running workflow as a tree: the Steward,
repository maintainers, implementors, and under each owner the sessions it manages, grouped by
the workflow's entries. They open an implementor and its engineer side by side and follow the
work as it moves.

**Why this priority**: Workflows start sessions under sessions; a flat list hides who owns
what and which ticket each one works on.

**Independent Test**: Run an implementor through implement, fix, review and merge-ready; check
at each step that the tree shows the owner chain, the entries with their sessions and rounds,
the item badges and liveness, and that the open tiles follow without a reload.

**Acceptance Scenarios**:

1. **Given** an implementor with a running engineer, **When** the maintainer opens Sessions,
   **Then** the engineer shows under the implementor's "engineer" entry with its state, its
   liveness in words and the pull request's state and checks.
2. **Given** the engineer is resumed for a fix round, **When** the tree updates, **Then** the
   same row says it was resumed and which rounds it served, and no second engineer appears.
3. **Given** a reviewer that starts fresh each round, **When** the second round's reviewer
   starts, **Then** the first round's reviewer folds into "1 earlier reviewer" with its
   verdict.
4. **Given** a wide screen, **When** the maintainer opens a workflow, **Then** its sessions
   open as side-by-side tiles; choosing a row focuses its tile and focusing a tile selects
   its row.

### Edge Cases

- A past session is already running again: Resume says so instead of starting a second
  copy.
- A worktree has uncommitted changes or a running session: "Select safe" never selects
  it.
- Someone other than the signed-in maintainer tries to type into a session: it is
  refused.
- An owner's session has ended while a session it managed still runs (kept on exit): the
  child shows under the ended owner, which stays visible while anything under it runs.
- A workflow lets an entry run several sessions at once: each shows under that entry with its
  count against the entry's most.

## Requirements

Each requirement is one testable statement. A requirement of another spec is cited with
that spec's name and number, as in "App frame (001) FR-011".

### Functional Requirements

#### Session view

- **FR-001**: A session view has three modes: full (Sessions), embedded (inside a Work
  item) and compact (Steward panel).
- **FR-002**: The session view header shows the persona badge, the persona name, the model,
  the state, the branch and the origin (where and why it was started), tinted with the
  persona's family tint.
- **FR-003**: The session view shows the covered items and pull requests as item pills.
- **FR-004**: When a session covers more than one item, an "Also on these items" switcher
  shows the other items and opens them.
- **FR-005**: The session view shows the live terminal of the session on night paper
  (#121212), scrolled to the end, with the user's scroll position kept while new output
  arrives.
- **FR-006**: Pending interactions for that session are shown inline above the terminal
  and can be answered there, with the same effect as answering them in Needs you.
- **FR-007**: A SEND row offers the session's preset reply buttons and Esc.
- **FR-008**: Every Claude Code session, the Steward included, is a full chat: the
  session view has a message field, and what the maintainer types is sent to the session
  as their message. Only the signed-in maintainer can send a message into a session, a
  typed message is never visible to other processes on the machine, and the transcript
  shows it as the maintainer's.
- **FR-009**: A "Session spec" disclosure shows the persona, action, model, permission
  mode, ceiling, covered items, worktree location, branch and the command that started
  the session.
- **FR-010**: A session can be switched between embedded and background; a background
  session leaves the view and is counted in the view's "N sent to background" line.
- **FR-011**: A session can be stopped from its session view only after a confirmation.

#### Sessions › Running

- **FR-012**: Running shows a tree. Its roots are the sessions no other session owns: the
  Steward, repository maintainers, workflows started from an item, then one-state quick
  tasks grouped by their item, then plain shells.
- **FR-013**: Under an owner, its sessions are grouped by the managing entry of its workflow
  (Workflows (012) FR-040): each entry shows its name, whether it resumes or starts fresh,
  how it starts (by itself, on request, or when its condition holds), the round, and how many
  run against its most; an entry not in force in the owner's current state says in which
  states it runs. How many entries and sessions an owner has comes from its workflow
  definition only.
- **FR-014**: A session resumed for later work keeps one row that names the rounds and states
  it served. Sessions of earlier rounds of an entry that starts fresh fold into one line with
  their returns (such as verdicts); the line opens to list them.
- **FR-015**: Each row shows the persona badge, the session's name, its liveness in words and
  a mark (working, idle, waits for you, stopped, ended), its workflow state as a state chip,
  a Needs-you marker with its count, the items it covers and holds as item pills with their
  state (issue open or closed; pull request draft, open or merged; checks; review verdict),
  and its time and cost when known. Colour is never the only carrier.
- **FR-024**: The tree updates live: moves, starts, resumes, ends, returns and item changes
  show within 5 seconds without a reload. An ended session stays while it has a card waiting,
  or while it is the latest return of an entry under a running owner; "Ended" shows the rest.
- **FR-025**: The tree can be narrowed by Needs you, working, repository and a search over
  session names and items; owners above a match stay shown, dimmed. It is a keyboard tree
  (arrows, Home, End, Enter opens, Space selects) with collapse and expand.
- **FR-026**: Session views open as tabs grouped by workflow, and a group can be pinned. On a
  wide screen up to three tabs show side by side as tiles whose widths can be changed by
  pointer and keyboard; below the width for two, only the focused tile shows. "Open this
  workflow" opens an owner and the sessions under it as tiles.
- **FR-027**: Each tile has the session view header with links to its owner and to the
  sessions under it, the terminal, and a strip with the workflow state, what it waits for and
  the next exit in words. The focused tile is marked in shape and words; Ctrl+] and Ctrl+[
  move between tiles and Ctrl+↑ opens the owner.
- **FR-028**: Choosing a row focuses its tile, or opens it in the focused tile's place unless
  that tile is pinned; focusing a tile selects its row and opens the rows above it.
- **FR-029**: Running offers "＋ Plain shell" (a shell in a chosen repository's worktree) and
  "Resume a past session" (opens History).
- **FR-030**: On a phone, the tree is a list that drills into an owner; a session opens alone,
  with switches to its owner, the sessions under it and its siblings.

#### Sessions › History & cleanup

- **FR-016**: History lists past sessions with persona, items, outcome, start and end,
  and can be filtered by persona, repository and outcome.
- **FR-017**: History searches the transcripts of past sessions by words.
- **FR-018**: A past session offers "Resume" when its worktree exists and "Restore &
  resume" when it was removed; both show a busy state, and a session already running
  again says so instead.
- **FR-019**: A past session offers "Transcript", which opens its full transcript
  read-only.
- **FR-020**: Cleanup lists every worktree in the hub's worktree folder with its
  repository, branch, pull request state, uncommitted changes and age.
- **FR-021**: Each cleanup row shows the exact command that removing it will run.
- **FR-022**: "Select safe" selects only worktrees with no uncommitted changes, no running
  session and a merged or closed pull request.
- **FR-023**: A setting "Remove automatically 7 days after the PR merges" can be turned on
  and off.

### Key Entities

- **Session**: a Claude Code session or plain shell; has a persona, model, state, branch,
  worktree, covered items, pull requests, a view (embedded or background) and an origin.
- **Workflow tree node**: a session placed under its owner by the managing entry that started
  it, with the rounds it served, its liveness, state and items.
- **Origin**: where and why a session was started (its Launch record, Launch (005)
  FR-010).
- **Worktree**: a session's working copy on the host; has a repository, branch, pull
  request state, uncommitted changes and age.
- **Transcript**: the full conversation of a session, kept after it ends.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Cleanup's "Select safe" selects 0 worktrees that have uncommitted changes
  or a running session.

## Assumptions

- Sessions run on the hub's own host; running them on another machine is out of scope.
- Claude Code is installed on the host; the hub works with the version installed there.
- Resuming a session relies on Claude Code keeping the session's earlier conversation.
- A worktree's pull request state is as GitHub reports it.
