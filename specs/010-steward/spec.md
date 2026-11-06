# Feature Specification: Steward

**Feature Branch**: `001-hub-app`
**Created**: 2026-11-06
**Status**: Draft
**Input**: "The Steward panel: the planning session beside every view, what it sees, and how the maintainer plans work with it."

## Context

- **Steward** is a side panel with a long-lived planning session that runs beside the
  maintainer, sees the view they are on and proposes work.

Depends on: App frame (001) for the phone sheet (App frame (001) FR-008), Building blocks
(002) for the Steward's badge (Building blocks (002) FR-013), Needs you (003) where the
waiting strip leads, Sessions (004) for the compact session view and typed messages
(Sessions (004) FR-008), and Launch (005), since proposed work arrives as suggestions
that open Launch.

## User Scenarios & Testing

### User Story 1 - Plan new work from the current view (Priority: P2)

The maintainer asks the Steward to plan from what they are looking at.

**Given** the maintainer is on Work with two repositories selected and the Steward panel
open
**When** they press "＋ Plan new work with the Steward", add "start with the failing runs"
and send it
**Then** the SEES chips show Work and the two repositories, the Steward receives the view's
context and the words as the maintainer's message, and the panel keeps the width it had
after a reload.

### Edge Cases

- More than three repositories are selected: the SEES chips name none of them and show a
  count, and the Steward is told the same.
- The panel is dragged past its limits: it stops at 320 or 760 px (FR-001).
- On a phone the panel is a sheet (App frame (001) FR-008).

## Requirements

Each requirement is one testable statement. A requirement of another spec is cited with
the spec's name and number, as in "App frame (001) FR-011".

### Functional Requirements

- **FR-001**: The Steward is a side panel on the right that can be resized between 320
  and 760 px; the width is remembered per viewer.
- **FR-002**: The Steward panel is open by default on Overview, Roadmap, Work and Work
  item, and collapsed by default on Sessions, Knowledge and Notes.
- **FR-003**: The Steward shows the session in a compact session view with its model and
  a model select.
- **FR-004**: SEES chips show everything the Steward is told about the current view (the
  view, the selected repositories, the open item); it is told nothing the chips do not
  show.
- **FR-005**: A waiting strip shows how many interactions from the Steward wait, and
  opens Needs you filtered to the Steward.
- **FR-006**: "＋ Plan new work with the Steward" sends the current view's context to
  the Steward as a request; the maintainer can add their own words (Sessions (004)
  FR-008).

### Key Entities

- **Steward**: the planning session beside every view; it proposes work, which the
  maintainer launches.
- **View context**: what the Steward is told about the current view: the view, the
  selected repositories (up to three by name, else a count) and the open item.

## Success Criteria

No criteria of its own; App frame (001) SC-004 (keyboard-only pass) and App frame (001)
SC-003 (phone width) apply.

## Assumptions

- The Steward is a Claude Code session the hub runs, with its own persona.
- The hub runs on the maintainer's own machine and touches no device.

## Out of scope

- The Steward's persona and preset buttons (the persona library, Building blocks (002)).
