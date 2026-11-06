# Implementation Plan: Work

**Branch**: `001-hub-app` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/006-work/spec.md`

Honest framing: this plan was written by an AI agent from a reading of the code at `c81fe71`
(`make check` green there: 1509 passed, 1 skipped). Nothing in it was tried in a browser, with a
real `claude` or against real GitHub. Each PR says what it must try for real.

## Summary

GitHub reads go through the already allowed read-only `gh api` path; three new write shapes and one
narrowing join the allowlist, each with allowed and refused tests (R1). The Work item comes before
the Work list because the row action rule and GhActions are defined there.

## Technical Context

As in [001 plan](../001-app-frame/plan.md) § Technical Context (languages, dependencies, storage,
testing, platform, constraints, scale).

## Constitution Check

The table in [001 plan](../001-app-frame/plan.md) § Constitution Check holds for this spec.

Specific to this spec:

- ghpolicy allowlist: `pr edit` with labels only, `pr reopen`, `@me` assignee narrowing, each with
  allowed and refused tests (`contracts/gh-calls.md`).

### Departures from the spec (said before building)

1. **FR-004 issue groups** (Untriaged, In sessions, Backlog) replace today's (Needs you, Untriaged,
   Everything else, `app.js:978-982`); issues assigned to you lose their own group. Built as the
   spec says.

## Source code this spec touches

`app/hub/static/app.js` (`ItemFrame`, `IssueDetail`, `PrDetail`, `RunDetail`, `Threads`, `Comment`,
`Labels`, `WorkLists`, `WorkRow`, `NewIssue`, `Dispatch`, `WorkQueue`), `app/hub/github.py`,
`app/hub/web.py`, `app/hub/tools.py`, `hubd/ghpolicy.py`, `agents/actions/run-fix.toml` (new),
`agents/prompts/run-fix.md` (new), `hubd/agents.py` (run-fix checkout), `SECURITY.md`, tests.

## PR stack (detail in tasks.md)

| # | PR | Size | Depends on | Status |
|---|---|---|---|---|
| 1 | Work item | L | 004/PR 3, 005/PR 2 | to build |
| 2 | Work | M | PR 1 | to build |

## Complexity Tracking

No constitution violations to justify.
