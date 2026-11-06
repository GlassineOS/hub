---
description: "Task list for spec 004 (sessions), as a stack of pull requests"
---

# Tasks: Sessions

**Input**: `specs/004-sessions/` — spec.md, plan.md, research.md, data-model.md, contracts/; the dev hub and browser checks are in `specs/001-app-frame/quickstart.md`.

**Organization**: by **pull request**. The format (`[P]`, `[US#]`), the tests rule and the three
steps every PR ends with are in [`specs/README.md`](../README.md) § Tasks. `[USk]` is this spec's
scenario k, `[NNN/USk]` another spec's; `NNN/PR k` is another spec's PR.

## Scenario → PR map

| Scenario | PRs |
|---|---|
| US1 Clean up old worktrees (P2) | PR 4 |
| US2 Resume a past session (P3) | PR 4 |

---

## PR 1 — Session covers[], prs[], view, origin (M)

**Delivers**: 002 FR-019 (data), FR-003 (data), FR-009 (fields), FR-010 (backend), 005 FR-009 (backend).
**Depends on**: 002/PR 1. **Scenario**: 005/US1. **Files**: `hubd/agents.py`, `hubd/server.py`,
`app/hub/web.py`, `app/hub/tools.py` (`list_running_sessions`), `app/hub/static/app.js`
(`sessionsOf`), `tests/test_agents.py`, `tests/test_hubd.py`, `tests/test_app.py`.
**Browser check**: Work rows still show their sessions; a session covering two issues shows on both.

- [ ] T001 [005/US1] Add `covers` to `_FIELDS` (`hubd/agents.py:98`) and validate it in `validate` (`hubd/agents.py:248-325`): 1 + up to `MAX_ALSO` items, each `{repo, number}` with today's repo/number checks, no duplicates, `repo`/`number` set from the first; across repositories only for full actions with a checkout; keep `also_numbers` accepted and folded in
- [ ] T002 [005/US1] Make `describe()`, `started()`, `running_sessions()` and `_prompt` (`hubd/agents.py:1424-1494`, `:809-840`) read `covers` (old records: primary + `also_numbers`); `_prompt` lists items in other repositories and that the worktree is the first item's (005 FR-009)
- [ ] T003 Add derived `prs` to `describe()`: `_pr_of(repo, "agent/<name>")` (`hubd/agents.py:1903`) per covered repository, in-memory cache 60 s; for PR actions, the covered PR itself
- [ ] T004 Add `view.json` handling and the `agent.view` op (`mode`, `where` from `SCREENS`, `ref`) in `hubd/agents.py` + `hubd/server.py:952-1010`; `describe()` returns `view` (default background), `origin` (null when absent), `permission_mode` (from the action, `hubd/agents.py:947`)
- [ ] T005 Expose `POST /api/agents/view` (add `view` to the step list at `app/hub/web.py:357`, fields `mode`, `where`, `ref`)
- [ ] T006 Return `covers` (refs only) from `list_running_sessions`/`list_sessions` (`app/hub/tools.py:340-370`)
- [ ] T007 Replace `sessionsOf` (`app.js:1046`) with a shared `sessionsOn(item, sessions)` helper using `covers` and `prs` (002 FR-019)
- [ ] T008 Tests: `tests/test_agents.py` — covers validated (bad repo, too many, duplicates, cross-repo on a locked action refused), old `session.json` with `also_numbers` describes as covers, `view.json` round-trip, `prs` from a fake `gh` reply; `tests/test_hubd.py` — `agent.view` needs a login; `tests/test_app.py` — the tool rows carry `covers` and no titles

---

## PR 2 — Typed messages: sessions are chats (S)

**Delivers**: FR-008, 010 FR-006 (own words). **Depends on**: 001/PR 2. **Files**: `hubd/agents.py`,
`hubd/shells.py`, `hubd/server.py`, `app/hub/web.py`, `app/hub/static/app.js`
(`StewardSession`, `Shells`), `SECURITY.md`, `docs/orchestrator.md`, `tests/test_app.py`,
`tests/test_agents.py`, `tests/test_hubd.py`. **Browser check**: quickstart "After 004/PR 2".
**Real claude**: one typed message to a real session, transcript shows it as the person's.

