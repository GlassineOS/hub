---
description: "Task list for spec 001 (app frame), as a stack of pull requests"
---

# Tasks: App frame

**Input**: `specs/001-app-frame/` — spec.md, plan.md, research.md, data-model.md, contracts/; the dev hub and browser checks are in `specs/001-app-frame/quickstart.md`.

**Organization**: by **pull request**. The format (`[P]`, `[US#]`), the tests rule and the three
steps every PR ends with are in [`specs/README.md`](../README.md) § Tasks. `[USk]` is this spec's
scenario k, `[NNN/USk]` another spec's; `NNN/PR k` is another spec's PR.

## Scenario → PR map

| Scenario | PRs |
|---|---|
| US1 Use it on a phone (P2) | PR 3 |

## Decisions needed before building

- **Before PR 2:** the maintainer agrees the GitHub API budget leaves the header (R1, plan.md Departures).

## Requirements of this spec built by other specs' PRs

- 002/PR 2 — Shared components: FR-011, FR-012, FR-015
- 003/PR 1 — Interactions, Feed and the Needs-you modal: FR-011
- 004/PR 3 — SessionView: FR-014
- 005/PR 2 — Launch UI: FR-010
- 006/PR 1 — Work item: FR-013
- 006/PR 2 — Work: FR-019
- 007/PR 1 — Overview: FR-019

---

## PR 1 — Dev hubd: configurable tool server port (S) — done (hub #26)

**Delivers**: Implementation notes, the dev hubd tool server port (parallel test runs). **Depends on**: —.
**Browser check**: none (start `.dev/run.sh`, sign in once).

- [x] T001 Take the tool server URL from `DEV_MCP_URL` (default `http://127.0.0.1:19095/mcp`) instead of the literal at `tests/dev_hubd.py:30`
- [x] T002 Pass `HUB_AGENT_PORT` through to `DEV_MCP_URL` in `.dev/run.sh` (local, not committed) and say so in `quickstart.md` §2
- [x] T003 Add a test in `tests/test_hubd.py` that imports `tests/dev_hubd.py`'s config builder with `DEV_MCP_URL` set and sees it used (split the builder out of `main()` so it can be imported)

---

## PR 2 — Header and navigation (M)

