---
description: "Task list for spec 001 (hub app), as a stack of pull requests"
---

# Tasks: Hub app

**Input**: `specs/001-hub-app/` — plan.md, spec.md, research.md (R1–R17), data-model.md,
contracts/, quickstart.md

**Organization**: by **pull request**, not by user story, at the maintainer's request. Phases are
the PR stack in dependency order; each PR is independently reviewable, leaves `make check` green
(`make check PYTHON=.venv/bin/python`) and the app usable, with no half-migrated screen on `main`.
The `[US#]` label ties a task to the spec's scenario it serves; the map is below.

**Tests** are required: the constitution's Tests principle and the spec's Acceptance section ask
for host tests with every change. Each PR lists them as tasks; write them with or before the code.

## Format: `[ID] [P?] [US#?] Description`

- **[P]**: can run in parallel with other [P] tasks of the same PR (different files, no dependency
  between them). `app/hub/static/app.js` is one file, so its tasks are never [P] with each other.
- **[US#]**: the spec scenario (user story) the task serves.
- Every PR ends with the same three steps, written once here and not repeated: run
  `make check PYTHON=.venv/bin/python`; do the PR's browser check (quickstart.md §3) and record in
  the PR body what was checked and what wasn't tried for real; run
  `.glassine/org/scripts/safety-scan.sh --staged` before committing, with an `Assisted-by:` trailer.

## Scenario → PR map

| Scenario | PRs |
|---|---|
| US1 Answer a blocking prompt from any screen (P1) | 4, 5 |
| US2 Launch an implementer on two issues from a suggestion (P1) | 3, 7, 9 |
| US3 Review a PR, then merge it yourself (P1) | 7, 9, 11 |
| US4 Fix a failing CI run (P1) | 7, 9, 12 |
| US5 Research a question (P2) | 15 |
| US6 Grant a Go for a device run (P2) | 4, 5 |
| US7 Clean up old worktrees (P2) | 10 |
| US8 Use it on a phone (P2) | 18 |
| US9 Keep notes useful (P3) | 16 |
| US10 Resume a past session (P3) | 10 |
| US11 File an issue or start a workflow by hand (P3) | 12 |

## Decisions needed before building

- **Before PR 7:** the maintainer agrees that `pr-review` and `issue-triage` hand in results instead
  of posting and labelling themselves (research R9, plan Departure 2).
- **Before PR 5:** the maintainer agrees the GitHub API budget leaves the header (R7, Departure 5).
- **Before PR 16:** an issue in the workspace repository asks for `notes stats --json` (R12). PR 16
  ships with the fallback if it isn't there yet.

---

## PR 0 — Dev hubd: configurable tool server port (S)

**Delivers**: spec Implementation notes, last bullet (parallel test runs). **Depends on**: —.
**Browser check**: none (start `.dev/run.sh`, sign in once).

- [ ] T001 Take the tool server URL from `DEV_MCP_URL` (default `http://127.0.0.1:19095/mcp`) instead of the literal at `tests/dev_hubd.py:30`
- [ ] T002 Pass `HUB_AGENT_PORT` through to `DEV_MCP_URL` in `.dev/run.sh` (local, not committed) and say so in `quickstart.md` §2
- [ ] T003 Add a test in `tests/test_hubd.py` that imports `tests/dev_hubd.py`'s config builder with `DEV_MCP_URL` set and sees it used (split the builder out of `main()` so it can be imported)

---

## PR 1 — Persona families and action metadata (S)

**Delivers**: FR-011, FR-013 (data), FR-014 (data), FR-059 (metadata), FR-060, FR-051 (words).
**Depends on**: PR 0. **Files**: `agents/personas/families.toml` (new), `agents/personas/ci-fixer.md`,
`researcher.md`, `archivist.md` (new), `agents/actions/*.toml`, `hubd/agents.py` (`Library`,
`actions`), `tests/test_agents.py`. **Browser check**: none (no UI change).

- [ ] T004 [P] Write `agents/personas/families.toml` with `name`, `initials`, `family` for all ten personas in `agents/personas/` plus `ci-fixer`, `researcher`, `archivist` (R1; Steward = `organise`)
- [ ] T005 [P] Write persona prompts `agents/personas/ci-fixer.md`, `agents/personas/researcher.md`, `agents/personas/archivist.md` in the style of `agents/personas/engineer.md` (trailer rule, no `Signed-off-by`)
- [ ] T006 [P] Add `verb` and `result` to every file in `agents/actions/` per the table in research R2 (`result = "none"` for the "More…" actions); `pr-fix-checks.toml` personas become `["ci-fixer", "engineer"]`
- [ ] T007 Load `families.toml` in `Library.__init__` (`hubd/agents.py:210`), add `Library.family(persona)`, and refuse to load when a persona file lacks an entry, an entry lacks a file, or a family is outside the five
- [ ] T008 Validate `verb` (unique where present) and `result` (closed list) when actions load, and return `verb`, `result`, `family`, `persona_name` from `Agents.actions()` (`hubd/agents.py:396`)
- [ ] T009 Tests in `tests/test_agents.py`: library refuses a missing family, an unknown family, a duplicate verb, an unknown result; `agent.actions` rows carry the new fields; every shipped action loads

---

## PR 2 — Shared components (M)

**Delivers**: FR-001–FR-010, FR-012–FR-019 (UI), FR-164–FR-165, FR-168 (for these components),
SC-009. **Depends on**: PR 1. **Files**: `app/hub/static/app.js` (new component section after the
helpers, `app.js:120-220`), `app/hub/static/style.css`, `app/hub/web.py`/`hubd/server.py`
(families in `shell.list`), `tests/test_app.py`. **Browser check**: quickstart rows "After PR 2".
Each component is adopted in one existing place in this PR, so none is dead code.

- [ ] T010 Add CSS tokens for the five family tints, pen blue, mark yellow and night paper to `:root` and the dark block in `app/hub/static/style.css:14-21`; outline styles double/heavy/solid/dashed for severity (FR-165)
- [ ] T011 Add `ref(item)` helper and `ItemPill({kind, repo, number, title, state, removable, onRemove})` to `app/hub/static/app.js`: kind icon (reuse `StateIcon`, `app.js:143`), `repo#N` / `workflow #N`, title when there's room, state by outline + icon + accessible name, link to the Work item route, optional remove button (FR-001–FR-004)
- [ ] T012 Add `PersonaBadge({persona})` (initials on the family tint, `aria-label` = persona name; reserved pen-blue "S" for `steward`; a separate plain-shell badge) and `FamilyLegend` to `app/hub/static/app.js` (FR-012–FR-015)
- [ ] T013 Add `SessionChip({session, pending, onOpen})` to `app/hub/static/app.js`: badge, short name, RUNNING/WAITING/DONE/ATTACHED in words, yellow + "N waiting" only when waiting (FR-016, FR-017)
- [ ] T014 Add `RepoPicker({value, onChange, many, allowAll, groups})`: type-to-filter, recents and pins first from `localStorage` (try/catch), then by layer from `/api/overview` groups; >3 selected renders "N repos"; full keyboard (FR-005–FR-007, FR-010)
- [ ] T015 Add `ItemPicker({repos, kind, many, onPick})` over `GET /api/work/search` (`app/hub/web.py:202`) and refs typed as `repo#N`; candidates as ItemPills; keyboard (FR-008–FR-010)
- [ ] T016 Return `family`, `persona_name`, `initials` in each `agent` of `shell.list` (`hubd/server.py:217-221`) via `describe()` (`hubd/agents.py:1483`)
- [ ] T017 Adopt: `WorkRow`'s `sesschip` (`app.js:996`) → `SessionChip`; `WorkRow` ref → `ItemPill`; `RepoSelect` (`app.js:926`) → `RepoPicker` in `NewIssue` and `Dispatch`; Sessions list items (`app.js:2202`) show `PersonaBadge`
- [ ] T018 Static tests in `tests/test_app.py`: the five tint values and `#2747b8` / `#ffd86b` defined once as tokens; `ItemPill` never sets a background from state; `RepoPicker` renders a count past 3 (search the component's source for the `> 3` rule)

---

## PR 3 — Session covers[], prs[], view, origin (M)

**Delivers**: FR-019 (data), FR-022 (data), FR-028 (fields), FR-029 (backend), FR-056 (backend).
**Depends on**: PR 1. **Scenario**: US2. **Files**: `hubd/agents.py`, `hubd/server.py`,
`app/hub/web.py`, `app/hub/tools.py` (`list_running_sessions`), `app/hub/static/app.js`
(`sessionsOf`), `tests/test_agents.py`, `tests/test_hubd.py`, `tests/test_app.py`.
**Browser check**: Work rows still show their sessions; a session covering two issues shows on both.

- [ ] T019 [US2] Add `covers` to `_FIELDS` (`hubd/agents.py:98`) and validate it in `validate` (`hubd/agents.py:248-325`): 1 + up to `MAX_ALSO` items, each `{repo, number}` with today's repo/number checks, no duplicates, `repo`/`number` set from the first; across repositories only for full actions with a checkout; keep `also_numbers` accepted and folded in
- [ ] T020 [US2] Make `describe()`, `started()`, `running_sessions()` and `_prompt` (`hubd/agents.py:1424-1494`, `:809-840`) read `covers` (old records: primary + `also_numbers`); `_prompt` lists items in other repositories and that the worktree is the first item's (FR-056)
- [ ] T021 Add derived `prs` to `describe()`: `_pr_of(repo, "agent/<name>")` (`hubd/agents.py:1903`) per covered repository, in-memory cache 60 s; for PR actions, the covered PR itself
- [ ] T022 Add `view.json` handling and the `agent.view` op (`mode`, `where` from `SCREENS`, `ref`) in `hubd/agents.py` + `hubd/server.py:952-1010`; `describe()` returns `view` (default background), `origin` (null when absent), `permission_mode` (from the action, `hubd/agents.py:947`)
- [ ] T023 Expose `POST /api/agents/view` (add `view` to the step list at `app/hub/web.py:357`, fields `mode`, `where`, `ref`)
- [ ] T024 Return `covers` (refs only) from `list_running_sessions`/`list_sessions` (`app/hub/tools.py:340-370`)
- [ ] T025 Replace `sessionsOf` (`app.js:1046`) with a shared `sessionsOn(item, sessions)` helper using `covers` and `prs` (FR-019)
- [ ] T026 Tests: `tests/test_agents.py` — covers validated (bad repo, too many, duplicates, cross-repo on a locked action refused), old `session.json` with `also_numbers` describes as covers, `view.json` round-trip, `prs` from a fake `gh` reply; `tests/test_hubd.py` — `agent.view` needs a login; `tests/test_app.py` — the tool rows carry `covers` and no titles

---

## PR 4 — Interactions, Feed and the Needs-you modal (L)

**Delivers**: FR-031–FR-039, FR-041–FR-047, FR-149–FR-153, FR-164 (cards), SC-001, SC-002.
Result data (FR-040) comes in PR 7, result cards in PR 9. **Depends on**: PRs 2, 3. **Scenarios**: US1, US6.
**Files**: `hubd/server.py`, `app/hub/web.py`, `app/hub/static/app.js` (`Ask`, `Inbox`,
`SessionTabs`, `ActiveDecisions`, `DecisionsPage`, `GoPanel`, `DecisionRow`, `WorkWaiting`,
`SuggestedSession`, `Hub`), `app/hub/static/style.css`, `tests/test_hubd.py`, `tests/test_app.py`.
**Browser check**: quickstart rows "After PR 4". The old Sessions › Needs you and Active tabs and the
`#/decisions` route open the modal (with the matching filter) instead, so no screen is
half-migrated.

- [ ] T027 [US1] Add `interaction.` to the login-gated prefixes at `hubd/server.py:200` and implement `interaction.list` projecting `Asks.list()` (`hubd/asks.py:202`), `Decisions` (`hubd/decisions.py`), NewWork offers and done drafts (`hubd/newwork.py:233`) into the data-model Interaction shape, with `counts` (pending, blocking, by kind, longest wait) and `grants` (allowed decisions with `left`)
- [ ] T028 [US1] Implement `interaction.answer` dispatching by id prefix to `ask.answer`, `decision.approve|deny|end`, `work.dismiss`; record `handled = {by: login user, where, at}` on the source (asks: a field on `Ask`; decisions and offers: a field in their record)
- [ ] T029 [US6] Map statuses per research R3, including decisions' `timeout` (request older than `REQUEST_LIFE`, `hubd/decisions.py:38`) and asks' `stopped` → `ended`; eye-test Go can't be "always" (already in `decisions.py`; assert it)
- [ ] T030 Expose `GET /api/interactions` and `POST /api/interactions/{id}/answer` in `app/hub/web.py` (routes list `:412-462`); keep `/api/asks`, `/api/decisions`, `/api/new-work` for old pages
- [ ] T031 [US1] Replace the `asks` and `decisions` polls in `Hub` (`app.js:2763-2777`) with one 3 s poll of `/api/interactions`; keep the `/api/new-work` poll until PR 9, as `NewWork`, `StartForm` and `SetAside` read `asks.work`; keep the "failed read keeps what we knew" rule (`app.js:2765`)
- [ ] T032 [US1] Add `InteractionCard` with one body per kind, reusing `AskContent`/`AskQuestion` (`app.js:1426-1480`) for permission and question, `DecisionRow`'s approve/deny form (`app.js:2497`) for decisions, `GoForm` fields (`app.js:2442`) for the Go card (actions, device, ends after N runs/hours; eye-test note, FR-037), `SuggestedSession` (`app.js:1885`) for suggestions (its "Launch…" opens today's `StartForm` until PR 9)
- [ ] T033 [US1] Add `Feed({items, filter, dense, session})`: groups Blocking (oldest first), Suggested (with "Decisions asked for" first), Results ready; filter All / The Steward / Other sessions; dense one-line mode; each card links its session (SessionChip) and items (ItemPill) (FR-044–FR-047)
- [ ] T034 [US1] Add `NeedsYouModal`: opens over any view, sheet class at phone width, focus trap, Esc closes and returns focus to the opener (FR-149, FR-153, FR-169); filters include "Active grants" (Go and merge decisions in force with what's left and "End now", FR-151) and a session filter (FR-152); "Record a go…" and "I've got the device" from `GoPanel` (`app.js:2473`) move into it
- [ ] T035 [US1] "N handled in this view" line: interactions settled since the view mounted, with final status, who and where, until the route changes (FR-041)
- [ ] T036 Open the modal from a temporary "Needs you" entry on the Sessions tab bar and from the Sessions nav count (`app.js:2798-2801`) until PR 5 moves it to the header; route `#/shells?tab=needs`, `tab=active` and `#/decisions` to the modal with the matching filter; delete `Inbox`, `ActiveDecisions`, `DecisionsPage` and `SessionTabs`' needs/active tabs (`app.js:1991-2045`, `:2157-2168`, `:2526-2546`)
- [ ] T037 Tests in `tests/test_hubd.py`: `interaction.list` refuses a token; every status in FR-032 produced from a fixture of each source; answering through `interaction.answer` settles the source and records `handled.by`; a token can't call `interaction.answer`; eye-test Go refused as "always"; Go `left` counts down after `decision.use`
- [ ] T038 Tests in `tests/test_app.py`: `/api/interactions` needs a login and same origin for answers; replace `test_decisions_wait_under_needs_you_and_stand_under_active_without_a_nav_entry` and `test_queue_and_notes_are_tabs_and_the_go_is_in_needs_you` (`tests/test_app.py:914-943`) with checks that `GoPanel` is in `NeedsYouModal` and `DecisionsPage` is gone

---

## PR 5 — Header and navigation (M)

**Delivers**: FR-082–FR-086a, FR-089, FR-084, FR-085 (opens today's NewWork until PR 9), FR-173
(disconnected state). **Depends on**: PR 4. **Scenarios**: US1, US6. **Files**: `app/hub/static/app.js`
(`NAV`, `Hub`, `Budget`, `DeviceView`, `Overview`, `SEEN_SCREEN`, `seenFrom`, `Docs`/`NotesPage`
routing), `app/hub/static/style.css`, `hubd/agents.py` (`SCREENS`, status line), `hubd/server.py`
(`ping`, `usage.status`), `app/hub/web.py`, `agents/personas/steward-buttons.toml`,
`tests/test_app.py`, `tests/test_agents.py`. **Browser check**: quickstart rows "After PR 5".

- [ ] T039 [US1] Set `NAV` (`app.js:2640`) to `overview, roadmap, work, knowledge, notes, shells` labelled Overview, Roadmap, Work, Knowledge, Notes, Sessions; `knowledge` renders today's `Docs` search view and `notes` today's `NotesPage` (`app.js:2609`) on its own route; old `#/docs`, `#/docs?tab=notes`, `#/notes`, `#/device` addresses redirect (extend the legacy map at `app.js:2788-2794`)
- [ ] T040 [US1] Header "Needs you N" button: yellow only when something is blocking, outlined when N > 0 and nothing blocks, plain at 0, state in its accessible name (FR-083); opens `NeedsYouModal`; remove the temporary Sessions entry from PR 4
- [ ] T041 Header "＋ New work" (pen blue) opening today's `NewWork` with an empty brief (`planWork()`, `app.js:1481`) until PR 9 replaces it (FR-085)
- [ ] T042 Header user line with the hubd address from `ping` (add `socket` to the reply in `hubd/server.py`); when `/api/host` or the interactions poll fails, a plain "hubd can't be reached — showing what was last read" banner (FR-086, FR-173)
- [ ] T043 Usage meter: status-line command in `_hooks`/settings (`hubd/agents.py:841-862`) writing `status.json` (≤ 16 KiB); `usage.status` op (login, `usage.` prefix added at `hubd/server.py:200`); `GET /api/usage`; small `UsageMeter` replacing `Budget` in the header (`app.js:2415`), words + bar, "low" at 80 % (FR-086a, R7)
- [ ] T044 Move the GitHub API budget into Overview's stats line (`Overview`, `app.js:388-395`)
- [ ] T045 [US6] Device lock card on Overview from `GET /api/device` (`app/hub/web.py:151`) and `decision.holding`: lock line in words with its age, "you hold it", the Go in force; remove `DeviceView` (`app.js:2426-2440`) (FR-089, R11)
- [ ] T046 Rename screens: `SCREENS` (`hubd/agents.py:130`) → `Overview, Roadmap, Work, Knowledge, Notes, Sessions, Queue`; `SEEN_SCREEN` and `seenFrom` (`app.js:2645-2657`); `screen` values in `agents/personas/steward-buttons.toml`; a stale `Docs` from an old page maps to `Knowledge`
- [ ] T047 Tests in `tests/test_app.py`: NAV pinned to the six entries in order; `DeviceView` gone and `#/device` redirects; header button classes for blocking / pending / none; `seenFrom` maps knowledge and notes; `tests/test_agents.py`: `set_context` accepts Knowledge and Notes, refuses Device and Decisions; the status-line command writes only inside the session folder; `usage.status` with no file says not known, with a fixture computes `low`

---

## PR 6 — Typed messages: sessions are chats (S)

**Delivers**: FR-027, FR-159 (own words). **Depends on**: PR 5. **Files**: `hubd/agents.py`,
`hubd/shells.py`, `hubd/server.py`, `app/hub/web.py`, `app/hub/static/app.js`
(`StewardSession`, `Shells`), `SECURITY.md`, `docs/orchestrator.md`, `tests/test_app.py`,
`tests/test_agents.py`, `tests/test_hubd.py`. **Browser check**: quickstart "After PR 6".
**Real claude**: one typed message to a real session, transcript shows it as the person's.

- [ ] T048 Switch `Shells.paste` (`hubd/shells.py:115-125`) from `set-buffer -- text` to `load-buffer -b <buf> -` with the text on stdin (extend `_tmux` to take stdin); `paste-buffer` unchanged
- [ ] T049 Add `agent.say` (`name`, `text`, `where`) in `hubd/server.py:952-1010` calling `Agents._send(name, text)` (`hubd/agents.py:1249`); login-gated by the existing prefix check
- [ ] T050 Add `say` to the step list at `app/hub/web.py:357` with fields `name`, `text`, `where`; `press` keeps refusing `text`
- [ ] T051 Add `MessageField({name})` (textarea, Send, queued/sent status in words, errors shown) under the Steward terminal (`StewardSession`, `app.js:2663-2690`) and under the Sessions terminal (`Shells`, `app.js:2238-2258`)
- [ ] T052 Change `tests/test_app.py:768` (`test_the_page_says_only_a_button_and_an_item_to_a_session`): `/api/agents/say` passes `text` through, `/api/agents/press` still drops it, `/api/agents/send` still 400
- [ ] T053 Tests: `tests/test_hubd.py` — `agent.say` refused without a login and with a tool token; `tests/test_agents.py` — `_send` refuses control characters and >4000 characters, queues mid-turn; the fake tmux sees the text on stdin and never in argv
- [ ] T054 Update `docs/orchestrator.md:146-156` ("Buttons", "Any session": typed messages from a login join the preset buttons) and add a `SECURITY.md` paragraph (who can send, through hubd, as typed input via stdin; the terminal socket already allowed typing, so no new reach; agents can't use it)

---

## PR 7 — Launch records, stages and results: backend (L)

**Delivers**: FR-049 (stages as state), FR-053 (steps), FR-055 (backend), FR-056, FR-057, FR-058,
FR-061, FR-040 (data), FR-062–FR-067 (data + apply for drafts, comment, labels, findings, report,
pr). **Depends on**: PRs 3, 4; the maintainer's yes on R9. **Scenarios**: US2, US3, US4.
**Files**: `hubd/newwork.py`, `hubd/results.py` (new), `hubd/server.py`, `hubd/agents.py`
(`Library.schema`, `_prompt`, `plan`), `hubd/graphql/pr_review_add.graphql` (new),
`hubd/ghrun.py` (document allowlist), `app/hub/web.py`, `app/hub/github.py`, `app/hub/tools.py`,
`agents/actions/pr-review.toml`, `issue-triage.toml`, `run-diagnose.toml`, `issue-implement.toml`,
`pr-address-review.toml`, `agents/prompts/*.md`, `SECURITY.md`, `docs/orchestrator.md`, tests.
**Browser check**: none new (UI in PR 9); repo-object launches from today's `NewWork` form now
create v2 records, item launches move onto records in PR 9. **Real claude**: one planner run returns `steps`.

- [ ] T055 [US2] Extend NewWork records with `v: 2`, `covers`, `repos`, `from`, `plan`, `background`, `result` (`hubd/newwork.py:117`), keep reading records without `v`; derive `stage` in `list()`
- [ ] T056 [US2] `work.start` (`hubd/server.py:825-840`) accepts item actions with `covers`; replace the `number` refusal (`:829-830`) with the FR-058 check naming the item and the action's object; refuse covers whose kinds differ from the action's object; record `from`
- [ ] T057 [US2] Add `steps` to the planner schema (`Library.schema`, `hubd/agents.py:233-245`; ≤ 12 steps, ≤ 8 touches, ≤ 300 chars), to `PLANNER_CHOOSES` (`hubd/server.py:62`) and `_FIELDS`; `_prompt` adds them below the planner banner (`hubd/agents.py:829-835`)
- [ ] T058 Add `work.background` op and route `POST /api/new-work/{id}/background`; the session's `view.json` follows (PR 3)
- [ ] T059 Write `origin` (`{launch, from, by}`) into `session.json` when `_start_planned` starts a session (`hubd/server.py:776-791`)
- [ ] T060 [US3] Create `hubd/results.py`: store in `state/results`, 0700, closed payload shapes per type (data-model § Result), `applying` → `pending` with a "check GitHub first" note after a restart, prune to 200
- [ ] T061 [US3] Add token op `result.submit` in a `RESULT_TOOL_OPS` map checked like `WORK_TOOL_OPS` (`hubd/server.py:714-722`): refused unless the token's action has that `result`; one pending result per session
- [ ] T062 [P] [US3] Add tool `submit_result(type, payload)` (`WRITE`) to `app/hub/tools.py` and `github.submit_result` in `app/hub/github.py`
- [ ] T063 [US3] Login ops `result.list`, `result.apply`, `result.keep`, `result.dismiss` (prefix `result.` added at `hubd/server.py:200`): `apply` checks the producing action lists the needed tool (`review_pr`, `label_issue`, `edit_issue`) and writes through the same path that tool uses, as the persona's App when there is one
- [ ] T064 [P] [US3] Add `hubd/graphql/pr_review_add.graphql` (`addPullRequestReview` with `threads`) and its organization check beside the existing content-id checks; `github.post_review_result` uses it
- [ ] T065 Extend `interaction.list` with pending results and done drafts as `result` kind, `result.*` answers in `interaction.answer`
- [ ] T066 [P] [US3] Change actions per R2/R9: `pr-review.toml` (`hub_tools`: `review_pr` → `submit_result`), `issue-triage.toml` (`label_issue` → `submit_result`), `run-diagnose.toml` (adds `submit_result`), and their prompts in `agents/prompts/` to hand in a result
- [ ] T067 [US4] `implement`/`address`/`fix` results: when `prs[]` (PR 3) finds the session's PR, create a `pr` result (no apply); the implement prompt says "Closes #N" per covered issue (FR-063)
- [ ] T068 Web routes in `app/hub/web.py`: `/api/results`, `/api/results/{id}/apply|keep|dismiss`; `/api/new-work` accepts the new fields
- [ ] T069 Tests in `tests/test_newwork.py`: v1 records read; v2 fields saved; stage derivation; restart rules for item launches
- [ ] T070 Tests in `tests/test_hubd.py`: FR-058 refusal words; cross-kind covers refused; background flag; origin written; `result.submit` refused for the wrong type, an unknown key, a token without the tool; `result.apply` refused without a login, refused when the action lacks the tool; applying a comment result calls the named document with stdin text; applying labels goes through `label_issue`'s path
- [ ] T071 Tests in `tests/test_app.py`: `submit_result` listed only for a token whose action has it; a token from a session started with the old `pr-review` tool list still reaches `review_pr` (running-session rule)
- [ ] T072 Tests in `tests/test_ghpolicy.py`: the new GraphQL document runs by name only; a raw mutation stays refused
- [ ] T073 Update `SECURITY.md` (results: handed in by a token, applied by a login within the producing action's tools; reviewer no longer posts by itself) and `docs/orchestrator.md` (Launch records for every action; results)

---

## PR 8 — SessionView (L)

**Delivers**: FR-020–FR-030, FR-018, FR-156 (compact mode), FR-024, FR-167. **Depends on**:
PRs 2, 6, 7. **Files**: `app/hub/static/app.js` (`TerminalView`, `Manifest`, `Shells`,
`StewardSession`), `app/hub/static/style.css`, `tests/test_app.py`. **Browser check**: quickstart
"After PR 8".

- [ ] T074 Add `SessionView({name, mode: "full"|"embedded"|"compact"})`: header with PersonaBadge, persona name, model, state, branch, origin ("from Work item kernel#204, by you"), tinted by family (FR-020, FR-021)
- [ ] T075 Covered items and PRs as ItemPills; "Also on these items" switcher when more than one, opening the Work item (FR-022, FR-023)
- [ ] T076 Terminal: wrap `TerminalView` (`app.js:1258`) on night paper; scroll to the end on open; keep the viewer's position while output arrives unless they're at the end (FR-024)
- [ ] T077 Inline pending interactions for this session from the shared interactions poll, answered with `interaction.answer` (`where = "SessionView"`) (FR-025)
- [ ] T078 SEND row: the session's preset buttons (from `agent.buttons`, `app.js:2666-2672`) and Esc (`agent.interrupt`), plus `MessageField` from PR 6 (FR-026, FR-027)
- [ ] T079 "Session spec" disclosure replacing `Manifest` (`app.js:1365-1403`): persona, action, model, permission mode, ceiling, covered items, worktree path, branch, start command (FR-028)
- [ ] T080 Embedded ⇄ background toggle calling `agent.view` (FR-029); Stop after `Confirm` (FR-030)
- [ ] T081 Adopt: Sessions (`Shells`, `app.js:2238-2258`) shows the selected session as `SessionView mode="full"`; the Steward panel (`StewardSession`) uses `mode="compact"`; `Spawn`'s embedded notice (`app.js:648-651`) uses `mode="embedded"`
- [ ] T082 Tests in `tests/test_app.py` (static): terminal box uses the night-paper token; Stop goes through `Confirm`; the message field posts to `agents/say`; `Manifest` is gone

---

## PR 9 — Launch UI (L)

**Delivers**: FR-048–FR-055, FR-039 ("Launch…"), FR-062–FR-067 (result views), FR-040, FR-163
(sheet class), SC-003. **Depends on**: PRs 7, 8. **Scenarios**: US2, US3, US4. **Files**:
`app/hub/static/app.js` (replaces `Spawn`, `NewWork`, `StartForm`, `Launch`, `SteerFields`,
`plans`/`planErrors`/`rowPlan`/`advancedHandoff` globals; `app.js:494-657`, `:1481-1864`,
`:2268-2392`), `app/hub/static/style.css`, `tests/test_app.py`. **Browser check**: quickstart
"After PR 9" with the claude stub.

- [ ] T083 [US2] Add `LaunchModal` opened by a `hub-launch` event with `{action?, covers?, repos?, from, suggestion?}`, replacing `hub-new-work` and `hub-start-form` (`app.js:2781-2787`); the stage bar names brief, planning, plan, run, result and marks the current one (FR-048, FR-049)
- [ ] T084 [US2] Brief stage: action (verb list, "More…" for the rest), persona, covered items (ItemPills + ItemPicker, removable), repositories (RepoPicker), model, optional note, pins from `SteerFields`; result type and ceiling in plain words (FR-050, FR-051); FR-058 refusal shown before planning when the kinds don't match
- [ ] T085 [US2] Planning stage: planner model Opus / Sonnet / Haiku (`PlannerModel`, `app.js:1498`), progress from the record's state (poll `/api/new-work`) (FR-052)
- [ ] T086 [US2] Plan stage: steps with what each touches, briefing, docs; edit the brief and plan again, change the model, or Start (`work.approve`) (FR-053)
- [ ] T087 [US2] Run stage: compact `SessionView` with inline asks (FR-054); "Send to background" at any stage after planning → `work.background`, toast linking the session; later asks and the result arrive in Needs you (FR-055)
- [ ] T088 [US3] Result stage and result cards: drafts (reuse today's draft list and filing from `NewWork`, file / edit and file / send to the Steward), pr (link + "Closes …" lines), comment (summary + inline notes, "Post"), labels (per issue, "Apply"), findings (cause, smallest fix, "Start a fix session" → Launch with fix), report (answer, unsettled, sources, follow-ups, "Save to Knowledge") (FR-062–FR-067); the same views render result cards in Needs you (FR-040)
- [ ] T089 [US4] Entry points: header "＋ New work", Work rows (`WorkRow` `planIt`, `app.js:992`), Work item "Launch on …" row, suggestion "Launch…" (prefilled, its notes marked as the suggester's), Roadmap, Knowledge, Notes, the Steward's "＋" — all dispatch `hub-launch` with their `from` (FR-048)
- [ ] T090 Delete `Spawn`, `NewWork`, `StartForm`, `Launch` (advanced) and the `#/launch` route (redirect to the item), and their globals; the `nw-toast` becomes the Launch toast
- [ ] T091 Tests in `tests/test_app.py` (static + API): no `hub-new-work`/`hub-start-form` listeners remain; `LaunchModal` posts `covers` and `from` to `/api/new-work`; the stage list has the five names in order

---

## PR 10 — Sessions › Running and History & cleanup (M)

**Delivers**: FR-137–FR-148, FR-015, SC-008. **Depends on**: PR 8. **Scenarios**: US7, US10.
**Files**: `app/hub/static/app.js` (`Shells`, `PastSessions`, `Cleanup`, `NewShell`,
`Transcript`), `hubd/agents.py` (`past`, `cleanup_scan`, `_cleanup_row`), `hubd/server.py`,
`tests/test_agents.py`, `tests/test_history.py`. **Browser check**: quickstart "After PR 10".

- [ ] T092 Running groups: embedded in a view, in the background, finished with tmux still open, plain shells (from `view`, `ended`, `agent`) (FR-137)
- [ ] T093 Rows: PersonaBadge, state, "N waiting", origin · model · age, "⇄ also on" items, covered items; `FamilyLegend` above the list (FR-138, FR-015)
- [ ] T094 "Badges only" narrowing; the selected session opens in a full `SessionView` beside the list (FR-139)
- [ ] T095 "＋ Plain shell" with a RepoPicker (one) choosing the cwd among that repository's worktrees (`NewShell`, `app.js:1347`) and "Resume a past session" linking History (FR-140)
- [ ] T096 [US10] History filters persona, repository, outcome: `agent.past` accepts them (`hubd/agents.py:1787-1814`); transcript search unchanged (`agent.past_search`); "Resume" / "Restore & resume" with busy state and "already running again" (`resume_past`, `hubd/agents.py:1844`) (FR-141–FR-144)
- [ ] T097 [US7] Cleanup rows add `command`, the exact removal `_remove_if_safe` runs (`hubd/agents.py:2026-2056`); "Select safe" picks only rows with no uncommitted changes, no running session and a merged or closed PR; the auto-remove setting (`cleanup_settings`, `hubd/agents.py:1892`) as a labelled switch (FR-145–FR-148)
- [ ] T098 Tests in `tests/test_agents.py`: `past` filters; cleanup `command` equals what removal runs; "safe" never set for a dirty worktree, a running session or an open PR (SC-008, one fixture each)

---

## PR 11 — Work item (L)

**Delivers**: FR-069–FR-076, FR-081, FR-108–FR-122, FR-166 (split), SC-004. **Depends on**: PRs 8,
9. **Scenario**: US3. **Files**: `app/hub/static/app.js` (`ItemFrame`, `IssueDetail`, `PrDetail`,
`RunDetail`, `Threads`, `Comment`, `Labels`), `app/hub/static/style.css`, `app/hub/github.py`,
`app/hub/web.py`, `app/hub/tools.py` (agent reads where useful), `hubd/ghpolicy.py`,
`tests/test_ghpolicy.py`, `tests/test_app.py`. **Browser check**: quickstart "After PR 11".
**Real GitHub**: one merge, one label change, one re-run by the maintainer on the live hub.

- [ ] T099 [P] [US3] ghpolicy: add `pr edit` with only `--add-label`/`--remove-label`, and `pr reopen` (`hubd/ghpolicy.py:28-33` + a flag check); narrow `issue edit --add-assignee` to `@me` where no other caller needs more (grep callers first)
- [ ] T100 [P] [US3] Tests in `tests/test_ghpolicy.py`: allowed cases for each new shape and for the read paths `compare/…`, `labels`, `actions/runs/<id>/jobs`; refused `pr edit --title`, `--body-file /etc/passwd`, `--add-reviewer`, `pr reopen --comment-file x`, `--add-assignee someone`, a traversal in `compare/`
- [ ] T101 [US3] `github.py`: `behind_by` from `compare`, `merge_blockers` (checks running, `reviewDecision` not APPROVED, open threads count) on `pr()` (`app/hub/github.py:660-680`); `labels(repo)`; `pr_labels`; `assign_me`; `failed_step(repo, id)` from `actions/runs/<id>/jobs` + `--log-failed`, marking error lines; `pr_files` with a `large` flag (over 400 changed lines or a binary)
- [ ] T102 Routes in `app/hub/web.py` per `contracts/web-api.md` § Work (labels, assign-me, failed-step, files, `/api/labels/{repo}`)
- [ ] T103 [US3] `GhActions({kind, item})`: black split button "Merge…" / main action with caption "On GitHub, as {user}"; menu per kind (FR-073, FR-075, FR-076); disabled items stay and say why (FR-071, FR-074); Merge, Close and Cancel run confirm (FR-072); after an action the view reloads and shows "Merged by {user}" etc. within 10 s (FR-081); never combined with a pen-blue control (FR-166)
- [ ] T104 Breadcrumb Work › repository › reference, state, title, ref; GhActions next to the title; Details flyout (Part of, branch, size, author, labels, assignee, trigger, runner, target, repositories, updated, changed files — per kind); facts line (FR-108–FR-111)
- [ ] T105 [US3] "Launch on {ref}" row: the kind's agent actions as pen-blue buttons, the best as primary (FR-105 rule from PR 12's helper, defined here), "New work from this…" (FR-112)
- [ ] T106 Body as Markdown (`Md`, `app.js:178`), checks as chips (FR-113); PR tabs Conversation and Files changed (FR-114)
- [ ] T107 [US3] Conversation: review threads with ticks, "Address N threads…" → Launch address with thread pins (`Threads`, `app.js:750`); comment box with Post and "Draft with Claude" → Launch review with a comment result (FR-115, FR-116)
- [ ] T108 Files changed: file list with +/−; each opens to its hunks (`/api/prs/{repo}/{n}/diff?path=`) with line numbers and inline review notes at their lines; large files show "Large file — load the diff" (FR-117, FR-118)
- [ ] T109 Run: failed step log with error lines marked and a link to the full log (FR-119)
- [ ] T110 "Sessions on {ref} · N": persona tabs, each an embedded SessionView; "N sent to background" with links; with none, a suggestion card for the best action (FR-120–FR-122)
- [ ] T111 Tests in `tests/test_app.py`: `merge_blockers` words for each reason with fixtures; `behind_by` from a fake compare; labels/assign-me go out with the login (`login=token` reaches `hubd.gh`); failed-step marks error lines; static: every GhActions menu item has a disabled-reason branch

---

## PR 12 — Work (M)

**Delivers**: FR-099–FR-107a, FR-077–FR-080, FR-172. **Depends on**: PR 11. **Scenarios**: US4,
US11. **Files**: `app/hub/static/app.js` (`WorkLists`, `WorkRow`, `ROWS`, `NEEDS`, `NewIssue`,
`Dispatch`, `WorkQueue`), `app/hub/github.py` (`workflows`), `app/hub/web.py`,
`agents/actions/run-fix.toml` (new), `agents/prompts/run-fix.md` (new), `hubd/agents.py`
(run-fix checkout), `SECURITY.md` (one line on FR-107a), tests. **Browser check**: quickstart
"After PR 12".

- [ ] T112 RepoPicker with "All repositories", remembered per viewer in `localStorage` (FR-099); kind tabs PRs, Issues, Runs with counts for the selection (FR-100)
- [ ] T113 Groups: PRs Needs you / From agent sessions / Everything else; Issues Untriaged / In sessions / Backlog; Runs Failed / Running / Recent (replace `NEEDS`, `app.js:978-982`) (FR-101–FR-103)
- [ ] T114 Row: kind icon, ItemPill, title, sub-line (Part of, size, author or trigger, duration, age), state badge, SessionChips (FR-104); count + "load more" past one screen (FR-172)
- [ ] T115 [US4] `bestAction(item, actions)` helper: fix if failing, address if changes requested, triage if untriaged, else review / implement / investigate (FR-105); one pen-blue button per row opening Launch
- [ ] T116 [P] [US4] New action `agents/actions/run-fix.toml` (verb `fix`, object `run`, ci-fixer, full, new-branch from the run's head branch, result `pr`) and `agents/prompts/run-fix.md`; `_checkout` handles a run's branch (`hubd/agents.py:729-791`)
- [ ] T117 [US11] Work GhActions: "New issue…" (RepoPicker one, title, description, optional Part of via ItemPicker written as the body's first line, labels from `/api/labels/{repo}`, "Let Claude write it instead" → Launch issue with the text as brief) and "Run workflow…" (repository, dispatchable workflows, branch or tag, typed inputs; "no workflow can be started by hand" state) (FR-077–FR-080)
- [ ] T118 [US11] `github.workflows` adds `dispatchable` and `inputs` read from `contents/.github/workflows/<file>?ref=` with a small reader for `on.workflow_dispatch.inputs` (no YAML library); unreadable files say so
- [ ] T119 Queue view kept as a Work view (`WorkQueue`, `app.js:2581`); approving a set asks for a merge decision (existing). One `SECURITY.md` line: agents merge only under a merge decision for the current head (`hubd/server.py:535-580`), full sessions' own `gh` is a guard (FR-107, FR-107a)
- [ ] T120 Tests in `tests/test_app.py`: grouping and `bestAction` per FR-105 case (fixtures from the work store); the workflow inputs reader for choice/boolean/string/environment and a workflow with none; issue create writes "Part of"; `tests/test_agents.py`: `run-fix` validates on a run and is refused on an issue; `tests/test_hubd.py`: an agent token's merge without a decision for the current head is refused (keep or extend the existing test)

---

## PR 13 — Overview (M)

**Delivers**: FR-087, FR-088, FR-090–FR-094, FR-172, SC-006. **Depends on**: PRs 2, 5.
**Files**: `app/hub/static/app.js` (`Overview`, `NeedsYou`, `RepoDetail`), `app/hub/github.py`
(`overview`, `_repo_row`), `tests/test_app.py`. **Browser check**: quickstart "After PR 13".

- [ ] T121 Needs-you card from interaction `counts`: total, by kind, longest wait; opens the modal (FR-087); replaces `NeedsYou` (`app.js:264-291`)
- [ ] T122 Four stats: running sessions, open issues, open PRs with how many fail, Knowledge indexed documents (`DocsStat`, `app.js:356`) (FR-088)
- [ ] T123 `github.overview` rows add `attention` (failing runs, waiting sessions, open PRs, last activity) and `last_commit`/`last_activity` (`app/hub/github.py:189-203`, `:320-332`)
- [ ] T124 Layers sorted by attention, 5 each then "Show N more"; text filter; "Needs attention only"; "Collapse all"/"Expand all"; Unplaced line kept (FR-090–FR-092, FR-094)
- [ ] T125 Repository row: run strip (`Strip`, `app.js:220`), last commit, last activity, SessionChips, "Launch…" (FR-093)
- [ ] T126 Tests in `tests/test_app.py`: attention order on a fixture with each factor; "Show N more" count; an Overview of 60 repositories and 500 items is served from the store without a `gh` call (SC-006 at host level)

---

## PR 14 — Roadmap (M)

**Delivers**: FR-095–FR-098. **Depends on**: PR 9. **Files**: `app/hub/static/app.js`
(`Roadmap`), `app/hub/github.py` (`project`, `_board`, `_rollup_subs`), `app/hub/workstore.py`
(Part-of query), `config/` (column map), `tests/test_app.py`, `tests/test_workstore.py`.
**Browser check**: quickstart "After PR 14".

- [ ] T127 Column map from Status option names to Planned / In progress / In review / Done, configurable with the defaults in R14; unknown options go to Planned with a note (`_board`, `app/hub/github.py:1114`)
- [ ] T128 Progress per repository = sub-issues (`_rollup_subs`, `app/hub/github.py:1104`) ∪ issues whose body has "Part of hub#N" from `WorkStore.with_bodies` (`app/hub/workstore.py:331`), each issue once
- [ ] T129 Card: ref and target, title, progress bar per repository with counts in words, who works on it, SessionChips, "Plan issues…" → Launch road; opening a card shows its Work item with road and docs actions (FR-096–FR-098)
- [ ] T130 Tests: Part-of parsing (first line, mid-body, another repo's ref, a quoted line not counted); union without double counting; column mapping including an unknown option

---

## PR 15 — Knowledge (L)

**Delivers**: FR-123–FR-131, FR-067 (save/list), FR-128. **Depends on**: PR 9. **Scenario**: US5.
**Files**: `app/hub/static/app.js` (`Docs`, `DocsSearch`, `DocsTabs`), `app/hub/web.py`,
`app/hub/github.py`, `app/hub/docsearch.py` (status only), `agents/actions/knowledge-research.toml`
(new), `agents/prompts/knowledge-research.md` (new), `hubd/agents.py` (`object = "knowledge"` in
`validate`), `app/hub/tools.py` (`plan_work` accepts it), tests. **Browser check**: quickstart
"After PR 15". **Real claude**: one research session ending in a report.

- [ ] T131 [P] [US5] Action `agents/actions/knowledge-research.toml` (verb research, object knowledge, researcher, locked, read tools + `docs_search`, `work_search`, repo readers, `submit_result`; result report) and its prompt
- [ ] T132 [US5] `validate` and `_name` accept `object = "knowledge"` (no repo, no number, like `project`, `hubd/agents.py:257-260`); `plan_work` accepts it without a repo
- [ ] T133 [US5] `GET /api/knowledge/search` combining `docs.search` and `github.work_search` with domains, repos, open-only, mode; `GET /api/knowledge/indexes` from `docs.status` and `work_status` (FR-123–FR-125, FR-131)
- [ ] T134 [US5] Knowledge view: search box with meaning/exact; domain chips with Code "planned" and unselectable; RepoPicker (many); "Open only"; ranked / grouped by repository; result cards with kind, title, score, marked snippet, SessionChips, Open, "Pin as context"; "Try" chips when empty (FR-123–FR-127)
- [ ] T135 [US5] No good hits (best score under a threshold, R13) → offer to research; "Research this… (N pins)" flyout with question, scope, pins, "Plan a research session…" → Launch research (FR-128, FR-129)
- [ ] T136 [US5] Earlier reports in the flyout from `result.list(type=report, kept)`; each opens or "Follow up" → Launch with the report as a pin; index list with "Run docs CI now" (`/api/docs/reindex`) and "Ingest now" (`/api/work/sync`) (FR-130, FR-131)
- [ ] T137 Tests: research action validates with no repo and is refused with one; the report payload shape; `/api/knowledge/search` merges domains and marks matches; a planned domain can't be requested

---

## PR 16 — Notes (L)

**Delivers**: FR-132–FR-136, FR-068, US9. **Depends on**: PR 9; workspace `notes stats` optional
(R12). **Files**: `app/hub/static/app.js` (`NotesPage`), `hubd/notes.py`, `hubd/server.py`,
`app/hub/web.py`, `agents/actions/notes-compact.toml`, `notes-sweep.toml` (new), prompts,
`hubd/agents.py` (`object = "notes"`), `SECURITY.md` (Notes section), `tests/test_notes.py`,
`tests/test_hubd.py`. **Browser check**: quickstart "After PR 16" (dev workspace has no notes tool,
so check the missing state; the full flow needs the live workspace).

- [ ] T138 [US9] Notes view on its own route: search on a button press, ≤ 500 characters, never in the address; 20 rows, more up to 100, then a limit box with a copyable `notes find --limit` command (FR-132, FR-133; extend `NotesPage`, `app.js:2609-2638`)
- [ ] T139 [US9] Rows: trust label (CURRENT, OPEN QUESTION, HISTORY, RETRACTED, ARCHIVE·UNREVIEWED, NO STATUS) in words, title, topic (from `where`), date when the tool gives one; expandable long rows; states empty with legend, no results, more available, limit, tool missing, tool failed with its message, warnings, "indexing" badge (FR-134, FR-135)
- [ ] T140 [US9] `notes.totals` (`notes stats --json` when present, else counted from the last search, `source` says which) and `GET /api/notes/totals`; "Keep notes useful" flyout with totals per label and topic and "Compact…"/"Sweep…" for all or per topic → Launch (FR-136)
- [ ] T141 [P] [US9] Actions `notes-compact.toml` (archivist, result notes) and `notes-sweep.toml` (docs-writer, result drafts), object `notes`, with prompts; `validate` accepts `object = "notes"` with an optional topic in `notes`
- [ ] T142 [US9] `notes.apply` in `hubd/notes.py` + `hubd/server.py`: closed op list mapped to `notes add`/`notes set …` per R12, every argument checked, words after `--`, same env and `-I` as `find`; the shown `command` is built by hubd; no op deletes (FR-068)
- [ ] T143 [US9] Notes result card: each op with its exact command, apply one or all, per-op state and the tool's message on failure
- [ ] T144 Tests in `tests/test_notes.py`: each op's argv; a topic or id outside the format refused; words never become flags; a fake tool records nothing like a delete; `tests/test_hubd.py`: `notes.apply` refused for a token
- [ ] T145 Update `SECURITY.md` "Notes" (hubd's first notes write: login only, closed ops, no deletes)

---

## PR 17 — Steward panel (M)

**Delivers**: FR-154–FR-159. **Depends on**: PRs 8, 9. **Files**: `app/hub/static/app.js`
(`Steward`, `StewardSession`, `StewardModel`, `seenFrom`, `keptRail`), `app/hub/static/style.css`,
`hubd/agents.py` (`set_context` repos), `tests/test_app.py`, `tests/test_agents.py`.
**Browser check**: quickstart "After PR 17".

- [ ] T146 Resizable panel 320–760 px with a keyboard-operable handle, width in `localStorage` (FR-154)
- [ ] T147 Default open on Overview, Roadmap, Work and Work item; collapsed on Sessions, Knowledge and Notes; a viewer's own choice per view remembered (replace `keptRail`, `app.js:2659`) (FR-155)
- [ ] T148 Compact `SessionView` with the model and `StewardModel`'s select (FR-156)
- [ ] T149 SEES chips: view, selected repositories (≤ 3, else a count), open item; `agent.context` carries `repos` (FR-157)
- [ ] T150 Waiting strip: count of the Steward's pending interactions, opens Needs you filtered to `steward` (FR-158)
- [ ] T151 "＋ Plan new work with the Steward": sends the current view's context as a request with the person's own words (`agent.say`) (FR-159)
- [ ] T152 Tests: default open/closed per view (static); `set_context` validates `repos` names and caps them

---

## PR 18 — Phone ≤ 760 px (M)

**Delivers**: FR-160–FR-163, FR-170, FR-171, SC-007, US8. **Depends on**: PR 17. **Files**:
`app/hub/static/style.css` (breakpoints `style.css:279`, `:284` → 760), `app/hub/static/app.js`
(`Hub` header, `Steward`, modal/sheet class), `tests/test_app.py`. **Browser check**: quickstart
"After PR 18", every view at 390 px.

- [ ] T153 [US8] Header at ≤ 760 px: "New" and "Menu" only; Menu is a sheet with the nav, Needs you and the user line (FR-160)
- [ ] T154 [US8] Steward as a floating button opening a full sheet (FR-161)
- [ ] T155 [US8] Single column, 16 px gutters, no sideways page scroll; diffs, logs, terminals scroll in their own box (FR-162)
- [ ] T156 [US8] Launch, Needs you and flyouts open as full sheets (FR-163); touch targets ≥ 44 × 44 px (FR-170)
- [ ] T157 `prefers-reduced-motion` turns transitions off; nothing relies on motion (FR-171)
- [ ] T158 Static tests: one `@media (max-width: 760px)` block holds the phone rules; no fixed widths over 360 px outside scroll boxes in that block

---

## PR 19 — Cross-cutting checks and leftovers (S)

**Delivers**: FR-164–FR-173 (checks), FR-174–FR-178 (re-asserted), SC-004, SC-009, SC-010.
**Depends on**: PR 18. **Files**: `tests/test_app.py`, `app/hub/static/app.js`,
`app/hub/static/style.css`, `app/hub/web.py`. **Browser check**: keyboard-only pass of
scenarios 1–4 (quickstart "After PR 19").

- [ ] T159 Static test: `--mark`/`#ffd86b` used only in rules for waiting states (FR-164)
- [ ] T160 Static test: every `<button>` and link in `app.js` has text or an `aria-label`; modals use the shared focus trap (FR-168, FR-169)
- [ ] T161 Static test: GitHub writes in `app.js` (`post(\`prs/…\`)`, `issues/…`, `runs/…`, `workflows/…`) are only called from `GhActions` and its forms (SC-004)
- [ ] T162 Remove routes kept for old pages: `/api/asks`, `/api/decisions` reads from the app (keep the routes if `tools`/tests still need them), `/api/agents/plan`, `/api/agents/start`, `/api/agents/run` from the page; the `#/launch`, `#/decisions`, `#/device` redirects stay
- [ ] T163 Re-assert security tests still pass unchanged: login for every write, same origin, Host allowlist, CSP (`tests/test_app.py:258-330`); add one for `/api/interactions/{id}/answer` from another origin (FR-174–FR-178)

---

## Dependencies and execution order

```text
PR0 → PR1 ─┬→ PR2 ─┐
           └→ PR3 ─┴→ PR4 → PR5 → PR6 ─┐
                     PR3,PR4 → PR7 ────┴→ PR8 → PR9 ─┬→ PR10
                                                     ├→ PR11 → PR12
                                                     ├→ PR14, PR15, PR16 (any order)
                                                     └→ PR17 → PR18 → PR19
                     PR2,PR5 → PR13 (any time after PR5)
```

- PR 2 and PR 3 can be built at the same time (PR 2 is front end + one hubd field, PR 3 is hubd);
  they touch `hubd/agents.py`'s `describe()` both — land PR 3 first if both are ready.
- PR 7 (backend) can be built while PRs 5–6 are in review: it doesn't touch `app.js`; its UI
  comes in PR 9.
- PRs 13–16 have no logical dependency on each other; they all edit `app.js`, so merge one at a time
  and rebase.

## Parallel opportunities

- Within PR 1: T004, T005, T006 (different files).
- Within PR 7: T062 (tools), T064 (GraphQL document), T066 (action TOML and prompts) beside the
  hubd tasks.
- Within PR 11: T099 and T100 (policy and its tests) beside the `github.py` work.
- Within PR 12: T116 (new action files). Within PR 15: T131. Within PR 16: T141.
- Across the stack: PR 7 backend in parallel with PRs 5–6; PR 13 in parallel with PRs 7–12.

## Implementation strategy

- **First usable increment (P1 scenarios 1 and 6):** PRs 0–5. After PR 5 the maintainer answers any
  blocking prompt from any screen through the header (SC-001, SC-002), with Decisions, Go and grants
  in the modal and the device lock on Overview.
- **Second increment (scenarios 2–4):** PRs 6–12: chat, Launch with records and results, SessionView,
  Work and Work item with GhActions.
- **Then** P2/P3 views (13–16), the Steward panel (17), phone (18) and the final checks (19).
- Each PR's body states the FRs it delivers, what was tried for real, and what wasn't.
