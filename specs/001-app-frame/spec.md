# Feature Specification: App frame

**Feature Branch**: `001-hub-app`
**Created**: 2026-11-06
**Status**: Draft
**Input**: "The frame of the hub web app: header and navigation, the phone layout, the rules that hold across every view, and the security and trust rules."

## Context

The hub is the place one maintainer uses to run GlassineOS. That means dozens of
repositories, their issues, pull requests and CI runs, a shared knowledge base and notes,
and many Claude Code sessions working at the same time. Sessions run in tmux on the host.
Each has a persona (Engineer, Code reviewer, CI investigator, ...) and works in its own git
worktree.

The maintainer is one person, and attention is the scarce thing. The hub's job is to:

- show what needs that person right now (a blocking permission, a question, a result to
  act on) wherever they are in the app, and let them answer it in place (003);
- turn any work item into work for an agent in a few steps (Launch, 005), with a visible
  plan and a known kind of result;
- keep the GitHub actions the maintainer does as themselves (merge, close, label, re-run)
  one click from the item, never mixed up with starting an agent (006);
- make knowledge, notes and past sessions findable, and keep the host tidy (worktrees,
  old sessions) (008, 009, 004);
- run beside a Steward, a long-lived planning session that sees what the maintainer sees
  (010).

The hub runs on the maintainer's machine. The web app talks to `hubd`, a host daemon that
holds the credentials and runs the sessions. Sessions reach the hub through a tool server.
The hub is used on a desktop browser and on a phone.

This spec is the frame every view sits in: the header and navigation (with the usage meter
and the hubd status), the layout at phone width, the rules that hold across all views
(colour and outline meanings, accessibility, live updates, scale) and the security and
trust rules. It depends on no other spec. The other nine build on it and cite its rules by
spec and number instead of repeating them.

Related: `docs/orchestrator.md` (session and merge model), `SECURITY.md` (boundary),
`.specify/memory/constitution.md`, and `specs/README.md` (all ten specs and their build
order).

## Views

- **Header**: always shows where you are, how many things wait for you, and the way to
  start new work.
- **Phone**: the same app at phone width, with the header and Steward folded for one hand.

The navigation leads to the views the other specs define: Overview and Roadmap
([007](../007-overview-roadmap/spec.md)), Work and Work item ([006](../006-work/spec.md)),
Knowledge ([008](../008-knowledge/spec.md)), Notes ([009](../009-notes/spec.md)) and
Sessions ([004](../004-sessions/spec.md)). Needs you ([003](../003-needs-you/spec.md)),
Launch ([005](../005-launch/spec.md)) and the Steward ([010](../010-steward/spec.md)) open
over or beside any view. The shared building blocks are in
[002](../002-building-blocks/spec.md).

## User scenarios

### Scenario 1 – Use it on a phone (Priority: P2)

**Given** the hub is open on a 390 px wide phone
**When** the maintainer opens the menu, goes to a Work item and answers a question from
the Steward's floating button
**Then** nothing scrolls sideways, the header shows only "New" and "Menu", the Steward
opens as a full sheet, and every control can be tapped.

## Requirements

Requirements are one testable statement each. A requirement of another spec is written with
that spec's number first, as in `001 FR-011`.

### Header

- **FR-001**: The header shows the navigation: Overview, Roadmap, Work, Knowledge, Notes,
  Sessions, with the current view marked.
- **FR-002**: The header shows a "Needs you N" button; it is yellow only when N > 0 and
  something is blocking, outlined when N > 0 and nothing blocks, and plain when N = 0.
- **FR-003**: The "Needs you" button opens the Needs you modal from any view.
- **FR-004**: The header shows "＋ New work", which opens Launch with an empty brief.
- **FR-005**: The header shows the logged-in user and the hubd address it is connected
  to, and shows plainly when hubd cannot be reached.
- **FR-006**: The header shows a small usage budget meter: how much of the sessions'
  usage allowance is used, in words as well as a bar, and says plainly when it is low.

### Phone (≤ 760 px)

- **FR-007**: At 760 px wide or less, the header shows only "New" and "Menu"; Menu holds
  the navigation, Needs you and the user line.
- **FR-008**: At phone width the Steward is a floating button that opens it as a full
  sheet.
- **FR-009**: At phone width, views use a single column with 16 px side gutters, and no
  page scrolls sideways (wide content such as diffs and terminals scrolls inside its own
  box).
