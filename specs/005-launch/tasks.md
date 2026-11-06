---
description: "Task list for spec 005 (launch), as a stack of pull requests"
---

# Tasks: Launch

**Input**: `specs/005-launch/` — spec.md, plan.md, research.md, data-model.md, contracts/; the dev hub and browser checks are in `specs/001-app-frame/quickstart.md`.

**Organization**: by **pull request**. The format (`[P]`, `[US#]`), the tests rule and the three
steps every PR ends with are in [`specs/README.md`](../README.md) § Tasks. `[USk]` is this spec's
scenario k, `[NNN/USk]` another spec's; `NNN/PR k` is another spec's PR.

## Scenario → PR map

| Scenario | PRs |
|---|---|
| US1 Launch an implementer on two issues from a suggestion (P1) | 004/PR 1, PR 1, PR 2 |

## Decisions needed before building

- **Before PR 1:** the maintainer agrees that `pr-review` and `issue-triage` hand in results instead
  of posting and labelling themselves (research R3, plan.md Departures).

## Requirements of this spec built by other specs' PRs

- 002/PR 1 — Persona families and action metadata: FR-004, FR-012, FR-013
- 004/PR 1 — Session covers[], prs[], view, origin: FR-009
- 008/PR 1 — Knowledge: FR-020
- 009/PR 1 — Notes: FR-021

---

## PR 1 — Launch records, stages and results: backend (L)

**Delivers**: FR-002 (stages as state), FR-006 (steps), FR-008 (backend), FR-009, FR-010, FR-011,
FR-014, 003 FR-010 (data), FR-015–FR-020 (data + apply for drafts, comment, labels, findings, report,
pr). **Depends on**: 004/PR 1, 003/PR 1; the maintainer's yes on R3. **Scenarios**: US1, 006/US1, 006/US2.
**Files**: `hubd/newwork.py`, `hubd/results.py` (new), `hubd/server.py`, `hubd/agents.py`
(`Library.schema`, `_prompt`, `plan`), `hubd/graphql/pr_review_add.graphql` (new),
`hubd/ghrun.py` (document allowlist), `app/hub/web.py`, `app/hub/github.py`, `app/hub/tools.py`,
`agents/actions/pr-review.toml`, `issue-triage.toml`, `run-diagnose.toml`, `issue-implement.toml`,
`pr-address-review.toml`, `agents/prompts/*.md`, `SECURITY.md`, `docs/orchestrator.md`, tests.
**Browser check**: none new (UI in PR 2); repo-object launches from today's `NewWork` form now
create v2 records, item launches move onto records in PR 2. **Real claude**: one planner run returns `steps`.

