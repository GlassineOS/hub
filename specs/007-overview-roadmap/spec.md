# Feature Specification: Overview and Roadmap

**Feature Branch**: `001-hub-app`
**Created**: 2026-11-06
**Status**: Draft
**Input**: "Overview (repositories by attention, Needs-you card, device lock state) and Roadmap (columns by stage, Part-of progress)."

## Context

Overview and Roadmap are the two views that show the whole of GlassineOS at once.

- **Overview** shows the state of every repository at a glance, sorted by what needs
  attention, plus who holds the device.
- **Roadmap** shows planned work across repositories as columns by stage, with progress
  taken from the issues linked to each item.

Depends on: App frame (001) (the scale rule, App frame (001) FR-019), Building blocks
(002), Needs you (003) for the Needs-you counts, and Launch (005) for Launch with the road
action.

## User Scenarios & Testing

### User Story 1 - See what needs attention across all repositories (Priority: P2)

The maintainer opens one page and knows where to look first.

**Given** 60 repositories in four layers, a failing run and a waiting session in `kernel`,
and a session that holds the device lock under a Go
**When** the maintainer opens Overview
**Then** the Needs-you card shows the count, the breakdown by kind and the longest wait;
`kernel` is first in its layer; each layer shows 5 repositories, then "Show N more"; and the
device card says who holds the lock, since when, and for which Go.

### User Story 2 - Follow a roadmap item's progress (Priority: P3)

The maintainer sees how far a planned item has come in each repository.

**Given** a roadmap item `hub#40` in progress with three `kernel` issues that are "Part of"
it, one of them closed
**When** the maintainer opens Roadmap
**Then** the card is in the In progress column with a `kernel` progress bar that says 1 of 3
done in words, and "Plan issues…" opens Launch with the road action on that item.

### Edge Cases

- A repository belongs to no layer: it is listed on the "Unplaced" line (FR-008).
- A layer has 5 or fewer repositories: no "Show N more" appears.
- Nobody holds the device: the device card says "free".

## Requirements

Each requirement is one testable statement. A requirement of another spec is cited with
the spec's name and number, as in "App frame (001) FR-011".

### Functional Requirements

#### Overview

- **FR-001**: Overview shows a Needs-you card with the count, the breakdown by kind, and
  the longest wait; it opens Needs you.
- **FR-002**: Overview shows four stats: running sessions, open issues, open pull requests
  (with how many fail), and Knowledge (indexed documents).
- **FR-003**: Overview shows the device lock state: free, or held by whom (session or
  maintainer) since when, and for which Go if any. Overview only shows the lock; it never
  takes or releases it.
- **FR-004**: Overview lists the repositories grouped by layer, each layer sorted by
  attention (failing runs, waiting sessions, open pull requests, then recent activity).
- **FR-005**: Each layer shows 5 repositories, then "Show N more".
- **FR-006**: Overview has a text filter, a "Needs attention only" switch, and "Collapse
  all" / "Expand all".
- **FR-007**: Each repository row shows the strip of recent CI runs, the last commit, the
  time of the last activity, the sessions on it (session chips) and "Launch…".
- **FR-008**: Repositories not assigned to a layer are listed on an "Unplaced" line.

#### Roadmap

- **FR-009**: Roadmap shows roadmap items in four columns: Planned, In progress, In review,
  Done.
- **FR-010**: A roadmap card shows the reference and target, the title, a progress bar per
  repository computed from the issues that are "Part of" it, who works on it, and its
  session chips.
- **FR-011**: A roadmap card offers "Plan issues…", which opens Launch with the road
  action on that item.
- **FR-012**: Opening a roadmap card shows the Work item view for it (Work (006)), with
  the actions road and docs.

### Key Entities

- **Layer**: a named group of repositories; a repository is in one layer or unplaced.
- **Roadmap item**: an issue that plans work across repositories, with a stage and a
  target.
- **Part of**: the link from an issue to the roadmap item it belongs to; progress counts
  the closed ones.
- **Device lock**: who may use the shared device right now, and under which Go.

## Success Criteria

Overview is held to App frame (001) SC-002 (first screen in under 2 seconds with 60
repositories and 500 open items); this spec has no criteria of its own.

## Assumptions

- GitHub issues can be linked as "Part of" a parent issue; Roadmap progress comes from
  those links.
- The device lock state is reported by the lock and the sessions; the hub reads it only.
- The hub runs on the maintainer's own machine and touches no device.

## Out of scope

- A device page or device control panel.
