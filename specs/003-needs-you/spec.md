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

It uses the header button (App frame (001) FR-002), the yellow rule (App frame (001)
FR-011), live updates (App frame (001) FR-020), the trust rule (App frame (001) FR-023)
and the item pill, session chip and persona badge (Building blocks, 002). Results open the
result actions of Launch (005); the session view (Sessions, 004) shows a session's
interactions inline; the Steward's waiting strip (Steward, 010) opens Needs you filtered
to the Steward.

### Views

- **Needs you**: the single list of everything waiting for the maintainer (prompts,
  questions, decisions, results, suggestions), answerable in place.

## User Scenarios & Testing

### User Story 1 - Answer a blocking prompt from any screen (Priority: P1)

A session is stuck on a permission; the maintainer answers it without leaving the view
they are in.

**Why this priority**: A blocked session does nothing until the maintainer answers.

**Independent Test**: Have a session ask for a permission while another view is open,
and answer it from the header.

**Acceptance Scenarios**:

1. **Given** a session is waiting for permission to run `git push`, and the maintainer is
   on Knowledge, **When** they press the yellow "Needs you 1" button in the header and
   choose "Allow" on the permission card, **Then** the session continues, the card shows
   "allowed" in the "handled in this view" line, the count drops to 0, and the yellow is
   gone from the header.

---

### User Story 2 - Grant a Go for a device run (Priority: P2)

A session needs the device; the maintainer grants a limited Go.

**Why this priority**: Device work waits on a Go, but it is rarer than permissions.

**Independent Test**: Have a session ask for a Go, grant it with a run limit, and watch
it count down.

**Acceptance Scenarios**:

1. **Given** a session asks for a Go (reboot and load test) and the device is free,
   **When** the maintainer opens the Go card in Needs you, sets "ends after 3 runs" and
   approves it, **Then** the grant appears under the Needs you "Active grants" filter,
   the session's runs count down, and Overview shows the device lock holder while the
   session holds the lock.

### Edge Cases

- The same interaction is answered in two places: the first answer wins, and every other
  place shows the final status.
- A pull request's head changes after a merge decision was approved: the decision no
  longer applies.
- An eye-test Go is asked for as "always": it is never granted that way.
- A session ends with interactions still pending: they show as ended.

## Requirements

Each requirement is one testable statement. A requirement of another spec is cited with
that spec's name and number, as in "App frame (001) FR-011".

### Functional Requirements

#### Interaction

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
  comes from the signed-in maintainer.
- **FR-006**: A Go card lets the maintainer set the allowed actions (reboot, suspend, load
  test, close apps, eye test), the device, and when it ends (after N runs or after N
  hours).
- **FR-007**: A Go card for an eye test says that the maintainer must look at the device,
  and is never granted as "always".
- **FR-008**: A merge decision card names the pull request and the head commit it applies
  to; it stops applying if the pull request's head changes.
- **FR-009**: A suggestion card names the action, the persona and the items, and offers
  "Launch…" (opens Launch prefilled) and "Dismiss".
- **FR-010**: A result card shows the result type and a summary, and opens the result
  actions for its type (Launch (005) FR-015 to FR-021).
- **FR-010a**: A result made by a session another session manages is not an interaction:
  it belongs to that session's owner. A pull request result whose pull request is already
  on GitHub has nothing to apply and is shown as handled, never as waiting.
- **FR-011**: Once handled, an interaction shows its final status, who handled it and
  where, and stays visible in the "N handled in this view" line until the view is left.
- **FR-012**: Permission and question cards are blocking; they are the only kinds shown
  yellow (App frame (001) FR-011).
- **FR-013**: Answering an interaction anywhere (card, session view, terminal) updates
  every other place it is shown within 5 seconds.

#### Feed

- **FR-014**: A Feed lists interactions in three groups: Blocking, Suggested and Results
  ready, in that order, oldest first within Blocking.
- **FR-015**: A Feed can be filtered to All, The Steward or Other sessions.
- **FR-016**: A Feed has a dense mode with one line per interaction.
- **FR-017**: Each card in a Feed links to its session and its items.

#### Needs-you modal and Active grants

- **FR-018**: Needs you opens as a modal from the header on any view, and as a sheet on
  phone.
- **FR-019**: Needs you shows every pending interaction (permission, question, decision,
  suggestion, result) as a Feed (FR-014 to FR-017).
- **FR-020**: Needs you has an "Active grants" filter that lists approved Go and merge
  decisions still in force, with what is left (runs, hours) and "End now".
- **FR-021**: Needs you can be filtered to one session (used by the Steward's waiting
  strip).
- **FR-022**: Closing Needs you returns to the same place in the view below.
- **FR-023**: When a new interaction becomes pending, or the app opens while interactions wait
  that the maintainer hasn't put off, Needs you opens by itself, showing them as its Feed;
  it can be answered or closed from the keyboard alone, and Esc closes it.
- **FR-024**: "Later" (or closing it) puts off what Needs you showed: it stays in the header
  count and Needs you doesn't open by itself again until a new interaction arrives. What
  was put off is remembered per browser.
- **FR-025**: Needs you never opens by itself while the maintainer is typing in a terminal
  or another dialog is open: it waits until focus leaves the terminal, or 10 seconds pass
  without a keystroke there, or the dialog closes.

### Key Entities

- **Interaction**: something a session or the hub needs from the maintainer; has a kind,
  a status, a session, items, and who handled it and where.
- **Decision**: a Go or a merge decision; has a scope and, once approved, an end.
- **Grant**: an approved decision still in force, with what is left of it (runs, hours).

## Success Criteria

### Measurable Outcomes

- **SC-001**: From any view, a blocking interaction can be answered in at most 2
  activations (open Needs you, choose the answer).
- **SC-002**: A new interaction shows in the header count and in Needs you within 5
  seconds of the session raising it.

## Assumptions

- What applying a result does is in Launch (005); this spec only opens it.
- Go cards are decisions the maintainer records; the hub never acts on the device itself
  (App frame (001) Assumptions).
- A merge decision's head commit is the pull request head as GitHub reports it.
- Permission requests and questions come from Claude Code sessions as they raise them.
