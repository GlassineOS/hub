# Feature Specification: App frame

**Feature Branch**: `001-hub-app`
**Created**: 2026-11-06
**Status**: Draft
**Input**: "The frame of the hub web app: header and navigation, the phone layout, the rules that hold across every view, and the security and trust rules."

## Context

The hub is the place one maintainer uses to run GlassineOS. That means dozens of
repositories, their issues, pull requests and CI runs, a shared knowledge base and notes,
and many Claude Code sessions working at the same time. Each session has a persona
(Engineer, Code reviewer, CI investigator, ...) and works in its own git worktree.

The maintainer is one person, and attention is the scarce thing. The hub's job is to:

- show what needs that person right now (a blocking permission, a question, a result to
  act on) wherever they are in the app, and let them answer it in place (Needs you, 003);
- turn any work item into work for an agent in a few steps, with a visible plan and a
  known kind of result (Launch, 005);
- keep the GitHub actions the maintainer does as themselves (merge, close, label, re-run)
  one click from the item, never mixed up with starting an agent (Work, 006);
- make knowledge, notes and past sessions findable, and keep the host tidy (Knowledge 008,
  Notes 009, Sessions 004);
- run beside a Steward, a long-lived planning session that sees what the maintainer sees
  (Steward, 010).

The hub runs on the maintainer's machine. The host service holds the credentials and runs
the sessions. The hub is used on a desktop browser and on a phone.

This spec is the frame every view sits in: the header and navigation, the layout at phone
width, the rules that hold across all views, and the security and trust rules. It depends
on no other spec. The other nine build on it and cite its rules by name and ID.

### Views

- **Header**: always shows where you are, how many things wait for you, and the way to
  start new work.
- **Phone**: the same app at phone width, with the header and Steward folded for one hand.

The navigation leads to Overview and Roadmap (007), Work and Work item (006), Knowledge
(008), Notes (009) and Sessions (004). Needs you (003), Launch (005) and the Steward (010)
open over or beside any view. The shared building blocks are in Building blocks (002).

## User Scenarios & Testing

### User Story 1 - Use it on a phone (Priority: P2)

The maintainer uses the hub one-handed on a phone.

**Why this priority**: The maintainer answers sessions away from the desk, but the
desktop layout comes first.

**Independent Test**: Open the hub at 390 px wide and walk through the scenario below.

**Acceptance Scenarios**:

1. **Given** the hub is open on a 390 px wide phone, **When** the maintainer opens the
   menu, goes to a Work item and answers a question from the Steward's floating button,
   **Then** nothing scrolls sideways, the header shows only "New" and "Menu", the Steward
   opens as a full sheet, and every control can be tapped.

### Edge Cases

- The host service cannot be reached: the header says so plainly, and the app shows that
  its data may be out of date.
- Nothing waits for the maintainer: the "Needs you" button is plain, not yellow.
- Things wait but none of them blocks: the button is outlined, not yellow; only its count
  is yellow.
- A list grows past one screen: it shows a count and loads more only on request.
- Agent text claims to be the maintainer's approval: it is not treated as one.

## Requirements

Each requirement is one testable statement. A requirement of another spec is cited with
that spec's name and number, as in "App frame (001) FR-011".

### Functional Requirements

#### Header

- **FR-001**: The header shows the navigation: Overview, Roadmap, Work, Knowledge, Notes,
  Sessions, with the current view marked.
- **FR-002**: The header shows a "Needs you N" button; it is yellow only when N > 0 and
  something is blocking, outlined when N > 0 and nothing blocks, and plain when N = 0. Its
  count N is a badge that is yellow and bold whenever N > 0: everything counted waits for
  the maintainer.
- **FR-003**: The "Needs you" button opens the Needs you modal from any view.
- **FR-004**: The header shows "＋ New work", which opens Launch with an empty brief.
- **FR-005**: The header shows the signed-in maintainer and which host service the app is
  connected to, and shows plainly when the host service cannot be reached.
- **FR-006**: The header shows a small usage budget meter: how much of the sessions'
  usage allowance is used, in words as well as a bar, and says plainly when it is low.

