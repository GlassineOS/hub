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

Depends on: [001](../001-app-frame/spec.md), [002](../002-building-blocks/spec.md)
(ItemPill, ItemPicker, RepoPicker, action metadata), [003](../003-needs-you/spec.md)
(suggestions and results arrive as interactions) and [004](../004-sessions/spec.md) (the
run stage shows a compact SessionView; sessions carry their covers and origin). Launch is
opened from Work and Work item ([006](../006-work/spec.md)), Roadmap
([007](../007-overview-roadmap/spec.md)), Knowledge ([008](../008-knowledge/spec.md)),
Notes ([009](../009-notes/spec.md)) and the Steward ([010](../010-steward/spec.md)).

## Views

- **Launch**: turns a brief into a planned, running agent session with a known result.

## User scenarios

### Scenario 1 – Launch an implementer on two issues from a suggestion (Priority: P1)

**Given** the Steward has posted a suggestion "implement kernel#204 and kernel#219
together"
**When** the maintainer opens it from Needs you, checks the brief, picks the planner model,
reads the plan and presses "Start"
**Then** an Engineer session runs that covers both issues; both items show its
SessionChip; the session is embedded in the view it was started from; and the suggestion
card shows "started".

## Requirements

Requirements are one testable statement each. A requirement of another spec is written with
that spec's number first, as in `001 FR-011`.

### Launch stages and records

- **FR-001**: Launch can be opened from the header ("＋ New work"), a Work row, a Work
  item, a suggestion, Roadmap, Knowledge or Notes, prefilled with the action and items of
  that place.
- **FR-002**: Launch goes through five stages: brief, planning, plan, run, result. The
  current stage is always visible.
- **FR-003**: The brief stage shows the action, the persona, the covered items (ItemPills,
  added with the ItemPicker), the repositories (RepoPicker), the model and an optional
  note.
- **FR-004**: The brief stage shows the action's result type and ceiling in plain words
  ("ends with a draft PR", "read-only, posts a comment").
- **FR-005**: The planning stage runs a planner on a chosen planner model (Opus, Sonnet or
  Haiku) and shows its progress.
- **FR-006**: The plan stage shows the planned steps and the files or items each step
  touches; the maintainer can edit the brief and plan again, or start.
- **FR-007**: The run stage shows the session in a compact SessionView with its inline
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

### Actions and result types

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
- **FR-016**: A pr result is a draft PR whose body says "Closes …" for each covered issue,
  with a link to it; for address, it is new commits on that PR's branch only.
- **FR-017**: A comment result shows the review summary and the inline notes and posts
  them on "Post", as a review comment on the PR.
- **FR-018**: A labels result shows the proposed labels and "Part of" lines per issue and
  applies them on "Apply".
- **FR-019**: A findings result shows the cause and the smallest fix, and offers "Start a
  fix session" (opens Launch with fix prefilled).
- **FR-020**: A report result shows the answer, what could not be settled, the sources,
  and follow-ups; it can be saved to Knowledge.
- **FR-021**: A notes result lists note operations (merge, distil, answer, supersede,
  status, retract, flag), each with its exact `notes` command; the operations can be
  applied one by one or all, and none of them deletes a note.

## Contracts

| Contract | Owned / consumed | Version | Spec location |
|---|---|---|---|
| Web API routes and hubd ops of this spec | Owned, internal | Unversioned; ship with the app (001) | `contracts/web-api.md`, `contracts/hubd-socket.md`, `contracts/tool-server-and-library.md`, `contracts/gh-calls.md` |
| Tool server tools (MCP, used by running sessions) | Owned | Not versioned; changes must stay safe for sessions already running | `app/hub/tools.py`, `docs/orchestrator.md`; this spec's changes in `contracts/tool-server-and-library.md` |

Web API and hubd socket: [001](../001-app-frame/spec.md) Contracts; this spec's routes and
ops are in `contracts/`. New or changed owned surfaces this spec needs: Launch records and
typed results (`submit_result`, `result.*`).

## Device scope and risk

No device risk (see [001](../001-app-frame/spec.md) Device scope and risk).

## Acceptance

Host level, in this repository (`make check`: `node --check` on the app plus `pytest`):

- hubd tests with the fake Claude CLI: Launch stages and records, covers across
  repositories, background hand-off, results per type.
- Tool server tests: the new tools and the changed ones keep working for a session
  started before the change.

Browser check (by hand, recorded in the PR, at 1440 px and 390 px wide; rows in
[001 quickstart](../001-app-frame/quickstart.md) §3):

- Launch through all five stages.

Product level: none. The hub is not part of a device image.

## Out of scope

- GitHub actions the maintainer does as themselves (merge, close, label, re-run): they are
  GhActions ([006](../006-work/spec.md)), never a Launch.

## Success criteria

- **SC-001**: From a Work row or suggestion, a session can be started in at most 4 steps
  (open Launch, plan, read plan, start).

## Implementation notes

Backend that is missing:

- Launch records (FR-010) and the planning and plan stages as hubd state.
