# Feature Specification: Notes

**Feature Branch**: `001-hub-app`
**Created**: 2026-11-06
**Status**: Draft
**Input**: "Notes: search with trust labels, the view's states, and upkeep (totals, compact and sweep, applying note operations)."

## Context

Notes are the shared notes that sessions and the maintainer keep, each with a trust label.
This spec defines the Notes view, which finds notes with their labels in view, and their
upkeep: an Archivist session proposes note operations, the maintainer applies them, and no
operation ever deletes a note.

Depends on: [001](../001-app-frame/spec.md), [002](../002-building-blocks/spec.md) and
[005](../005-launch/spec.md) (the compact and sweep actions, the notes result).

## Views

- **Notes**: finds and keeps tidy the shared notes, with each note's trust label in view.

## User scenarios

### Scenario 1 – Keep notes useful (Priority: P3)

**Given** the Notes topic "epd" has many HISTORY and duplicate notes
**When** the maintainer runs "Compact…" on that topic
**Then** an Archivist session returns note operations (merge, distil, supersede, ...),
each with its exact `notes` command; applying them changes labels and merges notes, and
deletes nothing.

## Requirements

Requirements are one testable statement each. A requirement of another spec is written with
that spec's number first, as in `001 FR-011`.

### Notes

- **FR-001**: Notes searches by words only; the search runs on a button press, accepts at
  most 500 characters, and is not kept in the address bar.
- **FR-002**: Notes shows 20 rows, then more on request up to 100; past 100 it shows a
  limit box with a copyable `notes` command that lists everything.
- **FR-003**: Each row shows the trust label (CURRENT, OPEN QUESTION, HISTORY, RETRACTED,
  ARCHIVE·UNREVIEWED, NO STATUS), the title, the topic and the date; a long row can be
  expanded.
- **FR-004**: Notes shows these states: empty (with the label legend), no results, more
  available, limit reached, notes tool missing, notes tool failed (with the tool's
  message), warnings, and an "indexing" badge while the index updates.
- **FR-005**: A "Keep notes useful" flyout shows totals per label and per topic, and
  offers "Compact…" and "Sweep…" for all notes or per topic.

## Contracts

| Contract | Owned / consumed | Version | Spec location |
|---|---|---|---|
| Web API routes and hubd ops of this spec | Owned, internal | Unversioned; ship with the app (001) | `contracts/web-api.md`, `contracts/hubd-socket.md`, `contracts/tool-server-and-library.md` |
| `notes` CLI | Consumed | Installed version | `hubd/notes.py` |

Web API and hubd socket: [001](../001-app-frame/spec.md) Contracts; this spec's routes, ops
and actions are in `contracts/`. New or changed owned surfaces this spec needs: the compact
action.

## Device scope and risk

No device risk (see [001](../001-app-frame/spec.md) Device scope and risk).

## Acceptance

Host level, in this repository (`make check`: `node --check` on the app plus `pytest`):

- Web API tests: Notes limits FR-001/FR-002.

Browser check (by hand, recorded in the PR, at 1440 px and 390 px wide; rows in
[001 quickstart](../001-app-frame/quickstart.md) §3):

- Notes as in the quickstart row "After 009/PR 1".

Product level: none. The hub is not part of a device image.

## Out of scope

- Deleting notes: no note operation deletes one (005 FR-021).

## Success criteria

No criteria of its own; 001 SC-004 (keyboard-only pass) and 001 SC-003 (phone width) apply.

## Implementation notes

Backend that is missing:

- Action `compact` (notes result).
- Notes upkeep: totals by label and topic, and applying note operations (hubd has status
  and find only).
