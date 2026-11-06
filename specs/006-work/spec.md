# Feature Specification: Work

**Feature Branch**: `001-hub-app`
**Created**: 2026-11-06
**Status**: Draft
**Input**: "Work: the Work list (groups, row action, Queue view, the agent merge rule), the Work item (details, diff, run log, sessions on an item) and GhActions (incl. New issue and Run workflow)."

## Context

Work is where the maintainer sees the PRs, issues and CI runs of the chosen repositories,
grouped by what they need, and turns any of them into work for an agent. The Work item
shows everything about one item, with agent actions and GitHub actions side by side. The
GitHub actions the maintainer does as themselves (merge, close, label, re-run, file an
issue, start a workflow) sit one click from the item in the black GhActions button, never
mixed up with starting an agent.

Depends on: [001](../001-app-frame/spec.md), [002](../002-building-blocks/spec.md),
[003](../003-needs-you/spec.md) (merge decisions, 003 FR-008), [004](../004-sessions/spec.md)
(sessions on an item) and [005](../005-launch/spec.md) (Launch, the action table, results).

## Views

- **Work**: lists PRs, issues and CI runs across the chosen repositories, grouped by what
  they need, with one suggested agent action per row.
- **Work item**: everything about one item (body, checks, conversation, diff or log, and
  the sessions on it), with agent actions and GitHub actions side by side.
- **GhActions**: the black split button that does GitHub actions as the maintainer.

## User scenarios

### Scenario 1 – Review a PR, then merge it yourself (Priority: P1)

**Given** a PR whose checks passed
**When** the maintainer launches "review" from the Work item, reads the resulting review
summary and inline notes and posts them, then uses the black "Merge…" split button and
confirms "squash"
**Then** the review is posted as a comment by the reviewer session's result, the PR is
merged on GitHub as the maintainer, and no agent took the merge step.

### Scenario 2 – Fix a failing CI run (Priority: P1)

**Given** a run in the Failed group on Work
**When** the maintainer presses the row's blue "fix" button (or "investigate" on the run
page)
**Then** the investigate result shows the cause and the smallest fix, with a button to
start a fix session; the fix session's draft PR says "Closes …" for each covered issue.

### Scenario 3 – File an issue or start a workflow by hand (Priority: P3)

**Given** the maintainer is on Work
**When** they use "New issue…" (or "Run workflow…") from the black split button and fill
in the form
**Then** the issue is created (or the workflow is dispatched) as the maintainer. The issue
form also offers "Let Claude write it instead", which opens Launch with the issue-writer
action.

## Requirements

Requirements are one testable statement each. A requirement of another spec is written with
that spec's number first, as in `001 FR-011`.

### Work

- **FR-001**: Work has a RepoPicker that allows "All repositories" and remembers the last
  selection per viewer.
- **FR-002**: Work has kind tabs: PRs, Issues, Runs, each with a count for the current
  selection.
- **FR-003**: PRs are grouped into: Needs you, From agent sessions, Everything else.
- **FR-004**: Issues are grouped into: Untriaged, In sessions, Backlog.
- **FR-005**: Runs are grouped into: Failed, Running, Recent.
- **FR-006**: Each row shows the kind icon, the reference, the title, a sub-line (Part of,
  size, author or trigger, duration, age), the state badge and the SessionChips.
- **FR-007**: Each row has one blue action: fix if failing, address if reviewed with
  changes requested, triage if untriaged, otherwise the kind's default (review for PRs,
  implement for issues, investigate for runs).
- **FR-008**: Work has GhActions for kind "work" (FR-034).
- **FR-009**: Work also offers a "Queue" view of open PRs grouped into merge sets, in
  order; approving a set asks for a merge decision (003 FR-008).
- **FR-010**: An agent session may merge a PR only under a merge decision the maintainer
  approved for that PR's current head commit (003 FR-008); every other merge is the
  maintainer's own Merge… (FR-030).

### Work item

- **FR-011**: The Work item view shows a breadcrumb (Work › repository › reference), the
  state, the title and the reference.
- **FR-012**: The view shows GhActions for the item kind next to the title.
- **FR-013**: A Details flyout shows: Part of, branch, size, author, labels, assignee,
  trigger, runner, target, repositories, updated, and changed files, as they apply to the
  kind.
- **FR-014**: A facts line shows the most important facts in one line (for example
  "+288 −31 · 4 files · 3 behind · checks passing").
- **FR-015**: A "Launch on {reference}" row shows the blue action buttons that apply to
  the kind, the best one as primary, plus "New work from this…" (opens Launch with the
  item as context).
