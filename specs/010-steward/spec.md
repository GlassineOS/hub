# Feature Specification: Steward

**Feature Branch**: `001-hub-app`
**Created**: 2026-11-06
**Status**: Draft
**Input**: "The Steward panel: the planning session beside every view, what it sees, and how the maintainer plans work with it."

## Context

The Steward is a long-lived planning session that runs beside the maintainer, sees the
view they are on and proposes work. This spec defines the Steward panel.

Depends on: [001](../001-app-frame/spec.md) (the phone sheet 001 FR-008),
[002](../002-building-blocks/spec.md) (the Steward's badge 002 FR-013),
[003](../003-needs-you/spec.md) (the waiting strip opens Needs you),
[004](../004-sessions/spec.md) (the compact SessionView and typed messages 004 FR-008) and
[005](../005-launch/spec.md) (proposed work arrives as suggestions that open Launch).

## Views

- **Steward**: a side panel with the planning session that sees the current view and
  proposes work.

## User scenarios

### Scenario 1 – Plan new work from the current view (Priority: P2)

**Given** the maintainer is on Work with two repositories selected and the Steward panel
open
**When** they press "＋ Plan new work with the Steward", add "start with the failing runs"
and send it
**Then** the SEES chips show Work and the two repositories, the Steward receives the view's
context and the words as the maintainer's message, and the panel keeps the width it had
after a reload.

## Requirements

Requirements are one testable statement each. A requirement of another spec is written with
that spec's number first, as in `001 FR-011`.

### Steward panel

- **FR-001**: The Steward is a side panel on the right that can be resized between 320
  and 760 px; the width is remembered per viewer.
- **FR-002**: The Steward panel is open by default on Overview, Roadmap, Work and Work
  item, and collapsed by default on Sessions, Knowledge and Notes.
- **FR-003**: The Steward shows the session in a compact SessionView with its model and a
  model select.
- **FR-004**: SEES chips show what the Steward is told about the current view (the view,
  the selected repositories, the open item).
- **FR-005**: A waiting strip shows how many interactions from the Steward wait, and
  opens Needs you filtered to the Steward.
- **FR-006**: "＋ Plan new work with the Steward" sends the current view's context to
  the Steward as a request; the maintainer can add their own words (004 FR-008).

## Contracts

| Contract | Owned / consumed | Version | Spec location |
|---|---|---|---|
| Web API routes and hubd ops of this spec | Owned, internal | Unversioned; ship with the app (001) | `contracts/hubd-socket.md` |

Web API and hubd socket: [001](../001-app-frame/spec.md) Contracts; this spec's op is in
`contracts/hubd-socket.md`.

## Device scope and risk

No device risk (see [001](../001-app-frame/spec.md) Device scope and risk).

## Acceptance

Host level, in this repository (`make check`: `node --check` on the app plus `pytest`):

- Tests as PR 1 lists: default open or closed per view; `set_context` validates and caps `repos`.

Browser check (by hand, recorded in the PR, at 1440 px and 390 px wide; rows in
[001 quickstart](../001-app-frame/quickstart.md) §3):

- Steward resize and collapse defaults.

Product level: none. The hub is not part of a device image.

## Out of scope

- The Steward's persona and preset buttons (the persona library, [002](../002-building-blocks/spec.md)).

## Success criteria

No criteria of its own; 001 SC-004 (keyboard-only pass) and 001 SC-003 (phone width) apply.

## Implementation notes

Existing code to reuse:

- The web app has a Steward panel (`Steward`, `StewardSession`, `StewardModel`, `keptRail`
  in `app/hub/static/app.js`); this spec's PR reshapes it on the compact SessionView.
