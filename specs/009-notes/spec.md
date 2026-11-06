# Feature Specification: Notes

**Feature Branch**: `001-hub-app`
**Created**: 2026-11-06
**Status**: Draft
**Input**: "Notes: search with trust labels, the view's states, and upkeep (totals, compact and sweep, applying note operations)."

## Context

Notes are the shared notes that sessions and the maintainer keep, each with a trust label.
They exist so sessions can read them: every session, planner and the Steward included, can
search them. What needs care is a note's text leaving in a public post, not a session reading it.

- **Notes** finds notes with their trust labels in view and keeps them tidy: sessions
  propose note operations, the maintainer applies them, and the maintainer can delete a
  note that is wrong or contradicts another.

Depends on: App frame (001), Building blocks (002) and Launch (005) for the compact and
sweep actions and the notes result.

## User Scenarios & Testing

### User Story 1 - Keep notes useful (Priority: P3)

The maintainer tidies a topic and drops what is wrong.

**Given** the Notes topic "epd" has many HISTORY and duplicate notes
**When** the maintainer runs "Compact…" on that topic
**Then** an Archivist session returns note operations (merge, distil, supersede, ...),
each with the exact notes-tool command it stands for, and proposes deleting a note that
another, better-founded note contradicts; the maintainer applies the ones they agree with.

### Edge Cases

- More than 100 matches: the list stops and offers a command that lists everything
  (FR-002).
- The notes tool is missing or fails: the view says so, with the tool's message (FR-004).
- The index is updating: an "indexing" badge shows (FR-004).
- Other notes rest on a note that is deleted: they lose their CURRENT label with it
  (FR-007).
- A proposed delete names no note that shows it wrong: it is refused (FR-008).

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
  from the hub. Notes shows only notes the maintainer may see.
- **FR-007**: The maintainer can delete a note from Notes after confirming, with a short
  reason. The note's text is gone from the notes; a line with its id, the date and the
  reason stays in its topic's history, and notes that rested on it lose their CURRENT
  label.
- **FR-008**: A session that finds two notes contradicting each other proposes deleting
  (or retracting) the one that is wrong, naming the note that shows it wrong; the proposal
  waits for the maintainer like any other note operation.

### Key Entities

- **Note**: a shared note with a title, topic, date, body and trust label.
- **Trust label**: how far a note can be relied on: CURRENT, OPEN QUESTION, HISTORY,
  RETRACTED, ARCHIVE·UNREVIEWED or NO STATUS.
- **Note operation**: a proposed change (merge, distil, answer, supersede, retract,
  delete, ...) with the command it stands for.

## Success Criteria

No criteria of its own; App frame (001) SC-004 (keyboard-only pass) and App frame (001)
SC-003 (phone width) apply.

## Assumptions

- A notes tool on the maintainer's machine holds the notes, searches them and applies
  operations; the hub shows its results and its messages as they are.
- Compact is done by an Archivist session and Sweep by a docs-writer session; both are
  read-only and post nothing (Launch (005)).
- The hub runs on the maintainer's own machine and touches no device.
- A deleted note's text stays in the notes tool's own history, so a delete can be undone
  by hand outside the hub.