**Delivers**: FR-001–FR-006, 007 FR-003, FR-003, FR-004 (opens today's NewWork until 005/PR 2), FR-020
(disconnected state). **Depends on**: 003/PR 1. **Scenarios**: 003/US1, 003/US2. **Files**: `app/hub/static/app.js`
(`NAV`, `Hub`, `Budget`, `DeviceView`, `Overview`, `SEEN_SCREEN`, `seenFrom`, `Docs`/`NotesPage`
routing), `app/hub/static/style.css`, `hubd/agents.py` (`SCREENS`, status line), `hubd/server.py`
(`ping`, `usage.status`), `app/hub/web.py`, `agents/personas/steward-buttons.toml`,
`tests/test_app.py`, `tests/test_agents.py`. **Browser check**: quickstart rows "After 001/PR 2".

- [ ] T004 [003/US1] Set `NAV` (`app.js:2640`) to `overview, roadmap, work, knowledge, notes, shells` labelled Overview, Roadmap, Work, Knowledge, Notes, Sessions; `knowledge` renders today's `Docs` search view and `notes` today's `NotesPage` (`app.js:2609`) on its own route; old `#/docs`, `#/docs?tab=notes`, `#/notes`, `#/device` addresses redirect (extend the legacy map at `app.js:2788-2794`)
- [ ] T005 [003/US1] Header "Needs you N" button: yellow only when something is blocking, outlined when N > 0 and nothing blocks, plain at 0, state in its accessible name (FR-002); opens `NeedsYouModal`; remove the temporary Sessions entry from 003/PR 1
- [ ] T006 Header "＋ New work" (pen blue) opening today's `NewWork` with an empty brief (`planWork()`, `app.js:1481`) until 005/PR 2 replaces it (FR-004)
- [ ] T007 Header user line with the hubd address from `ping` (add `socket` to the reply in `hubd/server.py`); when `/api/host` or the interactions poll fails, a plain "hubd can't be reached — showing what was last read" banner (FR-005, FR-020)
- [ ] T008 Usage meter: status-line command in `_hooks`/settings (`hubd/agents.py:841-862`) writing `status.json` (≤ 16 KiB); `usage.status` op (login, `usage.` prefix added at `hubd/server.py:200`); `GET /api/usage`; small `UsageMeter` replacing `Budget` in the header (`app.js:2415`), words + bar, "low" at 80 % (FR-006, R1)
- [ ] T009 Move the GitHub API budget into Overview's stats line (`Overview`, `app.js:388-395`)
- [ ] T010 [003/US2] Device lock card on Overview from `GET /api/device` (`app/hub/web.py:151`) and `decision.holding`: lock line in words with its age, "you hold it", the Go in force; remove `DeviceView` (`app.js:2426-2440`) (007 FR-003, 007 R1)
- [ ] T011 Rename screens: `SCREENS` (`hubd/agents.py:130`) → `Overview, Roadmap, Work, Knowledge, Notes, Sessions, Queue`; `SEEN_SCREEN` and `seenFrom` (`app.js:2645-2657`); `screen` values in `agents/personas/steward-buttons.toml`; a stale `Docs` from an old page maps to `Knowledge`
- [ ] T012 Tests in `tests/test_app.py`: NAV pinned to the six entries in order; `DeviceView` gone and `#/device` redirects; header button classes for blocking / pending / none; `seenFrom` maps knowledge and notes; `tests/test_agents.py`: `set_context` accepts Knowledge and Notes, refuses Device and Decisions; the status-line command writes only inside the session folder; `usage.status` with no file says not known, with a fixture computes `low`

---

## PR 3 — Phone ≤ 760 px (M)

**Delivers**: FR-007–FR-010, FR-017, FR-018, SC-003, US1. **Depends on**: 010/PR 1. **Files**:
`app/hub/static/style.css` (breakpoints `style.css:279`, `:284` → 760), `app/hub/static/app.js`
(`Hub` header, `Steward`, modal/sheet class), `tests/test_app.py`. **Browser check**: quickstart
"After 001/PR 3", every view at 390 px.

- [ ] T013 [US1] Header at ≤ 760 px: "New" and "Menu" only; Menu is a sheet with the nav, Needs you and the user line (FR-007)
- [ ] T014 [US1] Steward as a floating button opening a full sheet (FR-008)
- [ ] T015 [US1] Single column, 16 px gutters, no sideways page scroll; diffs, logs, terminals scroll in their own box (FR-009)
- [ ] T016 [US1] Launch, Needs you and flyouts open as full sheets (FR-010); touch targets ≥ 44 × 44 px (FR-017)
- [ ] T017 `prefers-reduced-motion` turns transitions off; nothing relies on motion (FR-018)
- [ ] T018 Static tests: one `@media (max-width: 760px)` block holds the phone rules; no fixed widths over 360 px outside scroll boxes in that block

---

## PR 4 — Cross-cutting checks and leftovers (S)

**Delivers**: FR-011–FR-020 (checks), FR-021–FR-025 (re-asserted), 006 SC-001, 002 SC-001, SC-004.
**Depends on**: PR 3. **Files**: `tests/test_app.py`, `app/hub/static/app.js`,
`app/hub/static/style.css`, `app/hub/web.py`. **Browser check**: keyboard-only pass of
the P1 scenarios (003/US1, 005/US1, 006/US1, 006/US2) (quickstart "After 001/PR 4").

- [ ] T019 Static test: `--mark`/`#ffd86b` used only in rules for waiting states (FR-011)
- [ ] T020 Static test: every `<button>` and link in `app.js` has text or an `aria-label`; modals use the shared focus trap (FR-015, FR-016)
- [ ] T021 Static test: GitHub writes in `app.js` (`post(\`prs/…\`)`, `issues/…`, `runs/…`, `workflows/…`) are only called from `GhActions` and its forms (006 SC-001)
- [ ] T022 Remove routes kept for old pages: `/api/asks`, `/api/decisions` reads from the app (keep the routes if `tools`/tests still need them), `/api/agents/plan`, `/api/agents/start`, `/api/agents/run` from the page; the `#/launch`, `#/decisions`, `#/device` redirects stay
- [ ] T023 Re-assert security tests still pass unchanged: login for every write, same origin, Host allowlist, CSP (`tests/test_app.py:258-330`); add one for `/api/interactions/{id}/answer` from another origin (FR-021–FR-025)

---

## Dependencies

- PR 1 — Dev hubd: configurable tool server port: depends on —
- PR 2 — Header and navigation: depends on 003/PR 1
- PR 3 — Phone ≤ 760 px: depends on 010/PR 1
- PR 4 — Cross-cutting checks and leftovers: depends on PR 3

The build order of all PRs across the ten specs is in [`specs/README.md`](../README.md).
