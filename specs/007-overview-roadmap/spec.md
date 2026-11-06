# Feature Specification: Overview and Roadmap

**Feature Branch**: `001-hub-app`
**Created**: 2026-11-06
**Status**: Draft
**Input**: "Overview (repositories by attention, Needs-you card, device lock state) and Roadmap (columns by stage, Part-of progress)."

## Context

Overview and Roadmap are the two views that show the whole of GlassineOS at once. Overview
shows the state of every repository, sorted by what needs attention, and who holds the
device. Roadmap shows planned work across repositories by stage, with progress taken from
the issues linked to each item.

Depends on: [001](../001-app-frame/spec.md) (scale rule 001 FR-019), [002](../002-building-blocks/spec.md),
[003](../003-needs-you/spec.md) (the Needs-you counts) and [005](../005-launch/spec.md)
(Launch with the road action).

## Views

- **Overview**: shows the state of every repository at a glance, sorted by what needs
  attention, plus who holds the device.
- **Roadmap**: shows planned work across repositories as columns by stage, with progress
  taken from linked issues.

## User scenarios

### Scenario 1 – See what needs attention across all repositories (Priority: P2)

**Given** 60 repositories in four layers, a failing run and a waiting session in `kernel`,
and a session that holds the device lock under a Go
**When** the maintainer opens Overview
**Then** the Needs-you card shows the count, the breakdown by kind and the longest wait;
`kernel` is first in its layer; each layer shows 5 repositories, then "Show N more"; and the
device card says who holds the lock, since when, and for which Go.

### Scenario 2 – Follow a roadmap item's progress (Priority: P3)

**Given** a roadmap item `hub#40` in progress with three `kernel` issues that are "Part of"
it, one of them closed
**When** the maintainer opens Roadmap
**Then** the card is in the In progress column with a `kernel` progress bar that says 1 of 3
done in words, and "Plan issues…" opens Launch with the road action on that item.

## Requirements

Requirements are one testable statement each. A requirement of another spec is written with
that spec's number first, as in `001 FR-011`.

### Overview

- **FR-001**: Overview shows a Needs-you card with the count, the breakdown by kind, and
  the longest wait; it opens Needs you.
- **FR-002**: Overview shows four stats: running sessions, open issues, open PRs (with
  how many fail), and Knowledge (indexed documents).
- **FR-003**: Overview shows the device lock state: free, or held by whom (session or
  maintainer) since when, and for which Go if any.
- **FR-004**: Overview lists the repositories grouped by layer, each layer sorted by
  attention (failing runs, waiting sessions, open PRs, then recent activity).
- **FR-005**: Each layer shows 5 repositories, then "Show N more".
- **FR-006**: Overview has a text filter, a "Needs attention only" switch, and "Collapse
  all" / "Expand all".
- **FR-007**: Each repository row shows the strip of recent CI runs, the last commit, the
  time of the last activity, the sessions on it (SessionChips) and "Launch…".
- **FR-008**: Repositories not assigned to a layer are listed on an "Unplaced" line.

### Roadmap

- **FR-009**: Roadmap shows roadmap items in four columns: Planned, In progress, In review,
  Done.
- **FR-010**: A roadmap card shows the reference and target, the title, a progress bar per
  repository computed from the issues that are "Part of" it, who works on it, and its
  SessionChips.
- **FR-011**: A roadmap card offers "Plan issues…", which opens Launch with the road
  action on that item.
- **FR-012**: Opening a roadmap card shows the Work item view for it, with the actions
  road and docs.

## Contracts

| Contract | Owned / consumed | Version | Spec location |
|---|---|---|---|
| Web API routes and hubd ops of this spec | Owned, internal | Unversioned; ship with the app (001) | `contracts/web-api.md` |

Web API and hubd socket: [001](../001-app-frame/spec.md) Contracts; this spec's routes are
in `contracts/web-api.md`.

## Device scope and risk

No device risk. Overview shows the device lock state as data reported by the lock and
sessions; it never takes the lock (see [001](../001-app-frame/spec.md) Device scope and
risk).

## Acceptance

Host level, in this repository (`make check`: `node --check` on the app plus `pytest`):

- Web API tests: Overview attention order and "Show N more"; Roadmap progress from
  Part-of.

Browser check (by hand, recorded in the PR, at 1440 px and 390 px wide; rows in
[001 quickstart](../001-app-frame/quickstart.md) §3):

- Overview and Roadmap as in the quickstart rows "After 007/PR 1" and "After 007/PR 2".

Product level: none. The hub is not part of a device image.

## Out of scope

- A device page or device control panel.

## Success criteria

Overview is held to 001 SC-002 (first screen in under 2 seconds with 60 repositories and 500 open items); this spec has no criteria of its own.

## Implementation notes

Backend that is missing:

- Roadmap progress per repository from "Part of" (issue fields have no Part-of today; the
  sub-issue rollup can feed it).
- Device lock state for Overview (read only).
