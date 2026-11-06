# Feature Specification: Work

**Feature Branch**: `001-hub-app`
**Created**: 2026-11-06
**Status**: Draft
**Input**: "Work: the Work list (groups, row action, Queue view, the agent merge rule), the Work item (details, diff, run log, sessions on an item) and the GitHub actions button (incl. New issue and Run workflow)."

## Context

Work is where the maintainer sees the pull requests, issues and CI runs of the chosen
repositories, grouped by what they need, and turns any of them into work for an agent.

- **Work** lists pull requests, issues and runs across the chosen repositories, grouped by
  what they need, with one suggested agent action per row.
- **Work item** shows everything about one item (body, checks, conversation, diff or log,
  and the sessions on it), with agent actions and GitHub actions side by side.
- **The GitHub actions button** is a black split button. It does the GitHub actions the
  maintainer does as themselves (merge, close, label, re-run, file an issue, start a
  workflow), one click from the item and never mixed up with starting an agent.

Depends on: App frame (001), Building blocks (002), Needs you (003) for merge decisions
(Needs you (003) FR-008), Sessions (004) for the sessions on an item, and Launch (005) for
Launch, the actions and their results.

## User Scenarios & Testing

### User Story 1 - Review a pull request, then merge it yourself (Priority: P1)

The maintainer has an agent review a pull request and does the merge in person.

**Given** a pull request whose checks passed
**When** the maintainer launches "review" from the Work item, reads the resulting review
summary and inline notes and posts them, then uses the black "Merge…" split button and
confirms "squash"
**Then** the review is posted as a comment from the reviewer session's result, the pull
request is merged on GitHub as the maintainer, and no agent took the merge step.

### User Story 2 - Fix a failing CI run (Priority: P1)

The maintainer turns a failed run into a fix with two clicks.

**Given** a run in the Failed group on Work
**When** the maintainer presses the row's blue "fix" button (or "investigate" on the run
page)
**Then** the investigate result shows the cause and the smallest fix, with a button to
start a fix session; the fix session's draft pull request says "Closes …" for each covered
issue.

### User Story 3 - File an issue or start a workflow by hand (Priority: P3)

The maintainer does a small GitHub chore without leaving the hub.

**Given** the maintainer is on Work
**When** they use "New issue…" (or "Run workflow…") from the black split button and fill
in the form
**Then** the issue is created (or the workflow is started) as the maintainer. The issue
form also offers "Let Claude write it instead", which opens Launch with the issue-writer
action.

### Edge Cases

- A pull request's head moves after a merge decision was approved: no agent may merge it
  until a decision for the new head is approved (FR-010).
- The head moves while the maintainer has Merge… open: the merge does not go through on
  the new head (FR-030).
- A file's diff is very large: it loads only when asked (FR-021).
- A repository has no workflow that can be started by hand (FR-037).
- An action does not apply (a merged pull request cannot be reopened, a finished run
  cannot be cancelled): it stays in the menu, disabled, with the reason (FR-028).

## Requirements

Each requirement is one testable statement. A requirement of another spec is cited with
the spec's name and number, as in "App frame (001) FR-011".

### Functional Requirements

#### Work

- **FR-001**: Work has a repository picker (Building blocks (002)) that allows "All
  repositories" and remembers the last selection per viewer.
- **FR-002**: Work has kind tabs: PRs, Issues, Runs, each with a count for the current
  selection.
- **FR-003**: Pull requests are grouped into: Needs you, From agent sessions, Everything
  else.
- **FR-004**: Issues are grouped into: Untriaged, In sessions, Backlog.
- **FR-005**: Runs are grouped into: Failed, Running, Recent.
- **FR-006**: Each row shows the kind icon, the reference, the title, a sub-line (Part of,
  size, author or trigger, duration, age), the state badge and the session chips.
- **FR-007**: Each row has one blue action: fix if failing, address if reviewed with
  changes requested, triage if untriaged, otherwise the kind's default (review for pull
  requests, implement for issues, investigate for runs).
- **FR-008**: Work has the GitHub actions button with the Work actions (FR-034).
- **FR-009**: Work also offers a "Queue" view of open pull requests grouped into merge
  sets, in order; approving a set asks for a merge decision (Needs you (003) FR-008).
