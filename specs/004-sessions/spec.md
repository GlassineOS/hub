# Feature Specification: Sessions

**Feature Branch**: `001-hub-app`
**Created**: 2026-11-06
**Status**: Draft
**Input**: "Sessions: the SessionView (full chat with typed messages), what a session knows (covers, PRs, view, origin), Sessions › Running, and History & cleanup."

## Context

A session is a Claude Code (or plain shell) process with a persona, covered items and a
terminal. Sessions run in tmux on the host, each in its own git worktree. This spec defines
the **SessionView** (the full chat with a session, in three sizes), what a session knows
about itself (the items and PRs it covers, where it is shown, where it came from),
**Sessions › Running**, and **Sessions › History & cleanup**, which resumes past sessions
and keeps the host tidy.

Depends on: [001](../001-app-frame/spec.md), [002](../002-building-blocks/spec.md)
(PersonaBadge, ItemPill, SessionChip) and [003](../003-needs-you/spec.md) (inline
interactions). Launch ([005](../005-launch/spec.md)) starts sessions and records their
origin; the Steward panel ([010](../010-steward/spec.md)) shows its session in the compact
SessionView.

## Views

- **SessionView**: shows one session in full (Sessions), embedded (inside a Work item) or
  compact (Steward panel), as a chat with its live terminal.
- **Sessions › Running**: lists every live session and plain shell and opens any of them
  in full.
- **Sessions › History & cleanup**: resumes or reads past sessions and removes the
  worktrees they left behind.

## User scenarios

### Scenario 1 – Clean up old worktrees (Priority: P2)

**Given** twenty worktrees under `~/hub-worktrees`, some for merged PRs
**When** the maintainer opens History & cleanup, presses "Select safe" and removes them
**Then** only the worktrees with no uncommitted work and a merged or closed PR are
removed; each row showed the exact command first; the rest stay.

### Scenario 2 – Resume a past session (Priority: P3)

**Given** a finished session whose worktree was removed
**When** the maintainer finds it by searching transcripts in History and presses
"Restore & resume"
**Then** the worktree is recreated on the session's branch and the session resumes with
its earlier conversation.

## Requirements

Requirements are one testable statement each. A requirement of another spec is written with
that spec's number first, as in `001 FR-011`.

### SessionView

- **FR-001**: A SessionView has three modes: full (Sessions), embedded (inside a Work
  item) and compact (Steward panel).
- **FR-002**: The SessionView header shows the PersonaBadge, the persona name, the model,
  the state, the branch and the origin (where and why it was started), tinted with the
  persona's family tint.
- **FR-003**: The SessionView shows the covered items and PRs as ItemPills.
- **FR-004**: When a session covers more than one item, an "Also on these items" switcher
  shows the other items and opens them.
- **FR-005**: The SessionView shows the live terminal of the session on night paper
  (#121212), scrolled to the end, with the user's scroll position kept while new output
  arrives.
- **FR-006**: Pending interactions for that session are shown inline above the terminal
  and can be answered there, with the same effect as answering them in Needs you.
- **FR-007**: A SEND row offers the session's preset reply buttons and Esc.
- **FR-008**: Every Claude session, the Steward included, is a full chat: the SessionView
  has a message field, and what the maintainer types is sent to the session as their
  message. Only the logged-in maintainer can send, the text reaches the session through
  hubd as typed input (never as a command-line argument), and the transcript shows it as
  the maintainer's.
- **FR-009**: A "Session spec" disclosure shows the persona, action, model, permission
  mode, ceiling, covered items, worktree path, branch and start command.
- **FR-010**: A session can be switched between embedded and background; a background
  session leaves the view and is counted in the view's "N sent to background" line.
- **FR-011**: A session can be stopped from its SessionView only after a confirmation.

### Sessions › Running

- **FR-012**: Running lists sessions in groups: embedded in a view, in the background,
  finished with tmux still open, and plain shells.
- **FR-013**: Each row shows the PersonaBadge, the state, "N waiting", a sub-line (origin,
  model, age), "⇄ also on" items and the covered items.
- **FR-014**: The list can be narrowed to badges only; the selected session opens in a
  full SessionView beside it.
- **FR-015**: Running offers "＋ Plain shell" (a shell in a chosen repository's worktree)
  and "Resume a past session" (opens History).

### Sessions › History & cleanup

- **FR-016**: History lists past sessions with persona, items, outcome, start and end,
  and can be filtered by persona, repository and outcome.
- **FR-017**: History searches the transcripts of past sessions by words.
- **FR-018**: A past session offers "Resume" when its worktree exists and "Restore &
  resume" when it was removed; both show a busy state, and a session already running
  again says so instead.
- **FR-019**: A past session offers "Transcript", which opens its full transcript
  read-only.
- **FR-020**: Cleanup lists every worktree under `~/hub-worktrees` with its repository,
  branch, PR state, uncommitted changes and age.
- **FR-021**: Each cleanup row shows the exact command that removing it will run.
- **FR-022**: "Select safe" selects only worktrees with no uncommitted changes, no running
  session and a merged or closed PR.
- **FR-023**: A setting "Remove automatically 7 days after the PR merges" can be turned on
  and off.

## Contracts

| Contract | Owned / consumed | Version | Spec location |
|---|---|---|---|
| Web API routes and hubd ops of this spec | Owned, internal | Unversioned; ship with the app (001) | `contracts/web-api.md`, `contracts/hubd-socket.md`, `contracts/tool-server-and-library.md` |
| Claude Code CLI | Consumed (Anthropic) | Installed version; not pinned | `hubd/agents.py` |

Web API and hubd socket: [001](../001-app-frame/spec.md) Contracts; this spec's routes and
ops are in `contracts/`. New or changed owned surfaces this spec needs: session `covers[]` and
`prs[]`, session view and origin, typed messages (`agent.say`).

## Device scope and risk

No device risk (see [001](../001-app-frame/spec.md) Device scope and risk).

## Acceptance

Host level, in this repository (`make check`: `node --check` on the app plus `pytest`):

- Web API tests: cleanup "Select safe" (FR-022).
- hubd tests for typed messages (FR-008): refused without a logged-in maintainer, sent as
  typed input, recorded as the maintainer's.

Browser check (by hand, recorded in the PR, at 1440 px and 390 px wide; rows in
[001 quickstart](../001-app-frame/quickstart.md) §3):

- Terminal rendering and scroll keeping.

Product level: none. The hub is not part of a device image.

## Out of scope

- Running sessions on another machine than the hub's host.

## Success criteria

- **SC-001**: Cleanup's "Select safe" never selects a worktree with uncommitted changes
  or a running session (tested on fixtures with each case).

## Implementation notes

Existing code to reuse:

- hubd (`hubd/agents.py`) runs sessions in tmux (`-L glassine-hub`) with worktrees under
  `~/hub-worktrees`. Input from the page is preset keys only (`press`, page sends the id,
  never the words); FR-008 replaces that rule, so `SECURITY.md` and `docs/orchestrator.md`
  change in the same pull request.

Backend that is missing:

- Sessions: `covers[]` across repositories (today only extra numbers in one repository)
  and `prs[]`; the view (embedded or background) and the origin; permission mode in the
  session fields.
