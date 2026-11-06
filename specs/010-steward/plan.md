# Implementation Plan: Steward

**Branch**: `001-hub-app` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/010-steward/spec.md`

Honest framing: this plan was written by an AI agent from a reading of the code at `c81fe71`
(`make check` green there: 1509 passed, 1 skipped). Nothing in it was tried in a browser, with a
real `claude` or against real GitHub. Each PR says what it must try for real.

## Summary

The panel is resizable and remembered per viewer (001 R2), shows the Steward in the compact
SessionView, and tells it the current view's context including the selected repositories.

## Technical Context

As in [001 plan](../001-app-frame/plan.md) § Technical Context (languages, dependencies, storage,
testing, platform, constraints, scale).

## Constitution Check

The table in [001 plan](../001-app-frame/plan.md) § Constitution Check holds for this spec.

## Source code this spec touches

`app/hub/static/app.js` (`Steward`, `StewardSession`, `StewardModel`, `seenFrom`, `keptRail`),
`app/hub/static/style.css`, `hubd/agents.py` (`set_context` repos), `tests/test_app.py`,
`tests/test_agents.py`.

## PR stack (detail in tasks.md)

| # | PR | Size | Depends on | Status |
|---|---|---|---|---|
| 1 | Steward panel | M | 004/PR 3, 005/PR 2 | to build |

## Complexity Tracking

No constitution violations to justify.