- **FR-010**: At phone width, Launch, Needs you and flyouts open as full sheets.

### Cross-cutting rules

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
  44 × 44 px on phone.
- **FR-018**: Animations are off when the viewer asks for reduced motion, and the app
  stays usable on an e-ink browser (no motion needed to understand state).
- **FR-019**: Lists that can grow past one screen show a count and load more on request;
  no view loads all items of all repositories at once.
- **FR-020**: Live data (sessions, interactions, terminals) updates without a page
  reload; the app shows when it is out of date or disconnected.

### Security and trust

- **FR-021**: The browser never holds GitHub or Claude credentials; every GitHub action
  and every session runs through hubd.
- **FR-022**: Every GitHub write an agent session asks for goes through the hub's policy
  allowlist, which refuses anything not listed.
- **FR-023**: A decision counts as the maintainer's word only when it is approved by the
  logged-in maintainer in the app, never from agent or tool text.
- **FR-024**: Text written by an agent (cards, reports, suggestions) never widens what an
  agent may do.
- **FR-025**: The app accepts requests only from the logged-in maintainer and binds to
  the local host unless set otherwise.

## Contracts

| Contract | Owned / consumed | Version | Spec location |
|---|---|---|---|
| Web API (`/api/...`, used by the app only) | Owned, internal | Unversioned; changes ship with the app | `app/hub/web.py`; shared rules in `contracts/web-api.md`, each spec's routes in its own `contracts/web-api.md` |
| hubd unix socket (requests from the web app) | Owned, internal | Unversioned; web app and hubd ship together | `hubd/`; login gate in `contracts/hubd-socket.md`, each spec's ops in its own |

Tool server and library changes stay safe for sessions already running
(`contracts/tool-server-and-library.md`). New or changed owned surfaces this spec needs: the
usage reading (status line, `usage.status`) and the hubd address in `ping`.

## Device scope and risk

No device risk. The hub never touches devices. It shows device-related decisions (Go
cards, 003) and the device lock holder (007 FR-003) as data reported by sessions and the lock.
It does not take the lock, flash, reboot or connect to a device itself. Granting a Go gives
a session permission to act within that Go's scope; what the session does on the device
is governed by the device repositories' own rules. Every other spec refers to this
section.

## Acceptance

Host level, in this repository (`make check`: `node --check` on the app plus `pytest`):

- Static checks on the app: navigation items, the yellow rule (FR-011) applied only to
  waiting states.
- Policy tests: agent requests outside the allowlist refused (FR-022).

Browser check (by hand, recorded in the PR, at 1440 px and 390 px wide; rows in
[001 quickstart](../001-app-frame/quickstart.md) §3):

- Header, phone menu and sheets, no sideways scroll, keyboard-only pass, reduced motion.

Product level: none. The hub is not part of a device image.

## Out of scope

- Any action on a device (flashing, rebooting, taking the device lock) by the hub itself.
- More than one maintainer, roles or sharing the hub with others.

## Success criteria

- **SC-001**: 0 GitHub writes are made by agents outside the policy allowlist (policy
  tests cover every listed call and at least one refused call per kind).
- **SC-002**: With 60 repositories and 500 open items, Overview and Work render their
  first screen in under 2 seconds on the host.
- **SC-003**: At 390 px wide, no view scrolls sideways and every control is at least
  44 × 44 px.
- **SC-004**: The keyboard-only browser pass completes every P1 scenario without a mouse.

## Implementation notes

Existing code to reuse:

- Web app (`app/hub/web.py`, `app/hub/static/app.js`) already has views for overview,
  roadmap, work lists, issue/PR/run detail, new issue, workflow dispatch, docs search,
  terminal, session spec, new work and launch forms, inbox, past sessions, cleanup,
  plain shells, decisions, the merge queue, notes and the Steward panel. Navigation tests
  in `tests/test_app.py` pin the current menu and must change with FR-001.
- `app/hub/tools.py` has about 50 tool server tools (including suggest_session,
  plan_work, docs_search, work_search, code_search, decision_request, merge_pr).
- `tests/test_agents.py` has a fake Claude CLI; `tests/dev_hubd.py` runs a dev hubd.

Backend that is missing:

- `tests/dev_hubd.py` hard-codes the tool server port; parallel test runs need it
  configurable.
