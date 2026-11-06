# Feature Specification: Notes

**Feature Branch**: `001-hub-app`
**Created**: 2026-11-06
**Status**: Draft
**Input**: "Notes: search with trust labels, the view's states, and upkeep (totals, compact and sweep, applying note operations)."

## Context

Notes are the shared notes that sessions and the maintainer keep, each with a trust label.

- **Notes** finds notes with their trust labels in view and keeps them tidy: an Archivist
  session proposes note operations, the maintainer applies them, and no operation ever
  deletes a note.

Depends on: App frame (001), Building blocks (002) and Launch (005) for the compact and
sweep actions and the notes result.

## User Scenarios & Testing

### User Story 1 - Keep notes useful (Priority: P3)

The maintainer tidies a topic without losing anything.

**Given** the Notes topic "epd" has many HISTORY and duplicate notes
**When** the maintainer runs "Compact…" on that topic
**Then** an Archivist session returns note operations (merge, distil, supersede, ...),
each with the exact notes-tool command it stands for; applying them changes labels and
merges notes, and deletes nothing.

### Edge Cases

- More than 100 matches: the list stops and offers a command that lists everything
  (FR-002).
- The notes tool is missing or fails: the view says so, with the tool's message (FR-004).
- The index is updating: an "indexing" badge shows (FR-004).
- A proposed operation would delete a note: it is not offered and cannot be applied
  (FR-006).

## Requirements

Each requirement is one testable statement. A requirement of another spec is cited with
the spec's name and number, as in "App frame (001) FR-011".

### Functional Requirements

- **FR-001**: Notes searches by words only; the search runs on a button press, accepts at
  most 500 characters, and is not kept in the address bar.
- **FR-002**: Notes shows 20 rows, then more on request up to 100; past 100 it shows a
  limit box with a copyable notes-tool command that lists everything.
- **FR-003**: Each row shows the trust label (CURRENT, OPEN QUESTION, HISTORY, RETRACTED,
  ARCHIVE·UNREVIEWED, NO STATUS), the title, the topic and the date; a long row can be
  expanded.
- **FR-004**: Notes shows these states: empty (with the label legend), no results, more
  available, limit reached, notes tool missing, notes tool failed (with the tool's
  message), warnings, and an "indexing" badge while the index updates.
- **FR-005**: A "Keep notes useful" flyout shows totals per label and per topic, and
  offers "Compact…" and "Sweep…" for all notes or per topic.
- **FR-006**: A session only proposes note operations; only the maintainer applies them,
  from the hub. No operation deletes a note (Launch (005) FR-021), and Notes shows only
  notes the maintainer may see.

### Key Entities

- **Note**: a shared note with a title, topic, date, body and trust label.
- **Trust label**: how far a note can be relied on: CURRENT, OPEN QUESTION, HISTORY,
  RETRACTED, ARCHIVE·UNREVIEWED or NO STATUS.
- **Note operation**: a proposed change (merge, distil, answer, supersede, ...) with the
  command it stands for; it changes labels or merges notes and never deletes.

## Success Criteria

No criteria of its own; App frame (001) SC-004 (keyboard-only pass) and App frame (001)
SC-003 (phone width) apply.

## Assumptions

- A notes tool on the maintainer's machine holds the notes, searches them and applies
  operations; the hub shows its results and its messages as they are.
- Compact is done by an Archivist session and Sweep by a docs-writer session; both are
  read-only and post nothing (Launch (005)).
- The hub runs on the maintainer's own machine and touches no device.

## Out of scope

- Deleting notes: no note operation deletes one (Launch (005) FR-021).