- [ ] T001 [US1] Extend NewWork records with `v: 2`, `covers`, `repos`, `from`, `plan`, `background`, `result` (`hubd/newwork.py:117`), keep reading records without `v`; derive `stage` in `list()`
- [ ] T002 [US1] `work.start` (`hubd/server.py:825-840`) accepts item actions with `covers`; replace the `number` refusal (`:829-830`) with the FR-011 check naming the item and the action's object; refuse covers whose kinds differ from the action's object; record `from`
- [ ] T003 [US1] Add `steps` to the planner schema (`Library.schema`, `hubd/agents.py:233-245`; ≤ 12 steps, ≤ 8 touches, ≤ 300 chars), to `PLANNER_CHOOSES` (`hubd/server.py:62`) and `_FIELDS`; `_prompt` adds them below the planner banner (`hubd/agents.py:829-835`)
- [ ] T004 Add `work.background` op and route `POST /api/new-work/{id}/background`; the session's `view.json` follows (004/PR 1)
- [ ] T005 Write `origin` (`{launch, from, by}`) into `session.json` when `_start_planned` starts a session (`hubd/server.py:776-791`)
- [ ] T006 [006/US1] Create `hubd/results.py`: store in `state/results`, 0700, closed payload shapes per type (data-model § Result), `applying` → `pending` with a "check GitHub first" note after a restart, prune to 200
- [ ] T007 [006/US1] Add token op `result.submit` in a `RESULT_TOOL_OPS` map checked like `WORK_TOOL_OPS` (`hubd/server.py:714-722`): refused unless the token's action has that `result`; one pending result per session
- [ ] T008 [P] [006/US1] Add tool `submit_result(type, payload)` (`WRITE`) to `app/hub/tools.py` and `github.submit_result` in `app/hub/github.py`
- [ ] T009 [006/US1] Login ops `result.list`, `result.apply`, `result.keep`, `result.dismiss` (prefix `result.` added at `hubd/server.py:200`): `apply` checks the producing action lists the needed tool (`review_pr`, `label_issue`, `edit_issue`) and writes through the same path that tool uses, as the persona's App when there is one
- [ ] T010 [P] [006/US1] Add `hubd/graphql/pr_review_add.graphql` (`addPullRequestReview` with `threads`) and its organization check beside the existing content-id checks; `github.post_review_result` uses it
- [ ] T011 Extend `interaction.list` with pending results and done drafts as `result` kind, `result.*` answers in `interaction.answer`
- [ ] T012 [P] [006/US1] Change actions per 002 R2/R9: `pr-review.toml` (`hub_tools`: `review_pr` → `submit_result`), `issue-triage.toml` (`label_issue` → `submit_result`), `run-diagnose.toml` (adds `submit_result`), and their prompts in `agents/prompts/` to hand in a result
- [ ] T013 [006/US2] `implement`/`address`/`fix` results: when `prs[]` (004/PR 1) finds the session's PR, create a `pr` result (no apply); the implement prompt says "Closes #N" per covered issue (FR-016)
- [ ] T014 Web routes in `app/hub/web.py`: `/api/results`, `/api/results/{id}/apply|keep|dismiss`; `/api/new-work` accepts the new fields
- [ ] T015 Tests in `tests/test_newwork.py`: v1 records read; v2 fields saved; stage derivation; restart rules for item launches
- [ ] T016 Tests in `tests/test_hubd.py`: FR-011 refusal words; cross-kind covers refused; background flag; origin written; `result.submit` refused for the wrong type, an unknown key, a token without the tool; `result.apply` refused without a login, refused when the action lacks the tool; applying a comment result calls the named document with stdin text; applying labels goes through `label_issue`'s path
- [ ] T017 Tests in `tests/test_app.py`: `submit_result` listed only for a token whose action has it; a token from a session started with the old `pr-review` tool list still reaches `review_pr` (running-session rule)
- [ ] T018 Tests in `tests/test_ghpolicy.py`: the new GraphQL document runs by name only; a raw mutation stays refused
- [ ] T019 Update `SECURITY.md` (results: handed in by a token, applied by a login within the producing action's tools; reviewer no longer posts by itself) and `docs/orchestrator.md` (Launch records for every action; results)

---

## PR 2 — Launch UI (L)

**Delivers**: FR-001–FR-008, 003 FR-009 ("Launch…"), FR-015–FR-020 (result views), 003 FR-010, 001 FR-010
(sheet class), SC-001. **Depends on**: PR 1, 004/PR 3. **Scenarios**: US1, 006/US1, 006/US2. **Files**:
`app/hub/static/app.js` (replaces `Spawn`, `NewWork`, `StartForm`, `Launch`, `SteerFields`,
`plans`/`planErrors`/`rowPlan`/`advancedHandoff` globals; `app.js:494-657`, `:1481-1864`,
`:2268-2392`), `app/hub/static/style.css`, `tests/test_app.py`. **Browser check**: quickstart
"After 005/PR 2" with the claude stub.

- [ ] T020 [US1] Add `LaunchModal` opened by a `hub-launch` event with `{action?, covers?, repos?, from, suggestion?}`, replacing `hub-new-work` and `hub-start-form` (`app.js:2781-2787`); the stage bar names brief, planning, plan, run, result and marks the current one (FR-001, FR-002)
- [ ] T021 [US1] Brief stage: action (verb list, "More…" for the rest), persona, covered items (ItemPills + ItemPicker, removable), repositories (RepoPicker), model, optional note, pins from `SteerFields`; result type and ceiling in plain words (FR-003, FR-004); FR-011 refusal shown before planning when the kinds don't match
- [ ] T022 [US1] Planning stage: planner model Opus / Sonnet / Haiku (`PlannerModel`, `app.js:1498`), progress from the record's state (poll `/api/new-work`) (FR-005)
- [ ] T023 [US1] Plan stage: steps with what each touches, briefing, docs; edit the brief and plan again, change the model, or Start (`work.approve`) (FR-006)
- [ ] T024 [US1] Run stage: compact `SessionView` with inline asks (FR-007); "Send to background" at any stage after planning → `work.background`, toast linking the session; later asks and the result arrive in Needs you (FR-008)
- [ ] T025 [006/US1] Result stage and result cards: drafts (reuse today's draft list and filing from `NewWork`, file / edit and file / send to the Steward), pr (link + "Closes …" lines), comment (summary + inline notes, "Post"), labels (per issue, "Apply"), findings (cause, smallest fix, "Start a fix session" → Launch with fix), report (answer, unsettled, sources, follow-ups, "Save to Knowledge") (FR-015–FR-020); the same views render result cards in Needs you (003 FR-010)
- [ ] T026 [006/US2] Entry points: header "＋ New work", Work rows (`WorkRow` `planIt`, `app.js:992`), Work item "Launch on …" row, suggestion "Launch…" (prefilled, its notes marked as the suggester's), Roadmap, Knowledge, Notes, the Steward's "＋" — all dispatch `hub-launch` with their `from` (FR-001)
- [ ] T027 Delete `Spawn`, `NewWork`, `StartForm`, `Launch` (advanced) and the `#/launch` route (redirect to the item), and their globals; the `nw-toast` becomes the Launch toast
- [ ] T028 Tests in `tests/test_app.py` (static + API): no `hub-new-work`/`hub-start-form` listeners remain; `LaunchModal` posts `covers` and `from` to `/api/new-work`; the stage list has the five names in order

---

## Dependencies

- PR 1 — Launch records, stages and results: backend: depends on 004/PR 1, 003/PR 1
- PR 2 — Launch UI: depends on PR 1, 004/PR 3

The build order of all PRs across the ten specs is in [`specs/README.md`](../README.md).

## Parallel opportunities

- Within PR 1: T008 (tools), T010 (GraphQL document), T012 (action TOML and prompts) beside the
  hubd tasks.
