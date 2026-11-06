# Implementation Plan: Building blocks

**Branch**: `001-hub-app` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-building-blocks/spec.md`

Honest framing: this plan was written by an AI agent from a reading of the code at `c81fe71`
(`make check` green there: 1509 passed, 1 skipped). Nothing in it was tried in a browser, with a
real `claude` or against real GitHub. Each PR says what it must try for real.

## Summary

Persona families and action metadata in the owned library (R1, R2), then the shared components
(ItemPill, PersonaBadge, SessionChip, RepoPicker, ItemPicker), each adopted in one existing place so
none is dead code. Both PRs are done (hub #27, #28).

## Technical Context

As in [001 plan](../001-app-frame/plan.md) § Technical Context (languages, dependencies, storage,
testing, platform, constraints, scale).

## Constitution Check

The table in [001 plan](../001-app-frame/plan.md) § Constitution Check holds for this spec.

Specific to this spec:

- Library data: `agents/personas/families.toml` is read by `Library` and refused when incomplete (R1).
- Components live in one section of `app.js` near the helpers (001 R3).

### Departures from the spec (said before building)

1. **005 FR-012 closed action list**: actions not in the table stay, under "More…" (R2).

## Source code this spec touches

`agents/personas/families.toml` (new), `agents/personas/ci-fixer.md`, `researcher.md`, `archivist.md`
(new), `agents/actions/*.toml`, `hubd/agents.py` (`Library`, `actions`, `describe()`), `hubd/server.py`
(`shell.list`), `app/hub/static/app.js` (component section), `app/hub/static/style.css`,
`tests/test_agents.py`, `tests/test_app.py`.

## PR stack (detail in tasks.md)

| # | PR | Size | Depends on | Status |
|---|---|---|---|---|
| 1 | Persona families and action metadata | S | 001/PR 1 | done (hub #27) |
| 2 | Shared components | M | PR 1 | done (hub #28) |

## Complexity Tracking

No constitution violations to justify.
