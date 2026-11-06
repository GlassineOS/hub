# Implementation Plan: Hub app

**Branch**: `001-hub-app` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-hub-app/spec.md`

Honest framing: this plan was written by an AI agent from a reading of the code at `c81fe71`
(`make check` green there: 1509 passed, 1 skipped). Nothing in it was tried in a browser, with a
real `claude` or against real GitHub. Each PR in the stack says what it must try for real.

## Summary

The hub already has most views as separate screens (`app/hub/static/app.js`, 2817 lines) and much
of the backend (sessions, asks, decisions, new work, the merge gate, threads, diffs, workflows).
This feature reshapes the app around four shared building blocks (Item, Launch, Session,
Interaction), moves Needs you into one modal fed by one interaction projection, turns every Claude
session into a chat, records every Launch in hubd, adds typed results, and rebuilds each view on
the blocks. It ships as a stack of 20 PRs, dependencies first, each leaving `make check` green and
the app usable.

Approach per layer:

- **hubd** (stdlib, the boundary): extend, don't replace. `NewWork` becomes the Launch record store
  (R6); a new `Results` store and `submit_result` tool (R8); `interaction.list` projects asks,
  decisions, offers and results (R3); `covers[]`, `view`, `origin` on sessions (R4); `agent.say`
  (R5); `notes.apply` (R12); `usage.status` (R7).
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
`sessionStorage` for per-viewer conveniences only (R15). No database is added.

**Testing**: `make check` = `node --check app/hub/static/app.js` + `pytest -q`; in the worktree
`make check PYTHON=.venv/bin/python`. Fakes: `FakeHubd` (`tests/test_app.py`), the fake Claude CLI
(`tests/test_agents.py:97`), `tests/dev_hubd.py`. Browser checks by hand at 1440 px and 390 px
against `.dev/run.sh` (quickstart.md), recorded in each PR.

**Target Platform**: the maintainer's Linux host; desktop browser and a phone browser; an e-ink
browser must stay usable (FR-171).

**Project Type**: web application (single-page front end, Python web app, host daemon).

**Performance Goals**: SC-002 an interaction reaches the header and Needs you within 5 s (3 s
poll); SC-006 Overview and Work first screen under 2 s with 60 repositories and 500 open items,
served from the work store (`github._serving()`, `app/hub/github.py:204`).

**Constraints**: hubd stdlib only; ghpolicy fails closed; the browser holds no credentials
(FR-174); agent text never widens rights (FR-177); tool and action changes safe for running
sessions; no motion needed to read state (FR-171); no half-migrated screen on `main`.

**Scale/Scope**: one maintainer; up to ~60 repositories; hundreds of open items; up to ~20 live
sessions, 4 started by the Steward at once (`MAX_STARTED`, `hubd/agents.py:103`).

No NEEDS CLARIFICATION remain: open questions are settled in `research.md` R1–R17. Two of them
need the maintainer's yes before their PR (Departures 2 and 5 below).

## Constitution Check

*GATE: before Phase 0, and again after Phase 1 design.*

| Principle | How this plan meets it | Status |
|---|---|---|
| I Honest framing | Plan, research and every PR say what was read vs tried; consumed behaviours (status line, paste, planner schema, `gh pr edit`) are marked "try for real" | pass |
| II Safety before features | No device action. The hub reads the device lock only (R11). Go cards keep `decisions.py`'s rules (eye test never "always") | pass |
| III Nothing vendor-owned or personal | Fixtures use made-up logins and paths; safety scan before each commit | pass |
| IV Contracts owned and versioned | Web API and socket internal, ship together; tool/action changes additive with a running-session rule (`contracts/tool-server-and-library.md`); `notes stats` belongs to the workspace repository and is asked for there, with a fallback here (R12) | pass |
| V Test at the right level | Host tests per PR (web API with `FakeHubd`, hubd with the fake CLI, policy, static app checks). No product-level tests: the hub isn't in an image | pass |
| VI Device-neutral | No device names in code; devices come from reports | pass |
| VII E-ink first | No animation needed to read state; reduced motion honoured; polls, no streaming redraws; state in outline, icon and words | pass |
| VIII Upstream and licenses | SPDX GPL-2.0-or-later headers on new files; `Assisted-by:` trailers | pass |
| Repo: security boundary | New writes (`agent.say`, `result.apply`, `notes.apply`, `interaction.answer`) are login ops in hubd; `submit_result` is a token op held to the action's own result type; GhActions run as the login; `SECURITY.md` changes ship in the PRs that change who can do what (PR 6, 7, 16) | pass |
| Repo: ghpolicy allowlist | New entries (`pr edit` with labels only, `pr reopen`, `@me` assignee narrowing) and one GraphQL document, each with allowed + refused tests (`contracts/gh-calls.md`) | pass |
| Repo: contracts safe for running sessions | Old `also_numbers` read; `submit_drafts` kept; running sessions keep their tool lists; old routes kept one release | pass |
| Repo: departures said first | Listed below, before any PR is built | pass |

Post-design re-check: the design adds one store module and one GraphQL document, no hubd
dependency, and no path by which agent text reaches a write without a login. Still pass.

### Departures from the spec (said before building)

1. **FR-059 closed action list**: actions not in the table stay, under "More…" (R2).
2. **FR-064 / FR-065**: `pr-review` and `issue-triage` stop writing directly and hand in a result
   the person applies; running sessions keep their old tools (R9). **Needs the maintainer's yes
   before PR 7.**
3. **FR-136 totals per label and topic** need `notes stats` in the workspace repository; until it
   exists the flyout counts the last search and says so (R12).
4. **FR-027 "never as a command-line argument"**: today's paste puts the text in tmux's argv
   (`hubd/shells.py:118`); PR 6 moves it to stdin.
5. **FR-086a** reads Claude Code's status-line JSON, which isn't pinned; the GitHub API budget leaves
   the header for Overview (R7). **Maintainer's yes on dropping the GitHub budget from the header.**
6. **FR-102 issue groups** (Untriaged, In sessions, Backlog) replace today's (Needs you, Untriaged,
   Everything else, `app.js:978-982`); issues assigned to you lose their own group. Built as the
   spec says.

## Project Structure

### Documentation (this feature)

```text
specs/001-hub-app/
├── spec.md
├── plan.md              # this file
├── research.md          # R1–R17
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── web-api.md
│   ├── hubd-socket.md
│   ├── tool-server-and-library.md
│   └── gh-calls.md
├── checklists/requirements.md
└── tasks.md             # the PR stack
```

### Source code (what the stack touches)

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
├── web.py                 # routes in contracts/web-api.md
├── github.py              # behind count, blockers, labels, failed step, workflow inputs, Part-of progress
├── tools.py               # submit_result; covers on suggest_session
└── static/
    ├── app.js             # components and views (one file)
    └── style.css          # family tints, night paper, phone sheets
agents/
├── actions/*.toml         # verb, result; run-fix, knowledge-research, notes-compact, notes-sweep
├── prompts/*.md           # hand-in instructions for new and changed actions
└── personas/              # families.toml; ci-fixer, researcher, archivist
tests/                     # extended per PR (tasks.md)
SECURITY.md, docs/orchestrator.md   # changed in PRs 6, 7, 16
```

