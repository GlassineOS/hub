# Feature Specification: Building blocks

**Feature Branch**: `001-hub-app`
**Created**: 2026-11-06
**Status**: Draft
**Input**: "The building blocks every hub view uses: item references and item pill, item picker and repository picker, persona badge with persona families and action metadata, and session chip."

## Context

Four things recur everywhere in the hub:

- **Item**: an issue, pull request, CI run or roadmap item, written `repo#N` or
  `workflow #N`.
- **Launch**: the path from "I want an agent on this" to a running session (Launch, 005).
- **Session**: a Claude Code session (or plain shell) with a persona, covered items and a
  terminal (Sessions, 004).
- **Interaction**: anything a session or the hub needs from the maintainer (Needs you,
  003).

This spec defines the small pieces every view uses to show them. It uses the colour and
outline rules (App frame (001) FR-011–FR-014), the accessibility rules (App frame (001)
FR-015–FR-017) and the scale rule (App frame (001) FR-019).

### Blocks

- **Item pill**: names one item by its stable reference, shows its state, and opens it.
- **Item picker / repository picker**: choose items and repositories by typing, at any number of
  repositories.
- **Persona badge**: tells at a glance which persona, and which family of work, a session
  is.
- **Action metadata**: gives each action a short name (its verb) and the kind of result it
  ends with, so Launch and Work rows can say it in plain words. The action table itself is
  Launch (005) FR-012.
- **Session chip**: shows a session wherever its items are shown, and whether it waits for
  the maintainer.

## User Scenarios & Testing

### User Story 1 - Pick items and repositories by keyboard (Priority: P2)

The maintainer picks the items and repositories for a piece of work without the mouse.

**Why this priority**: Every Launch needs items and repositories; the pickers must work
at the scale of the organization.

**Independent Test**: In a Launch brief, pick one item and five repositories using only
the keyboard.

**Acceptance Scenarios**:

1. **Given** the maintainer is in a Launch brief with no covered items, **When** they
   type "204" in the item picker, move to `kernel#204` with the arrow keys and press
   Enter, then open the repository picker, type a filter and choose five repositories, **Then**
   `kernel#204` shows as a removable item pill with its state by outline and icon, the
   repository selection shows as "5 repos" (not five pills), and no step needed a mouse.

### Edge Cases

- A selection holds more than 3 repositories: it shows as a count that opens the picker.
- A title search matches items in many repositories: only the selected repositories are
  searched.
- A shell has no persona: it gets its own badge, not a family tint.

## Requirements

Each requirement is one testable statement. A requirement of another spec is cited with
that spec's name and number, as in "App frame (001) FR-011".

### Functional Requirements

#### Item reference and item pill

- **FR-001**: Every item is referred to by a stable reference: `repo#N` for issues and
  pull requests, `workflow #N` for runs, and the roadmap item reference for roadmap items.
- **FR-002**: An item pill shows the item kind icon, the reference and (when there is room)
  the title, and opens the Work item view when activated.
- **FR-003**: An item pill shows the item's state (open, draft, merged, closed, failing,
  running) by its outline and icon, never by a background colour.
- **FR-004**: An item pill can be removable (shows a remove control) where it stands for a
  selection, such as a Launch brief's covered items.

#### Item picker and repository picker

- **FR-005**: The repository picker lets the user pick one or many repositories by typing a
  filter, and offers "All repositories" where a view allows it.
- **FR-006**: The repository picker shows recent and pinned repositories first, then the rest
  grouped by layer.
- **FR-007**: No view shows all repositories as pills or chips at once (scale rule). A
  selection of more than 3 repositories is shown as a count ("5 repos") that opens the
  picker.
- **FR-008**: The item picker finds items by reference or by words in the title, across
  the selected repositories, and returns one or many items.
- **FR-009**: The item picker shows each candidate as an item pill with its state and
  repository.
- **FR-010**: Both pickers can be used fully by keyboard (type, arrows, Enter, Esc).

#### Persona badge and persona families

- **FR-011**: Every persona belongs to exactly one family: build, review, investigate,
  write or organise.
- **FR-012**: A persona badge shows the persona's initials on its family tint (build
  #d6e2ff, review #eadcff, investigate #ffd9b8, write #d4efdc, organise #e2e2e2), with
  the persona name as its accessible label.
- **FR-013**: The Steward's badge is a pen-blue "S" and is never used for another
  persona.
- **FR-014**: A plain shell has its own badge that is not a persona family.
- **FR-015**: A family legend is available wherever badges appear in a list (Sessions ›
  Running).

#### Session chip

- **FR-016**: A session chip shows a session's persona badge, a short name and its state
  (RUNNING, WAITING, DONE, ATTACHED).
- **FR-017**: A session chip for a session that waits for the maintainer is marked yellow
  and says how many things wait.
- **FR-018**: Activating a session chip opens that session: in place where the view embeds
  sessions, otherwise in Sessions › Running.
- **FR-019**: Wherever an item is shown with sessions, every session that covers the item
  or has a pull request for it is listed as a session chip.

### Key Entities

- **Item**: an issue, pull request, CI run or roadmap item; has a stable reference, a
  kind, a state and a repository.
- **Persona**: a role a session plays (Engineer, Code reviewer, ...); belongs to one
  family.
- **Family**: build, review, investigate, write or organise; gives the badge its tint.
- **Action**: a kind of work a persona does; has a verb and a result type.

## Success Criteria

### Measurable Outcomes

- **SC-001**: No view shows more than 3 repository pills at once.

## Assumptions

- The views and flows that use these blocks are in specs 003–010.
- The library of personas and actions is an owned interface: a change to it keeps
  sessions that are already running working.
- Item states (open, draft, merged, closed, failing, running) are as GitHub reports them.
