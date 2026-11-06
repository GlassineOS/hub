# Feature Specification: Building blocks

**Feature Branch**: `001-hub-app`
**Created**: 2026-11-06
**Status**: Draft
**Input**: "The building blocks every hub view uses: item references and ItemPill, ItemPicker and RepoPicker, PersonaBadge with persona families and action metadata, and SessionChip."

## Context

Four building blocks recur everywhere in the hub:

- **Item**: an issue, PR, CI run or roadmap item, written `repo#N` or `workflow #N`.
- **Launch**: the path from "I want an agent on this" to a running session
  ([005](../005-launch/spec.md)).
- **Session**: a Claude Code (or plain shell) process with a persona, covered items and a
  terminal ([004](../004-sessions/spec.md)).
- **Interaction**: anything a session or the hub needs from the maintainer
  ([003](../003-needs-you/spec.md)).

This spec defines the small pieces every view uses to show them: the item reference and the
ItemPill, the ItemPicker and RepoPicker, the PersonaBadge with the persona families, the
action metadata (each action's short name and result type) and the SessionChip.

Depends on: [001](../001-app-frame/spec.md) (colour and outline meanings 001 FR-011–FR-014,
accessibility 001 FR-015–FR-017, scale 001 FR-019).

## Blocks

- **ItemPill**: names one item by its stable reference, shows its state, and opens it.
- **ItemPicker / RepoPicker**: choose items and repositories by typing, at any number of
  repositories.
- **PersonaBadge**: tells at a glance which persona, and which family of work, a session
  is.
- **Action metadata**: gives each action a short name (its verb) and the kind of result it
  ends with, so Launch and Work rows can say it in plain words. The action table itself is
  005 FR-012.
- **SessionChip**: shows a session wherever its items are shown, and whether it waits for
  the maintainer.

## User scenarios

### Scenario 1 – Pick items and repositories by keyboard (Priority: P2)

**Given** the maintainer is in a Launch brief with no covered items
**When** they type "204" in the ItemPicker, move to `kernel#204` with the arrow keys and
press Enter, then open the RepoPicker, type a filter and choose five repositories
**Then** `kernel#204` shows as a removable ItemPill with its state by outline and icon, the
repository selection shows as "5 repos" (not five pills), and no step needed a mouse.

## Requirements

Requirements are one testable statement each. A requirement of another spec is written with
that spec's number first, as in `001 FR-011`.

### Item reference and ItemPill

- **FR-001**: Every item is referred to by a stable reference: `repo#N` for issues and
  PRs, `workflow #N` for runs, and the roadmap item reference for roadmap items.
- **FR-002**: An ItemPill shows the item kind icon, the reference and (when there is room)
  the title, and opens the Work item view when activated.
- **FR-003**: An ItemPill shows the item's state (open, draft, merged, closed, failing,
  running) by its outline and icon, never by a background colour.
- **FR-004**: An ItemPill can be removable (shows a remove control) where it stands for a
  selection, such as a Launch brief's covered items.

### ItemPicker and RepoPicker

- **FR-005**: The RepoPicker lets the user pick one or many repositories by typing a
  filter, and offers "All repositories" where a view allows it.
- **FR-006**: The RepoPicker shows recent and pinned repositories first, then the rest
  grouped by layer.
- **FR-007**: No view shows all repositories as pills or chips at once (scale rule). A
  selection of more than 3 repositories is shown as a count ("5 repos") that opens the
  picker.
- **FR-008**: The ItemPicker finds items by reference or by words in the title, across
  the selected repositories, and returns one or many items.
- **FR-009**: The ItemPicker shows each candidate as an ItemPill with its state and
  repository.
- **FR-010**: Both pickers can be used fully by keyboard (type, arrows, Enter, Esc).

### PersonaBadge and persona families

- **FR-011**: Every persona belongs to exactly one family: build, review, investigate,
  write or organise.
- **FR-012**: A PersonaBadge shows the persona's initials on its family tint (build
  #d6e2ff, review #eadcff, investigate #ffd9b8, write #d4efdc, organise #e2e2e2), with
  the persona name as its accessible label.
- **FR-013**: The Steward's badge is a pen-blue "S" and is never used for another
  persona.
- **FR-014**: A plain shell has its own badge that is not a persona family.
- **FR-015**: A family legend is available wherever badges appear in a list (Sessions ›
  Running).

### SessionChip

- **FR-016**: A SessionChip shows a session's PersonaBadge, a short name and its state
  (RUNNING, WAITING, DONE, ATTACHED).
- **FR-017**: A SessionChip for a session that waits for the maintainer is marked yellow
  and says how many things wait.
- **FR-018**: Activating a SessionChip opens that session: in place where the view embeds
  sessions, otherwise in Sessions › Running.
- **FR-019**: Wherever an item is shown with sessions, every session that covers the item
  or has a PR for it is listed as a SessionChip.

## Contracts

| Contract | Owned / consumed | Version | Spec location |
|---|---|---|---|
| Web API routes and hubd ops of this spec | Owned, internal | Unversioned; ship with the app (001) | `contracts/hubd-socket.md`, `contracts/tool-server-and-library.md` |
| Action and persona library | Owned | Not versioned; changes must stay safe for sessions already running | `agents/actions/`, `agents/personas/`; this spec's changes in `contracts/tool-server-and-library.md` |

Web API and hubd socket: [001](../001-app-frame/spec.md) Contracts. New or changed owned
surfaces this spec needs: persona families, and `verb` and `result` on every action.

## Device scope and risk

No device risk (see [001](../001-app-frame/spec.md) Device scope and risk).

## Acceptance

Host level, in this repository (`make check`: `node --check` on the app plus `pytest`):

- Library tests: persona families and action `verb`/`result` load or are refused as PR 1
  lists.
- Static tests on the components: the family tints and marks are tokens, ItemPill never
  sets a background from state, RepoPicker shows a count past 3 (PR 2).

Browser check (by hand, recorded in the PR, at 1440 px and 390 px wide; rows in
[001 quickstart](../001-app-frame/quickstart.md) §3):

- ItemPill, PersonaBadge, SessionChip and RepoPicker as in the quickstart rows "After 002/PR 2".

Product level: none. The hub is not part of a device image.

## Out of scope

- The views and flows that use these blocks (specs 003–010).

## Success criteria

- **SC-001**: No view shows more than 3 repository pills at once.

## Implementation notes

Existing code to reuse:

- `agents/actions/*.toml` and `agents/personas/` hold the action and persona library.

Backend that is missing:

- A persona family on each persona.
