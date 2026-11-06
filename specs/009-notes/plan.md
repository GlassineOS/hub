# Implementation Plan: Notes

**Branch**: `001-hub-app` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/009-notes/spec.md`

Honest framing: this plan was written by an AI agent from a reading of the code at `c81fe71`
(`make check` green there: 1509 passed, 1 skipped). Nothing in it was tried in a browser, with a
real `claude` or against real GitHub. Each PR says what it must try for real.

## Summary

Notes gets its own route with the search limits and every state. Note operations map onto the `notes`
CLI's existing verbs, applied by a login op with a closed list and no deletes; totals come from
`notes stats` when the workspace tool has it, else from the last search (R1).

## Technical Context

As in [001 plan](../001-app-frame/plan.md) § Technical Context (languages, dependencies, storage,
testing, platform, constraints, scale).

## Constitution Check

The table in [001 plan](../001-app-frame/plan.md) § Constitution Check holds for this spec.

Specific to this spec:

- Security boundary: `notes.apply` is hubd's first notes write: login only, closed ops, no deletes;
  `SECURITY.md` "Notes" changes in PR 1.

### Departures from the spec (said before building)

1. **FR-005 totals per label and topic** need `notes stats` in the workspace repository; until it
   exists the flyout counts the last search and says so (R1).

## Source code this spec touches

`app/hub/static/app.js` (`NotesPage`), `hubd/notes.py`, `hubd/server.py`, `app/hub/web.py`,
`agents/actions/notes-compact.toml`, `notes-sweep.toml` (new), prompts, `hubd/agents.py`
(`object = "notes"`), `SECURITY.md`, `tests/test_notes.py`, `tests/test_hubd.py`.

## PR stack (detail in tasks.md)

| # | PR | Size | Depends on | Status |
|---|---|---|---|---|
| 1 | Notes | L | 005/PR 2 | to build |

## Complexity Tracking

No constitution violations to justify.
