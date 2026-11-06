# Feature Specification: Knowledge

**Feature Branch**: `001-hub-app`
**Created**: 2026-11-06
**Status**: Draft
**Input**: "Knowledge: search across docs, work items and code, research when search is not enough, research reports and the indexes."

## Context

- **Knowledge** makes the docs, work items and code of GlassineOS findable, and starts
  research when search is not enough. A research session ends with a report that is kept,
  listed and can be followed up.

Depends on: App frame (001), Building blocks (002) for the repository picker and session
chips, Needs you (003) where reports arrive in Results ready, and Launch (005) for the
research action and the report result.

## User Scenarios & Testing

### User Story 1 - Research a question (Priority: P2)

The maintainer asks a question the docs do not answer and gets a kept report.

**Given** a Knowledge search for "why LUT version 3" returns no good hits
**When** the maintainer pins two passages, presses "Research this…" and plans a research
session
**Then** the session ends with a report (answer, what could not be settled, sources,
follow-ups); the report lands in Needs you › Results ready and can be saved; Knowledge
lists it under reports, where it can be opened or followed up. The research session
posts nothing on GitHub.

### Edge Cases

- A domain is not indexed yet (today: Code): it shows as "planned" and cannot be chosen
  (FR-002).
- An index is stale or being rebuilt: the flyout shows its state and age (FR-009).
- The search box is empty: "Try" chips offer example searches (FR-005).
- A search finds nothing good: Knowledge offers research instead of an empty page
  (FR-006).

## Requirements

Each requirement is one testable statement. A requirement of another spec is cited with
the spec's name and number, as in "App frame (001) FR-011".

### Functional Requirements

- **FR-001**: Knowledge has a search box with a meaning / exact switch.
- **FR-002**: Knowledge searches three domains: Docs, Work items and Code; a domain that
  is not indexed yet is shown as "planned" and cannot be chosen.
- **FR-003**: Knowledge has a repository picker (many), an "Open only" switch for work
  items, and a ranked or grouped-by-repository layout.
- **FR-004**: A result card shows the kind, the title, the score, a snippet with the
  matched words marked, session chips (for work items), "Open" and "Pin as context".
- **FR-005**: "Try" chips offer example searches when the box is empty.
- **FR-006**: When a search has no good hits, Knowledge offers to research the question.
- **FR-007**: "Research this…" (with the number of pins) opens a flyout with the research
  question, the scope, the pins and "Plan a research session…" (Launch, research action).
  A research session does not need a repository.
- **FR-008**: The flyout lists earlier research reports; each can be opened or followed up
  (Launch with the report as context).
- **FR-009**: The flyout shows each index with its state and age: Docs ("Run docs CI
  now"), Work items ("Ingest now"), Code (planned).
- **FR-010**: Searches and research scopes stay inside what the maintainer may see on
  GitHub; Knowledge shows nothing from a repository the maintainer cannot read.

### Key Entities

- **Domain**: a kind of thing Knowledge searches (Docs, Work items, Code), with an index
  state: ready, indexing, planned or failed.
- **Result**: one hit, with kind, title, score, marked snippet and a link.
- **Pin**: a result the maintainer keeps as context for research.
- **Research report**: the kept result of a research session: answer, open points,
  sources, follow-ups.

## Success Criteria

No criteria of its own; App frame (001) SC-004 (keyboard-only pass) and App frame (001)
SC-003 (phone width) apply.

## Assumptions

- A GlassineOS search service indexes the docs and the work items; Knowledge reads it.
  Code is not indexed yet.
- A research session is read-only: it hands in a report and posts nothing (Launch (005)).
- The hub runs on the maintainer's own machine and touches no device.

## Out of scope

- Code search as a working domain in Knowledge (shown as planned until the code index
  exists).
