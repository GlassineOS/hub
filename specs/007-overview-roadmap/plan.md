# Implementation Plan: Overview and Roadmap

**Branch**: `001-hub-app` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/007-overview-roadmap/spec.md`

Honest framing: this plan was written by an AI agent from a reading of the code at `c81fe71`
(`make check` green there: 1509 passed, 1 skipped). Nothing in it was tried in a browser, with a
real `claude` or against real GitHub. Each PR says what it must try for real.

## Summary

Overview rows gain an attention sort key and are served from the work store; its device card reads
the lock in words (R1). Roadmap maps the project's Status options onto four columns and counts
progress from sub-issues and "Part of" lines (R2).

## Technical Context

As in [001 plan](../001-app-frame/plan.md) § Technical Context (languages, dependencies, storage,
testing, platform, constraints, scale).

## Constitution Check

The table in [001 plan](../001-app-frame/plan.md) § Constitution Check holds for this spec.

Specific to this spec:

- The device lock card itself is built in the header PR (001/PR 2), which removes the Device page, so the
  information never disappears (R1).

## Source code this spec touches

`app/hub/static/app.js` (`Overview`, `NeedsYou`, `RepoDetail`, `Roadmap`), `app/hub/github.py`
(`overview`, `_repo_row`, `project`, `_board`, `_rollup_subs`), `app/hub/workstore.py` (Part-of
query), `config/` (column map), `tests/test_app.py`, `tests/test_workstore.py`.

## PR stack (detail in tasks.md)

| # | PR | Size | Depends on | Status |
|---|---|---|---|---|
| 1 | Overview | M | 002/PR 2, 001/PR 2 | to build |
| 2 | Roadmap | M | 005/PR 2 | to build |

## Complexity Tracking

No constitution violations to justify.
