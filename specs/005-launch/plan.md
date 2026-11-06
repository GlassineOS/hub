# Implementation Plan: Launch

**Branch**: `001-hub-app` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/005-launch/spec.md`

Honest framing: this plan was written by an AI agent from a reading of the code at `c81fe71`
(`make check` green there: 1509 passed, 1 skipped). Nothing in it was tried in a browser, with a
real `claude` or against real GitHub. Each PR says what it must try for real.

## Summary

Every Launch becomes a record in the NewWork store, extended to item actions and `covers` (R1).
Sessions hand in a typed result through a new tool; a login applies it within the producing action's
own tools (R2). The backend PR comes first and doesn't touch `app.js`; the Launch UI PR replaces
Spawn, NewWork, StartForm and the advanced launch in one go.

## Technical Context

As in [001 plan](../001-app-frame/plan.md) § Technical Context (languages, dependencies, storage,
testing, platform, constraints, scale).

## Constitution Check

The table in [001 plan](../001-app-frame/plan.md) § Constitution Check holds for this spec.

Specific to this spec:

- Security boundary: `submit_result` is a token op held to the action's own result type;
  `result.apply` is a login op that writes only through the producing action's tools (R2);
  `SECURITY.md` changes in PR 1.

### Departures from the spec (said before building)

1. **FR-017 / FR-018**: `pr-review` and `issue-triage` stop writing directly and hand in a result
   the person applies; running sessions keep their old tools (R3). **Needs the maintainer's yes
   before PR 1.**

## Source code this spec touches

`hubd/newwork.py` (Launch record store, v2 fields), `hubd/results.py` (new),
`hubd/graphql/pr_review_add.graphql` (new), `hubd/server.py`, `hubd/agents.py` (`Library.schema`,
`_prompt`, `plan`), `app/hub/web.py`, `app/hub/github.py`, `app/hub/tools.py` (`submit_result`),
`agents/actions/*.toml` and `agents/prompts/*.md` (hand-in), `app/hub/static/app.js` (Launch modal),
`SECURITY.md`, `docs/orchestrator.md`, tests.

## PR stack (detail in tasks.md)

| # | PR | Size | Depends on | Status |
|---|---|---|---|---|
| 1 | Launch records, stages and results: backend | L | 004/PR 1, 003/PR 1 | to build |
| 2 | Launch UI | L | PR 1, 004/PR 3 | to build |

## Complexity Tracking

No constitution violations to justify.