- **FR-010**: An agent session may merge a pull request only under a merge decision the
  maintainer approved for that pull request's current head commit (Needs you (003)
  FR-008); every other merge is the maintainer's own Merge… (FR-030).

#### Work item

- **FR-011**: The Work item view shows a breadcrumb (Work › repository › reference), the
  state, the title and the reference.
- **FR-012**: The view shows the GitHub actions button for the item's kind next to the
  title.
- **FR-013**: A Details flyout shows: Part of, branch, size, author, labels, assignee,
  trigger, runner, target, repositories, updated, and changed files, as they apply to the
  kind.
- **FR-014**: A facts line shows the most important facts in one line (for example
  "+288 −31 · 4 files · 3 behind · checks passing").
- **FR-015**: A "Launch on {reference}" row shows the blue action buttons that apply to
  the kind, the best one as primary, plus "New work from this…" (opens Launch with the
  item as context).
- **FR-016**: The view shows the item body rendered as Markdown and the checks as chips.
- **FR-017**: A pull request has two tabs: Conversation and Files changed.
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
  each showing that session's view embedded (Sessions (004)).
- **FR-024**: The section shows "N sent to background" when sessions on this item run in
  the background, with a link to each.
- **FR-025**: When no session covers the item, the section shows a suggestion for the
  best action.

#### The GitHub actions button (black split button)

- **FR-026**: The GitHub actions button is a black split button labelled with its main
  action and the caption "On GitHub, as {user}"; the arrow opens the other actions.
- **FR-027**: Every action of the GitHub actions button runs on GitHub as the
  maintainer's own GitHub login, never as a session or a persona's GitHub App, and only
  on the organization's repositories.
- **FR-028**: A disabled action stays in the menu and says why it is disabled.
- **FR-029**: Merge and Close (and Cancel run) ask for confirmation before they act.
- **FR-030**: For a pull request, the button offers: Merge… (squash, merge commit or
  rebase), Mark ready (draft pull requests only), Update branch (shows how many commits
  behind), Labels…, Close/Reopen, and Open on GitHub. Merge… merges only the head commit
  the maintainer saw. Editing a pull request from the hub changes only its labels.
- **FR-031**: Merge… is disabled while checks are running, while the pull request is not
  approved, or while review threads are open, and names which of these applies.
- **FR-032**: For an issue, the button offers: Close as completed, Close as not planned,
  Reopen, Labels…, Assign to me, and Open on GitHub. Assign to me adds only the
  maintainer and removes no one.
- **FR-033**: For a run, the button offers: Re-run failed jobs, Re-run all, Cancel run,
  Download full log, and Open on GitHub.
- **FR-034**: On Work, the button offers "New issue…" and "Run workflow…".
- **FR-035**: New issue… asks for the repository (one), title, description, an optional
  "Part of" item and labels, and offers "Let Claude write it instead", which opens Launch
  with the issue action and what was typed as the brief.
- **FR-036**: Run workflow… asks for the repository, a workflow that can be started by
  hand, a branch or tag, and the workflow's inputs with their types (choice, boolean,
  text). Inputs are sent as typed; the hub never fills them from files on the
  maintainer's machine.
- **FR-037**: When a repository has no workflow that can be started by hand, Run
  workflow… says so instead of showing an empty form.
- **FR-038**: After an action of the button, the item view refreshes and shows the result
  (for example "Merged by {user}") within 10 seconds.

### Key Entities

- **Work item**: a pull request, issue or CI run in one of the organization's
  repositories, with its state, group and suggested action.
- **Merge set**: an ordered group of open pull requests in the Queue view, approved
  together.
- **Merge decision**: the maintainer's approval for one pull request at one head commit
  (Needs you (003)).
- **GitHub action**: a step on GitHub that the maintainer takes as themselves through the
  black split button.

## Success Criteria

- **SC-001**: 100 % of GitHub actions in the hub are reached through the black split
  button, and 100 % of disabled ones state a reason.

## Assumptions

- GitHub provides the reviews, review threads, checks, run logs, labels, branch
  protection and manually started workflows this view shows.
- The hub runs on the maintainer's own machine and touches no device.

## Out of scope

- Editing files or pushing commits by hand from the hub.
