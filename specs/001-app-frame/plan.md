# Implementation Plan: App frame

**Branch**: `001-hub-app` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-app-frame/spec.md`

Honest framing: this plan was written by an AI agent from a reading of the code at `c81fe71`
(`make check` green there: 1509 passed, 1 skipped). Nothing in it was tried in a browser, with a
real `claude` or against real GitHub. Each PR says what it must try for real.

## Summary

The hub already has most views as separate screens (`app/hub/static/app.js`, 2817 lines) and much
of the backend (sessions, asks, decisions, new work, the merge gate, threads, diffs, workflows).
The ten specs reshape the app around four shared building blocks (Item, Launch, Session,
Interaction), move Needs you into one modal fed by one interaction projection, turn every Claude
session into a chat, record every Launch in hubd, add typed results, and rebuild each view on
the blocks. They ship as a stack of 20 PRs (`specs/README.md`), dependencies first, each leaving
`make check` green and the app usable.

This spec's part: the dev hubd port for parallel test runs, the header and navigation (with the
usage meter and the device lock card that replaces the Device page, 007 R1), the phone layout and the
final cross-cutting checks.

Approach per layer, for all ten specs:

- **hubd** (stdlib, the boundary): extend, don't replace. `NewWork` becomes the Launch record store
  (005 R1); a new `Results` store and `submit_result` tool (005 R2); `interaction.list` projects asks,
  decisions, offers and results (003 R1); `covers[]`, `view`, `origin` on sessions (004 R1); `agent.say`
  (004 R2); `notes.apply` (009 R1); `usage.status` (R1).
- **app container** (`app/hub/*.py`): new reads in `github.py`, exposed in both `web.py` and
  `tools.py` where agents need them (`CLAUDE.md`); GhActions writes go out as the login.
- **front end** (`app.js`, `style.css`): shared components first, then one view per PR, each
  replacing the old screen in the same PR.

## Technical Context

**Language/Version**: Python 3 (hubd: standard library only; app: Starlette, uvicorn, the MCP SDK,
pinned in `pyproject.toml:9`); JavaScript in the browser (Preact + htm from `app/fetch-vendor.sh`,
no build step); CSS.

**Primary Dependencies**: Starlette 1.10, `mcp` 2.3 (tool server, `app/hub/tools.py`), xterm.js
(terminal), `gh` CLI (consumed, not pinned), Claude Code CLI (consumed, not pinned), the `notes` CLI
from the workspace repository (consumed), the GlassineOS search index (consumed). No new
dependency.

**Storage**: JSON files under hubd's state folder (`sessions/`, `newwork/`, `decisions/`, new
`results/`), the work store SQLite (`app/hub/workstore.py`), browser `localStorage` /
`sessionStorage` for per-viewer conveniences only (R2). No database is added.

**Testing**: `make check` = `node --check app/hub/static/app.js` + `pytest -q`; in the worktree
`make check PYTHON=.venv/bin/python`. Fakes: `FakeHubd` (`tests/test_app.py`), the fake Claude CLI
(`tests/test_agents.py:97`), `tests/dev_hubd.py`. Browser checks by hand at 1440 px and 390 px
against `.dev/run.sh` (quickstart.md), recorded in each PR.

**Target Platform**: the maintainer's Linux host; desktop browser and a phone browser; an e-ink
browser must stay usable (FR-018).

**Project Type**: web application (single-page front end, Python web app, host daemon).

**Performance Goals**: 003 SC-002 an interaction reaches the header and Needs you within 5 s (3 s
poll); SC-002 Overview and Work first screen under 2 s with 60 repositories and 500 open items,
served from the work store (`github._serving()`, `app/hub/github.py:204`).

**Constraints**: hubd stdlib only; ghpolicy fails closed; the browser holds no credentials
(FR-021); agent text never widens rights (FR-024); tool and action changes safe for running
sessions; no motion needed to read state (FR-018); no half-migrated screen on `main`.

**Scale/Scope**: one maintainer; up to ~60 repositories; hundreds of open items; up to ~20 live
sessions, 4 started by the Steward at once (`MAX_STARTED`, `hubd/agents.py:103`).

The other specs' plans add only what is specific to them; this technical context holds for all
ten. No NEEDS CLARIFICATION remain: open questions are settled in each spec's research.md. Two
need the maintainer's yes before their PR: the GitHub budget leaving the header (this spec,
before PR 2) and results instead of direct posting (005, before 005/PR 1).

## Constitution Check

*GATE: before Phase 0, and again after Phase 1 design.*

| Principle | How the ten specs meet it | Status |
|---|---|---|
| I Honest framing | Plans, research and every PR say what was read vs tried; consumed behaviours (status line, paste, planner schema, `gh pr edit`) are marked "try for real" | pass |
| II Safety before features | No device action. The hub reads the device lock only (007 R1). Go cards keep `decisions.py`'s rules (eye test never "always") | pass |
| III Nothing vendor-owned or personal | Fixtures use made-up logins and paths; safety scan before each commit | pass |
| IV Contracts owned and versioned | Web API and socket internal, ship together; tool/action changes additive with a running-session rule (`contracts/tool-server-and-library.md`); `notes stats` belongs to the workspace repository and is asked for there, with a fallback here (009 R1) | pass |
| V Test at the right level | Host tests per PR (web API with `FakeHubd`, hubd with the fake CLI, policy, static app checks). No product-level tests: the hub isn't in an image | pass |
| VI Device-neutral | No device names in code; devices come from reports | pass |
| VII E-ink first | No animation needed to read state; reduced motion honoured; polls, no streaming redraws; state in outline, icon and words | pass |
| VIII Upstream and licenses | SPDX GPL-2.0-or-later headers on new files; `Assisted-by:` trailers | pass |
| Repo: security boundary | New writes (`agent.say`, `result.apply`, `notes.apply`, `interaction.answer`) are login ops in hubd; `submit_result` is a token op held to the action's own result type; GhActions run as the login; `SECURITY.md` changes ship in the PRs that change who can do what (004/PR 2, 005/PR 1, 009/PR 1) | pass |
| Repo: ghpolicy allowlist | New entries (`pr edit` with labels only, `pr reopen`, `@me` assignee narrowing) and one GraphQL document, each with allowed + refused tests (006 `contracts/gh-calls.md`) | pass |
| Repo: contracts safe for running sessions | Old `also_numbers` read; `submit_drafts` kept; running sessions keep their tool lists; old routes kept one release | pass |
| Repo: departures said first | Listed in each spec's plan, before any PR is built | pass |

Post-design re-check: the design adds one store module and one GraphQL document, no hubd
dependency, and no path by which agent text reaches a write without a login. Still pass. The
other plans refer to this table.

### Departures from the spec (said before building)

1. **FR-006** reads Claude Code's status-line JSON, which isn't pinned; the GitHub API budget leaves
   the header for Overview (R1). **Maintainer's yes on dropping the GitHub budget from the header.**

## Source code this spec touches

```text
hubd/                      # host daemon, stdlib only, the security boundary
├── server.py              # op routing; login gate at :200; new interaction./result./usage. ops
├── agents.py              # sessions: covers, view, origin, say, status line, families
├── asks.py                # storage unchanged; projected
├── decisions.py           # rules unchanged; projected
├── newwork.py             # becomes the Launch record store (v2 fields)
├── results.py             # NEW: typed results
├── notes.py               # adds apply and totals
├── shells.py              # paste through stdin
├── ghpolicy.py            # pr edit (labels), pr reopen, @me narrowing
└── graphql/pr_review_add.graphql   # NEW
app/hub/
├── web.py                 # routes in each spec's contracts/web-api.md
├── github.py              # behind count, blockers, labels, failed step, workflow inputs, Part-of progress
├── tools.py               # submit_result; covers on suggest_session
└── static/
    ├── app.js             # components and views (one file)
    └── style.css          # family tints, night paper, phone sheets
agents/
├── actions/*.toml         # verb, result; run-fix, knowledge-research, notes-compact, notes-sweep
├── prompts/*.md           # hand-in instructions for new and changed actions
└── personas/              # families.toml; ci-fixer, researcher, archivist
tests/                     # extended per PR (each spec's tasks.md)
SECURITY.md, docs/orchestrator.md   # changed in 004/PR 2, 005/PR 1, 009/PR 1
```

**Structure Decision**: the existing three-part layout (hubd / app / static front end) stays. No new
top-level directory; one new hubd module and one GraphQL document. This spec's own PRs touch
`tests/dev_hubd.py`, the header and navigation in `app.js`, `style.css`, `hubd/agents.py`
(`SCREENS`, status line), `hubd/server.py` (`ping`, `usage.status`) and `app/hub/web.py`.

## PR stack (detail in tasks.md)

| # | PR | Size | Depends on | Status |
|---|---|---|---|---|
| 1 | Dev hubd: configurable tool server port | S | — | done (hub #26) |
| 2 | Header and navigation | M | 003/PR 1 | to build |
| 3 | Phone ≤ 760 px | M | 010/PR 1 | to build |
| 4 | Cross-cutting checks and leftovers | S | PR 3 | to build |

## Complexity Tracking

No constitution violations to justify.
