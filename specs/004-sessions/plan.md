# Implementation Plan: Sessions

**Branch**: `001-hub-app` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/004-sessions/spec.md`

Honest framing: this plan was written by an AI agent from a reading of the code at `c81fe71`
(`make check` green there: 1509 passed, 1 skipped). Nothing in it was tried in a browser, with a
real `claude` or against real GitHub. Each PR says what it must try for real.

## Summary

Sessions gain `covers[]` (across repositories), derived `prs[]`, a stored `view` and an `origin`
(R1). Typed messages reach a session through hubd on stdin (R2). The SessionView is one component in
three modes, adopted by Sessions, the Steward panel and Launch. Running and History & cleanup are
rebuilt on it.

## Technical Context

As in [001 plan](../001-app-frame/plan.md) § Technical Context (languages, dependencies, storage,
testing, platform, constraints, scale).

## Constitution Check

The table in [001 plan](../001-app-frame/plan.md) § Constitution Check holds for this spec.

Specific to this spec:

- Security boundary: `agent.say` is a login op; the text goes to tmux on stdin, never argv (R2);
  `SECURITY.md` and `docs/orchestrator.md` change in PR 2.

### Departures from the spec (said before building)

1. **FR-008 "never as a command-line argument"**: today's paste puts the text in tmux's argv
   (`hubd/shells.py:118`); PR 2 moves it to stdin.

## Source code this spec touches

`hubd/agents.py` (covers, view, origin, `_send`, `past`, cleanup), `hubd/shells.py` (paste on
stdin), `hubd/server.py`, `app/hub/web.py`, `app/hub/tools.py` (`list_running_sessions`),
`app/hub/static/app.js` (`TerminalView`, `Manifest`, `Shells`, `PastSessions`, `Cleanup`,
`NewShell`), `app/hub/static/style.css`, `SECURITY.md`, `docs/orchestrator.md`, tests.

## PR stack (detail in tasks.md)

| # | PR | Size | Depends on | Status |
|---|---|---|---|---|
| 1 | Session covers[], prs[], view, origin | M | 002/PR 1 | to build |
| 2 | Typed messages: sessions are chats | S | 001/PR 2 | to build |
| 3 | SessionView | L | 002/PR 2, PR 2, 005/PR 1 | to build |
| 4 | Sessions › Running and History & cleanup | M | PR 3 | to build |

## Complexity Tracking

No constitution violations to justify.
