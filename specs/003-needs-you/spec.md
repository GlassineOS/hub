# Feature Specification: Needs you

**Feature Branch**: `001-hub-app`
**Created**: 2026-11-06
**Status**: Draft
**Input**: "Needs you: interactions of every kind (permissions, questions, decisions incl. Go and merge decisions, suggestions, results), the Feed, the Needs-you modal and Active grants."

## Context

The maintainer is one person, and attention is the scarce thing. This spec defines
everything a session or the hub needs from them: the **interaction** (a permission, a
question, a decision, a suggestion or a result), the **Feed** that lists interactions, the
**Needs-you modal** that opens from any view, and **Active grants** (the Go and merge
decisions in force). Each interaction can be answered wherever it shows, with the same
effect everywhere.

Depends on: [001](../001-app-frame/spec.md) (the header button 001 FR-002, the yellow rule
001 FR-011, live updates 001 FR-020, the trust rule 001 FR-023) and
[002](../002-building-blocks/spec.md) (ItemPill, SessionChip, PersonaBadge). Results open
the result actions of [005](../005-launch/spec.md); the SessionView
([004](../004-sessions/spec.md)) shows a session's interactions inline; the Steward's
waiting strip ([010](../010-steward/spec.md)) opens Needs you filtered to the Steward.

## Views

- **Needs you**: the single list of everything waiting for the maintainer (prompts,
  questions, decisions, results, suggestions), answerable in place.

## User scenarios

### Scenario 1 – Answer a blocking prompt from any screen (Priority: P1)

**Given** a session is waiting for permission to run `git push`, and the maintainer is on
Knowledge
**When** they press the yellow "Needs you 1" button in the header and choose "Allow" on
the permission card
**Then** the session continues, the card shows "allowed" in the "handled in this view"
line, the count drops to 0, and the yellow is gone from the header.

### Scenario 2 – Grant a Go for a device run (Priority: P2)

**Given** a session asks for a Go (reboot and load test) and the device is free
**When** the maintainer opens the Go card in Needs you, sets "ends after 3 runs" and
approves it
**Then** the grant appears under the Needs you "Active grants" filter, the session's runs
count down, and Overview shows the device lock holder while the session holds the lock.

## Requirements

Requirements are one testable statement each. A requirement of another spec is written with
that spec's number first, as in `001 FR-011`.

### Interaction

- **FR-001**: An interaction has a kind: permission, question, decision, suggestion or
  result.
- **FR-002**: An interaction has a status: pending, allowed, always, denied, answered,
  started, dismissed, terminal (answered in the terminal), timeout or ended.
- **FR-003**: A permission card shows the tool, the exact command or file, the session and
  how long it has waited, with Allow, Always (for this session) and Deny.
- **FR-004**: A question card shows the question and the session's offered answers as
  buttons.
- **FR-005**: A decision card (a Go or a merge decision) shows what is asked, by which
  session, and its scope; approving it is recorded as the maintainer's word only when it
  comes from the logged-in maintainer.
- **FR-006**: A Go card lets the maintainer set the allowed actions (reboot, suspend, load
  test, close apps, eye test), the device, and when it ends (after N runs or after N
  hours).
- **FR-007**: A Go card for an eye test says that the maintainer must look at the device,
  and is never granted as "always".
- **FR-008**: A merge decision card names the PR and the head commit it applies to; it
  stops applying if the PR head changes.
- **FR-009**: A suggestion card names the action, the persona and the items, and offers
  "Launch…" (opens Launch prefilled) and "Dismiss".
- **FR-010**: A result card shows the result type and a summary, and opens the result
  actions for its type (005 FR-015 to FR-021).
- **FR-011**: Once handled, an interaction shows its final status, who handled it and
  where, and stays visible in the "N handled in this view" line until the view is left.
- **FR-012**: Permission and question cards are blocking; they are the only kinds shown
  yellow (001 FR-011).
- **FR-013**: Answering an interaction anywhere (card, SessionView, terminal) updates
  every other place it is shown within 5 seconds.

### Feed

- **FR-014**: A Feed lists interactions in three groups: Blocking, Suggested and Results
  ready, in that order, oldest first within Blocking.
- **FR-015**: A Feed can be filtered to All, The Steward or Other sessions.
- **FR-016**: A Feed has a dense mode with one line per interaction.
- **FR-017**: Each card in a Feed links to its session and its items.

### Needs-you modal and Active grants

- **FR-018**: Needs you opens as a modal from the header on any view, and as a sheet on
  phone.
- **FR-019**: Needs you shows every pending interaction (permission, question, decision,
  suggestion, result) as a Feed (FR-014 to FR-017).
- **FR-020**: Needs you has an "Active grants" filter that lists approved Go and merge
  decisions still in force, with what is left (runs, hours) and "End now".
- **FR-021**: Needs you can be filtered to one session (used by the Steward's waiting
  strip).
- **FR-022**: Closing Needs you returns to the same place in the view below.

## Contracts

| Contract | Owned / consumed | Version | Spec location |
|---|---|---|---|
| Web API routes and hubd ops of this spec | Owned, internal | Unversioned; ship with the app (001) | `contracts/web-api.md`, `contracts/hubd-socket.md` |

Web API and hubd socket: [001](../001-app-frame/spec.md) Contracts; this spec's routes and
ops are in `contracts/`. New or changed owned surfaces this spec needs: interactions with
results (one projection, `interaction.list` / `interaction.answer`).

## Device scope and risk

No device risk. Go cards are decisions recorded by the maintainer; the hub never acts on
the device (see [001](../001-app-frame/spec.md) Device scope and risk).

## Acceptance

Host level, in this repository (`make check`: `node --check` on the app plus `pytest`):

- hubd tests with the fake Claude CLI: interactions with every status, decisions (Go
  scope and end, merge head check, eye test never "always").

Browser check (by hand, recorded in the PR, at 1440 px and 390 px wide; rows in
[001 quickstart](../001-app-frame/quickstart.md) §3):

- Needs you modal from every view.

Product level: none. The hub is not part of a device image.

## Out of scope

- What applying a result does: the result actions per type are in
  [005](../005-launch/spec.md).

## Success criteria

- **SC-001**: From any view, a blocking interaction can be answered in at most 2
  activations (open Needs you, choose the answer).
- **SC-002**: A new interaction shows in the header count and in Needs you within 5
  seconds of the session raising it.

## Implementation notes

Existing code to reuse:

- `hubd/decisions.py` has Go and merge decisions with scope, run and hour limits, head
  checks and the eye-test rule; this backs the decision cards and Active grants.

Backend that is missing:

- Interactions: one model for permission, question, decision, suggestion and result,
  with the statuses in FR-002 and result payloads per type.