**Structure Decision**: the existing three-part layout (hubd / app / static front end) stays. No new
top-level directory; one new hubd module and one GraphQL document.

## PR stack (summary; detail in tasks.md)

| # | PR | Size | Depends on |
|---|---|---|---|
| 0 | Dev hubd tool port configurable | S | — |
| 1 | Persona families and action metadata | S | 0 |
| 2 | Shared components (ItemPill, PersonaBadge, SessionChip, RepoPicker, ItemPicker) | M | 1 |
| 3 | Session covers[], prs[], view, origin | M | 1 |
| 4 | Interactions, Feed, Needs-you modal (Decisions, Go, grants folded in) | L | 2, 3 |
| 5 | Header and navigation (+ device lock on Overview, usage meter) | M | 4 |
| 6 | Typed messages (chat) | S | 5 |
| 7 | Launch records, stages and results (backend) | L | 3, 4 |
| 8 | SessionView | L | 2, 6, 7 |
| 9 | Launch UI (replaces Spawn, NewWork, StartForm, advanced launch) | L | 7, 8 |
| 10 | Sessions › Running and History & cleanup | M | 8 |
| 11 | Work item (GhActions, details, files diff, run log, sessions on it) | L | 8, 9 |
| 12 | Work (lists, row action, Queue, New issue, Run workflow, run-fix) | M | 11 |
| 13 | Overview | M | 2, 5 |
| 14 | Roadmap | M | 9 |
| 15 | Knowledge (search, pins, research, reports, indexes) | L | 9 |
| 16 | Notes (own view, upkeep, compact/sweep, apply ops) | L | 9 |
| 17 | Steward panel | M | 8, 9 |
| 18 | Phone ≤ 760 px | M | 17 |
| 19 | Cross-cutting checks (yellow rule, keyboard, focus, legacy routes out) | S | 18 |

The suggested order was kept with two changes the code forces: SessionView comes **before** the
Launch UI (the run stage embeds a compact SessionView, FR-054), and the device lock card lands
with the Header PR, which removes the Device page (R11). PRs 13–16 only share `app.js`; they have no
logical dependency on each other and can be reordered.

## Complexity Tracking

No constitution violations to justify.
