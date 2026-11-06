# Feature Specification: Knowledge

**Feature Branch**: `001-hub-app`
**Created**: 2026-11-06
**Status**: Draft
**Input**: "Knowledge: search across docs, work items and code, research when search is not enough, research reports and the indexes."

## Context

Knowledge makes the docs, work items and code of GlassineOS findable, and starts research
when search is not enough. A research session ends with a report that is kept, listed and
can be followed up.

Depends on: [001](../001-app-frame/spec.md), [002](../002-building-blocks/spec.md)
(RepoPicker, SessionChip), [003](../003-needs-you/spec.md) (reports arrive in Results
ready) and [005](../005-launch/spec.md) (the research action and the report result).

## Views

- **Knowledge**: searches docs, work items and code, and starts research when search is
  not enough.

## User scenarios

### Scenario 1 – Research a question (Priority: P2)

**Given** a Knowledge search for "why LUT version 3" returns no good hits
**When** the maintainer pins two passages, presses "Research this…" and plans a research
session
**Then** the session ends with a report (answer, what could not be settled, sources,
follow-ups); the report lands in Needs you › Results ready and can be saved; Knowledge
lists it under reports, where it can be opened or followed up.

## Requirements

Requirements are one testable statement each. A requirement of another spec is written with
that spec's number first, as in `001 FR-011`.

### Knowledge

- **FR-001**: Knowledge has a search box with a meaning / exact switch.
- **FR-002**: Knowledge searches three domains: Docs, Work items and Code; a domain that
  is not indexed yet is shown as "planned" and cannot be chosen.
- **FR-003**: Knowledge has a RepoPicker (many), an "Open only" switch for work items, and
  a ranked or grouped-by-repository layout.
- **FR-004**: A result card shows the kind, the title, the score, a snippet with the
  matched words marked, SessionChips (for work items), "Open" and "Pin as context".
- **FR-005**: "Try" chips offer example searches when the box is empty.
- **FR-006**: When a search has no good hits, Knowledge offers to research the question.
- **FR-007**: "Research this…" (with the number of pins) opens a flyout with the research
  question, the scope, the pins and "Plan a research session…" (Launch, research action).
- **FR-008**: The flyout lists earlier research reports; each can be opened or followed up
  (Launch with the report as context).
- **FR-009**: The flyout shows each index with its state and age: Docs ("Run docs CI
  now"), Work items ("Ingest now"), Code (planned).

## Contracts

| Contract | Owned / consumed | Version | Spec location |
|---|---|---|---|
| Web API routes and hubd ops of this spec | Owned, internal | Unversioned; ship with the app (001) | `contracts/web-api.md`, `contracts/tool-server-and-library.md` |
| Search index (docs, work items) | Consumed (GlassineOS search) | As deployed | search repository |

Web API and hubd socket: [001](../001-app-frame/spec.md) Contracts; this spec's routes and
its new action are in `contracts/`. New or changed owned surfaces this spec needs: the research
action.

## Device scope and risk

No device risk (see [001](../001-app-frame/spec.md) Device scope and risk).

## Acceptance

Host level, in this repository (`make check`: `node --check` on the app plus `pytest`):

- Tests as PR 1 lists: the research action validates with no repository, the report
  payload shape, the merged search marks matches, a planned domain can't be requested.

Browser check (by hand, recorded in the PR, at 1440 px and 390 px wide; rows in
[001 quickstart](../001-app-frame/quickstart.md) §3):

- Knowledge as in the quickstart row "After 008/PR 1".

Product level: none. The hub is not part of a device image.

## Out of scope

- Code search as a working domain in Knowledge (shown as planned until the code index
  exists).

## Success criteria

No criteria of its own; 001 SC-004 (keyboard-only pass) and 001 SC-003 (phone width) apply.

## Implementation notes

Backend that is missing:

- Action `research` (report result).
- Knowledge: search across domains with pins, research reports stored and listed, index
  state and the "Ingest now" / "Run docs CI now" triggers.