- **FR-016**: The view shows the item body rendered as Markdown and the checks as chips.
- **FR-017**: A PR has two tabs: Conversation and Files changed.
- **FR-018**: Conversation lists review threads; each can be ticked, and "Address N
  threads…" opens Launch with the address action and those threads.
- **FR-019**: Conversation has a comment box with "Post" and "Draft with Claude", which
  opens Launch with the review action and a comment result.
- **FR-020**: Files changed lists the files with added and removed line counts; each file
  opens to its diff hunks with line numbers and the inline review notes at their lines.
- **FR-021**: A large file shows "Large file — load the diff" instead of the diff until
  asked.
- **FR-022**: A run shows the log of the failed step, with the error lines marked, and a
  link to the full log.
- **FR-023**: A "Sessions on {reference} · N" section has persona tabs, one per session,
  each showing the session as an embedded SessionView.
- **FR-024**: The section shows "N sent to background" when sessions on this item run in
  the background, with a link to each.
- **FR-025**: When no session covers the item, the section shows a suggestion interaction
  for the best action.

### GhActions (black split button)

- **FR-026**: GhActions is a black split button labelled with its main action and the
  caption "On GitHub, as {user}"; the arrow opens the other actions.
- **FR-027**: Every GhActions action runs on GitHub as the logged-in maintainer, never as
  an agent.
- **FR-028**: A disabled GhActions action stays in the menu and says why it is disabled.
- **FR-029**: Merge and Close (and Cancel run) ask for confirmation before they act.
- **FR-030**: For a PR, GhActions offers: Merge… (squash, merge commit or rebase), Mark
  ready (draft PRs only), Update branch (shows how many commits behind), Labels…,
  Close/Reopen, and Open on GitHub.
- **FR-031**: Merge… is disabled while checks are running, while the PR is not approved,
  or while review threads are open, and names which of these applies.
- **FR-032**: For an issue, GhActions offers: Close as completed, Close as not planned,
  Reopen, Labels…, Assign to me, and Open on GitHub.
- **FR-033**: For a run, GhActions offers: Re-run failed jobs, Re-run all, Cancel run,
  Download full log, and Open on GitHub.
- **FR-034**: On Work, GhActions offers "New issue…" and "Run workflow…".
- **FR-035**: New issue… asks for the repository (RepoPicker, one), title, description,
  an optional "Part of" item and labels, and offers "Let Claude write it instead", which
  opens Launch with the issue action and what was typed as the brief.
- **FR-036**: Run workflow… asks for the repository, a workflow that can be started by
  hand, a branch or tag, and the workflow's inputs with their types (choice, boolean,
  text).
- **FR-037**: When a repository has no workflow that can be started by hand, Run
  workflow… says so instead of showing an empty form.
- **FR-038**: After a GhActions action, the item view refreshes and shows the result (for
  example "Merged by {user}") within 10 seconds.

## Contracts

| Contract | Owned / consumed | Version | Spec location |
|---|---|---|---|
| Web API routes and hubd ops of this spec | Owned, internal | Unversioned; ship with the app (001) | `contracts/web-api.md`, `contracts/hubd-socket.md`, `contracts/tool-server-and-library.md`, `contracts/gh-calls.md` |
| `gh` CLI / GitHub API | Consumed (GitHub) | Installed version; not pinned | `ghpolicy.py` allowlist; this spec's calls in `contracts/gh-calls.md` |

Web API and hubd socket: [001](../001-app-frame/spec.md) Contracts; this spec's routes and
ops are in `contracts/`.

## Device scope and risk

No device risk (see [001](../001-app-frame/spec.md) Device scope and risk).

## Acceptance

Host level, in this repository (`make check`: `node --check` on the app plus `pytest`):

- Web API tests: Work groups and the row action rule FR-007.
- Policy tests: every GhActions action maps to an allowed `gh` call made as the
  maintainer; disabled reasons (FR-031).

Browser check (by hand, recorded in the PR, at 1440 px and 390 px wide; rows in
[001 quickstart](../001-app-frame/quickstart.md) §3):

- Work item tabs and diff.

Product level: none. The hub is not part of a device image.

## Out of scope

- Editing files or pushing commits by hand from the app.

## Success criteria

- **SC-001**: 100 % of GitHub actions in the app are reached through the black split
  button, and 100 % of disabled ones state a reason.

## Implementation notes

Existing code to reuse:

- `ghpolicy.py` is the fail-closed allowlist; `app/hub/github.py` has issue/PR/run
  reads, sub-issue rollups and work search.

Backend that is missing:

- GitHub: PR approval, behind count, review threads with ticks, diff hunks, failed-step
  logs, workflow inputs, and the GhActions writes made as the maintainer.
