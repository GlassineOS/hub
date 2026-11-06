# Feature Specification: Launch

**Feature Branch**: `001-hub-app`
**Created**: 2026-11-06
**Status**: Draft
**Input**: "Launch: the stages from brief to result, the record kept of every Launch, the action table and the result types with what applying each one does."

## Context

Launch turns any work item into work for an agent in a few steps, with a visible plan and
a known kind of result. This spec defines the five stages of Launch, the record kept of
every Launch, the action table (which persona does what, with which result and ceiling),
and the result types with what applying each one does.

It uses App frame (001), the item pill, item picker, repository picker and action metadata
(Building blocks, 002), suggestions and results as interactions (Needs you, 003) and the
compact session view with covers and origin (Sessions, 004). Launch is opened from Work
and Work item (006), Roadmap (007), Knowledge (008), Notes (009) and the Steward (010).

### Views

- **Launch**: turns a brief into a planned, running agent session with a known result.

## User Scenarios & Testing

### User Story 1 - Launch an implementer on two issues from a suggestion (Priority: P1)

The maintainer takes a Steward suggestion and starts one session on two issues.

**Why this priority**: Starting agents on work is what the hub is for.

**Independent Test**: Post a suggestion covering two issues, open it and go through all
five stages to Start.

**Acceptance Scenarios**:

1. **Given** the Steward has posted a suggestion "implement kernel#204 and kernel#219
   together", **When** the maintainer opens it from Needs you, checks the brief, picks
   the planner model, reads the plan and presses "Start", **Then** an Engineer session
   runs that covers both issues; both items show its session chip; the session is embedded
   in the view it was started from; and the suggestion card shows "started".

### Edge Cases

- The action's ceiling forbids the item kind (for example "implement" on a run): Launch
  refuses and says why.
- The covered items span repositories: the worktree is in the first item's repository,
  and the others are listed as covered.
- The maintainer leaves Launch after planning: it goes on in the background, and its asks
  and result arrive in Needs you.

## Requirements

Each requirement is one testable statement. A requirement of another spec is cited with
that spec's name and number, as in "App frame (001) FR-011".

### Functional Requirements

#### Launch stages and records

- **FR-001**: Launch can be opened from the header ("＋ New work"), a Work row, a Work
  item, a suggestion, Roadmap, Knowledge or Notes, prefilled with the action and items of
  that place.
- **FR-002**: Launch goes through five stages: brief, planning, plan, run, result. The
  current stage is always visible.
- **FR-003**: The brief stage shows the action, the persona, the covered items (item pills,
  added with the item picker), the repositories (repository picker), the model and an optional
  note.
- **FR-004**: The brief stage shows the action's result type and ceiling in plain words
  ("ends with a draft PR", "read-only, posts a comment").
- **FR-005**: The planning stage runs a planner on a chosen planner model (Opus, Sonnet or
  Haiku) and shows its progress.
- **FR-006**: The plan stage shows the planned steps and the files or items each step
  touches; the maintainer can edit the brief and plan again, or start.
- **FR-007**: The run stage shows the session in a compact session view with its inline
  asks.
- **FR-008**: At any stage after planning, Launch can be sent to the background; a toast
  confirms it and links to the session, and later asks and the result arrive in Needs
  you.
- **FR-009**: A covered item list may span repositories; the session's worktree is created
  in the repository of the first item, and the others are listed as covered.
- **FR-010**: Every Launch is recorded (who, when, from where, action, items, model,
  plan) and the record is shown as the session's origin.
- **FR-011**: Launch refuses to start when an action's ceiling forbids the item kind (for
  example "implement" on a run) and says why.

#### Actions and result types

- **FR-012**: The action library has these actions, each with a fixed persona, result
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

- **FR-013**: Each action has a default model (Fable, Opus, Sonnet or Haiku) that the
  brief can change.
- **FR-014**: An action's ceiling (read-only, comment, branch + draft PR) is enforced by
  the session's permissions, not only shown.
- **FR-015**: A drafts result lists draft issues; each can be filed as is, edited and
  filed, or sent to the Steward.
- **FR-016**: A pr result is a draft pull request whose body says "Closes …" for each
  covered issue, with a link to it; for address, it is new commits on that pull request's
  branch only.
- **FR-017**: A comment result shows the review summary and the inline notes and posts
  them on "Post", as a review comment on the pull request.
- **FR-018**: A labels result shows the proposed labels and "Part of" lines per issue and
  applies them on "Apply".
- **FR-019**: A findings result shows the cause and the smallest fix, and offers "Start a
  fix session" (opens Launch with fix prefilled).
- **FR-020**: A report result shows the answer, what could not be settled, the sources,
  and follow-ups; it can be saved to Knowledge.
- **FR-021**: A notes result lists note operations (merge, distil, answer, supersede,
  status, retract, flag), each with the exact command it will run; the operations can be
  applied one by one or all, and none of them deletes a note.

### Key Entities

- **Brief**: what the maintainer asks for: action, persona, covered items, repositories,
  model and note.
- **Plan**: the planned steps and what each one touches.
- **Launch record**: who started it, when, from where, the action, items, model and plan.
- **Result**: what a session ends with; one of drafts, pr, comment, labels, findings,
  report or notes.

## Success Criteria

### Measurable Outcomes

- **SC-001**: From a Work row or suggestion, a session can be started in at most 4 steps
  (open Launch, plan, read plan, start).

## Assumptions

- The GitHub actions the maintainer does as themselves (merge, close, label, re-run) are
  in Work (006) and are never a Launch.
- The way running sessions reach the hub (to report results, ask and suggest) is an owned
  interface: a change to it keeps sessions that are already running working.
- The models offered are the Claude models available to the maintainer's account.
- Draft pull requests, review comments, labels and filed issues are GitHub's own objects.