#### Phone (≤ 760 px)

- **FR-007**: At 760 px wide or less, the header shows only "New" and "Menu"; Menu carries
  the Needs-you count and holds the navigation, Needs you and the user line.
- **FR-008**: At phone width the Steward is a floating button that opens it as a full
  sheet.
- **FR-009**: At phone width, views use a single column with 16 px side gutters, and no
  page scrolls sideways (wide content such as diffs and terminals scrolls inside its own
  box).
- **FR-010**: At phone width, Launch, Needs you and flyouts open as full sheets.

#### Cross-cutting rules

- **FR-011**: Yellow (#ffd86b) marks only things that wait for the maintainer; no other
  state uses it.
- **FR-012**: Severity is shown by outline, not colour: double = high or failed, heavy =
  medium or blocked, solid = low, dashed = info, running or draft.
- **FR-013**: Pen blue (#2747b8) marks the one primary agent action of a place (Launch
  and the actions that start an agent) and the Steward; GitHub actions done by the
  maintainer are the black split button; the two are never combined in one control.
- **FR-014**: Ink (#111) on paper is the base; terminals use night paper (#121212).
- **FR-015**: Every control has an accessible name; state is never shown by colour
  alone; focus is always visible.
- **FR-016**: Every view can be used by keyboard alone; modals and sheets trap focus and
  close on Esc.
- **FR-017**: Text and controls meet WCAG 2.2 AA contrast, and touch targets are at least
  44 × 44 px on phone; links inside running text keep the height of the text.
- **FR-018**: Animations are off when the viewer asks for reduced motion, and the app
  stays usable on an e-ink browser (no motion needed to understand state).
- **FR-019**: Lists that can grow past one screen show a count and load more on request;
  no view loads all items of all repositories at once.
- **FR-020**: Live data (sessions, interactions, terminals) updates without a page
  reload; the app shows when it is out of date or disconnected.

#### Security and trust

- **FR-021**: The browser never holds GitHub or Claude credentials; every GitHub action
  and every session runs through the host service.
- **FR-022**: Every GitHub write a session asks for is checked against the hub's list of
  allowed writes, and anything not on the list is refused.
- **FR-023**: A decision counts as the maintainer's word only when the signed-in
  maintainer approves it in the app, never from agent or tool text.
- **FR-024**: Text written by an agent (cards, reports, suggestions) never widens what an
  agent may do.
- **FR-025**: The hub accepts requests only from the signed-in maintainer, and is
  reachable only from the maintainer's own machine unless the maintainer chooses
  otherwise.

### Key Entities

- **Maintainer**: the one person who signs in and whose approval counts as a decision.
- **View**: a place in the app (Overview, Roadmap, Work, Knowledge, Notes, Sessions);
  Needs you, Launch and the Steward open over or beside any view.

## Success Criteria

### Measurable Outcomes

- **SC-001**: 0 GitHub writes are made by sessions outside the list of allowed writes;
  every kind of write not on the list is refused.
- **SC-002**: With 60 repositories and 500 open items, Overview and Work render their
  first screen in under 2 seconds on the host.
- **SC-003**: At 390 px wide, no view scrolls sideways and every control is at least
  44 × 44 px, links inside running text aside.
- **SC-004**: Every P1 user story can be completed with the keyboard alone, without a
  mouse.

## Assumptions

- One maintainer uses the hub; more than one maintainer, roles or sharing the hub with
  others are out of scope.
- The hub never acts on a device: it does not take the device lock, flash, reboot or
  connect to a device. It shows device decisions (Go cards, Needs you (003)) and the
  device lock holder (Overview and Roadmap (007) FR-003) as data reported by sessions.
  Granting a Go lets a session act within that Go's scope; what the session then does on
  the device is governed by the device repositories' own rules.
- The hub works over a GitHub organization (issues, pull requests, runs, labels, reviews,
  merges) and runs Claude Code sessions; what it shows of them is what GitHub and Claude
  Code report.
- The hub is not part of a device image.
