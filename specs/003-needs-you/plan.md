# Implementation Plan: Needs you

**Branch**: `001-hub-app` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/003-needs-you/spec.md`

Honest framing: this plan was written by an AI agent from a reading of the code at `c81fe71`
(`make check` green there: 1509 passed, 1 skipped). Nothing in it was tried in a browser, with a
real `claude` or against real GitHub. Each PR says what it must try for real.

## Summary

One read op projects asks, decisions, offers and results into one Interaction shape (R1); one answer
op dispatches to the existing op of each source. The app polls it every 3 s and shows the cards in a
Feed inside the Needs-you modal, which replaces the Sessions › Needs you and Active tabs and the
Decisions page in the same PR.

## Technical Context

As in [001 plan](../001-app-frame/plan.md) § Technical Context (languages, dependencies, storage,
testing, platform, constraints, scale).

## Constitution Check

The table in [001 plan](../001-app-frame/plan.md) § Constitution Check holds for this spec.

Specific to this spec:

- Security boundary: `interaction.answer` is a login op that only dispatches; it adds no rule of its
  own, and `handled.where` is a page claim, never trusted (R1).

## Source code this spec touches

`hubd/server.py` (`interaction.list`, `interaction.answer`), `hubd/asks.py`, `hubd/decisions.py`,
`hubd/newwork.py` (projected, unchanged), `app/hub/web.py`, `app/hub/static/app.js` (`Ask`, `Inbox`,
`SessionTabs`, `ActiveDecisions`, `DecisionsPage`, `GoPanel`, `DecisionRow`, `Hub`),
`app/hub/static/style.css`, `tests/test_hubd.py`, `tests/test_app.py`.

## PR stack (detail in tasks.md)

| # | PR | Size | Depends on | Status |
|---|---|---|---|---|
| 1 | Interactions, Feed and the Needs-you modal | L | 002/PR 2, 004/PR 1 | to build |

## Complexity Tracking

No constitution violations to justify.
