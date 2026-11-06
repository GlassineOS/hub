# Implementation Plan: Knowledge

**Branch**: `001-hub-app` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/008-knowledge/spec.md`

Honest framing: this plan was written by an AI agent from a reading of the code at `c81fe71`
(`make check` green there: 1509 passed, 1 skipped). Nothing in it was tried in a browser, with a
real `claude` or against real GitHub. Each PR says what it must try for real.

## Summary

Knowledge is a view over the two indexes that exist (docs and work items), searched in parallel, with
Code shown as planned (R1). A new locked research action hands in a report result that is kept and
listed.

## Technical Context

As in [001 plan](../001-app-frame/plan.md) § Technical Context (languages, dependencies, storage,
testing, platform, constraints, scale).

## Constitution Check

The table in [001 plan](../001-app-frame/plan.md) § Constitution Check holds for this spec.

## Source code this spec touches

`app/hub/static/app.js` (`Docs`, `DocsSearch`, `DocsTabs`), `app/hub/web.py`, `app/hub/github.py`,
`app/hub/docsearch.py` (status only), `agents/actions/knowledge-research.toml` (new),
`agents/prompts/knowledge-research.md` (new), `hubd/agents.py` (`object = "knowledge"`),
`app/hub/tools.py` (`plan_work`), tests.

## PR stack (detail in tasks.md)

| # | PR | Size | Depends on | Status |
|---|---|---|---|---|
| 1 | Knowledge | L | 005/PR 2 | to build |

## Complexity Tracking

No constitution violations to justify.