- [ ] T009 Switch `Shells.paste` (`hubd/shells.py:115-125`) from `set-buffer -- text` to `load-buffer -b <buf> -` with the text on stdin (extend `_tmux` to take stdin); `paste-buffer` unchanged
- [ ] T010 Add `agent.say` (`name`, `text`, `where`) in `hubd/server.py:952-1010` calling `Agents._send(name, text)` (`hubd/agents.py:1249`); login-gated by the existing prefix check
- [ ] T011 Add `say` to the step list at `app/hub/web.py:357` with fields `name`, `text`, `where`; `press` keeps refusing `text`
- [ ] T012 Add `MessageField({name})` (textarea, Send, queued/sent status in words, errors shown) under the Steward terminal (`StewardSession`, `app.js:2663-2690`) and under the Sessions terminal (`Shells`, `app.js:2238-2258`)
- [ ] T013 Change `tests/test_app.py:768` (`test_the_page_says_only_a_button_and_an_item_to_a_session`): `/api/agents/say` passes `text` through, `/api/agents/press` still drops it, `/api/agents/send` still 400
- [ ] T014 Tests: `tests/test_hubd.py` — `agent.say` refused without a login and with a tool token; `tests/test_agents.py` — `_send` refuses control characters and >4000 characters, queues mid-turn; the fake tmux sees the text on stdin and never in argv
- [ ] T015 Update `docs/orchestrator.md:146-156` ("Buttons", "Any session": typed messages from a login join the preset buttons) and add a `SECURITY.md` paragraph (who can send, through hubd, as typed input via stdin; the terminal socket already allowed typing, so no new reach; agents can't use it)

---

## PR 3 — SessionView (L)

**Delivers**: FR-001–FR-011, 002 FR-018, 010 FR-003 (compact mode), FR-005, 001 FR-014. **Depends on**:
002/PR 2, PR 2, 005/PR 1. **Files**: `app/hub/static/app.js` (`TerminalView`, `Manifest`, `Shells`,
`StewardSession`), `app/hub/static/style.css`, `tests/test_app.py`. **Browser check**: quickstart
"After 004/PR 3".

- [ ] T016 Add `SessionView({name, mode: "full"|"embedded"|"compact"})`: header with PersonaBadge, persona name, model, state, branch, origin ("from Work item kernel#204, by you"), tinted by family (FR-001, FR-002)
- [ ] T017 Covered items and PRs as ItemPills; "Also on these items" switcher when more than one, opening the Work item (FR-003, FR-004)
- [ ] T018 Terminal: wrap `TerminalView` (`app.js:1258`) on night paper; scroll to the end on open; keep the viewer's position while output arrives unless they're at the end (FR-005)
- [ ] T019 Inline pending interactions for this session from the shared interactions poll, answered with `interaction.answer` (`where = "SessionView"`) (FR-006)
- [ ] T020 SEND row: the session's preset buttons (from `agent.buttons`, `app.js:2666-2672`) and Esc (`agent.interrupt`), plus `MessageField` from PR 2 (FR-007, FR-008)
- [ ] T021 "Session spec" disclosure replacing `Manifest` (`app.js:1365-1403`): persona, action, model, permission mode, ceiling, covered items, worktree path, branch, start command (FR-009)
- [ ] T022 Embedded ⇄ background toggle calling `agent.view` (FR-010); Stop after `Confirm` (FR-011)
- [ ] T023 Adopt: Sessions (`Shells`, `app.js:2238-2258`) shows the selected session as `SessionView mode="full"`; the Steward panel (`StewardSession`) uses `mode="compact"`; `Spawn`'s embedded notice (`app.js:648-651`) uses `mode="embedded"`
- [ ] T024 Tests in `tests/test_app.py` (static): terminal box uses the night-paper token; Stop goes through `Confirm`; the message field posts to `agents/say`; `Manifest` is gone

---

## PR 4 — Sessions › Running and History & cleanup (M)

**Delivers**: FR-012–FR-023, 002 FR-015, SC-001. **Depends on**: PR 3. **Scenarios**: US1, US2.
**Files**: `app/hub/static/app.js` (`Shells`, `PastSessions`, `Cleanup`, `NewShell`,
`Transcript`), `hubd/agents.py` (`past`, `cleanup_scan`, `_cleanup_row`), `hubd/server.py`,
`tests/test_agents.py`, `tests/test_history.py`. **Browser check**: quickstart "After 004/PR 4".

- [ ] T025 Running groups: embedded in a view, in the background, finished with tmux still open, plain shells (from `view`, `ended`, `agent`) (FR-012)
- [ ] T026 Rows: PersonaBadge, state, "N waiting", origin · model · age, "⇄ also on" items, covered items; `FamilyLegend` above the list (FR-013, 002 FR-015)
- [ ] T027 "Badges only" narrowing; the selected session opens in a full `SessionView` beside the list (FR-014)
- [ ] T028 "＋ Plain shell" with a RepoPicker (one) choosing the cwd among that repository's worktrees (`NewShell`, `app.js:1347`) and "Resume a past session" linking History (FR-015)
- [ ] T029 [US2] History filters persona, repository, outcome: `agent.past` accepts them (`hubd/agents.py:1787-1814`); transcript search unchanged (`agent.past_search`); "Resume" / "Restore & resume" with busy state and "already running again" (`resume_past`, `hubd/agents.py:1844`) (FR-016–FR-019)
- [ ] T030 [US1] Cleanup rows add `command`, the exact removal `_remove_if_safe` runs (`hubd/agents.py:2026-2056`); "Select safe" picks only rows with no uncommitted changes, no running session and a merged or closed PR; the auto-remove setting (`cleanup_settings`, `hubd/agents.py:1892`) as a labelled switch (FR-020–FR-023)
- [ ] T031 Tests in `tests/test_agents.py`: `past` filters; cleanup `command` equals what removal runs; "safe" never set for a dirty worktree, a running session or an open PR (SC-001, one fixture each)

---

## Dependencies

- PR 1 — Session covers[], prs[], view, origin: depends on 002/PR 1
- PR 2 — Typed messages: sessions are chats: depends on 001/PR 2
- PR 3 — SessionView: depends on 002/PR 2, PR 2, 005/PR 1
- PR 4 — Sessions › Running and History & cleanup: depends on PR 3

The build order of all PRs across the ten specs is in [`specs/README.md`](../README.md).
