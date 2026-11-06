---
description: "Task list for spec 006 (work), as a stack of pull requests"
---

# Tasks: Work

**Input**: `specs/006-work/` — spec.md, plan.md, research.md, contracts/; the dev hub and browser checks are in `specs/001-app-frame/quickstart.md`.

**Organization**: by **pull request**. The format (`[P]`, `[US#]`), the tests rule and the three
steps every PR ends with are in [`specs/README.md`](../README.md) § Tasks. `[USk]` is this spec's
scenario k, `[NNN/USk]` another spec's; `NNN/PR k` is another spec's PR.

## Scenario → PR map

| Scenario | PRs |
|---|---|
| US1 Review a PR, then merge it yourself (P1) | 005/PR 1, 005/PR 2, PR 1 |
| US2 Fix a failing CI run (P1) | 005/PR 1, 005/PR 2, PR 2 |
| US3 File an issue or start a workflow by hand (P3) | PR 2 |

---

## PR 1 — Work item (L)

**Delivers**: FR-026–FR-033, FR-038, FR-011–FR-025, 001 FR-013 (split), SC-001. **Depends on**: 004/PR 3, 005/PR 2. **Scenario**: US1. **Files**: `app/hub/static/app.js` (`ItemFrame`, `IssueDetail`, `PrDetail`,
`RunDetail`, `Threads`, `Comment`, `Labels`), `app/hub/static/style.css`, `app/hub/github.py`,
`app/hub/web.py`, `app/hub/tools.py` (agent reads where useful), `hubd/ghpolicy.py`,
`tests/test_ghpolicy.py`, `tests/test_app.py`. **Browser check**: quickstart "After 006/PR 1".
**Real GitHub**: one merge, one label change, one re-run by the maintainer on the live hub.

- [ ] T001 [P] [US1] ghpolicy: add `pr edit` with only `--add-label`/`--remove-label`, and `pr reopen` (`hubd/ghpolicy.py:28-33` + a flag check); narrow `issue edit --add-assignee` to `@me` where no other caller needs more (grep callers first)
- [ ] T002 [P] [US1] Tests in `tests/test_ghpolicy.py`: allowed cases for each new shape and for the read paths `compare/…`, `labels`, `actions/runs/<id>/jobs`; refused `pr edit --title`, `--body-file /etc/passwd`, `--add-reviewer`, `pr reopen --comment-file x`, `--add-assignee someone`, a traversal in `compare/`
- [ ] T003 [US1] `github.py`: `behind_by` from `compare`, `merge_blockers` (checks running, `reviewDecision` not APPROVED, open threads count) on `pr()` (`app/hub/github.py:660-680`); `labels(repo)`; `pr_labels`; `assign_me`; `failed_step(repo, id)` from `actions/runs/<id>/jobs` + `--log-failed`, marking error lines; `pr_files` with a `large` flag (over 400 changed lines or a binary)
- [ ] T004 Routes in `app/hub/web.py` per `contracts/web-api.md` § Work (labels, assign-me, failed-step, files, `/api/labels/{repo}`)
- [ ] T005 [US1] `GhActions({kind, item})`: black split button "Merge…" / main action with caption "On GitHub, as {user}"; menu per kind (FR-030, FR-032, FR-033); disabled items stay and say why (FR-028, FR-031); Merge, Close and Cancel run confirm (FR-029); after an action the view reloads and shows "Merged by {user}" etc. within 10 s (FR-038); never combined with a pen-blue control (001 FR-013)
- [ ] T006 Breadcrumb Work › repository › reference, state, title, ref; GhActions next to the title; Details flyout (Part of, branch, size, author, labels, assignee, trigger, runner, target, repositories, updated, changed files — per kind); facts line (FR-011–FR-014)
- [ ] T007 [US1] "Launch on {ref}" row: the kind's agent actions as pen-blue buttons, the best as primary (FR-007 rule from PR 2's helper, defined here), "New work from this…" (FR-015)
- [ ] T008 Body as Markdown (`Md`, `app.js:178`), checks as chips (FR-016); PR tabs Conversation and Files changed (FR-017)
- [ ] T009 [US1] Conversation: review threads with ticks, "Address N threads…" → Launch address with thread pins (`Threads`, `app.js:750`); comment box with Post and "Draft with Claude" → Launch review with a comment result (FR-018, FR-019)
- [ ] T010 Files changed: file list with +/−; each opens to its hunks (`/api/prs/{repo}/{n}/diff?path=`) with line numbers and inline review notes at their lines; large files show "Large file — load the diff" (FR-020, FR-021)
- [ ] T011 Run: failed step log with error lines marked and a link to the full log (FR-022)
- [ ] T012 "Sessions on {ref} · N": persona tabs, each an embedded SessionView; "N sent to background" with links; with none, a suggestion card for the best action (FR-023–FR-025)
- [ ] T013 Tests in `tests/test_app.py`: `merge_blockers` words for each reason with fixtures; `behind_by` from a fake compare; labels/assign-me go out with the login (`login=token` reaches `hubd.gh`); failed-step marks error lines; static: every GhActions menu item has a disabled-reason branch

---

## PR 2 — Work (M)

**Delivers**: FR-001–FR-010, FR-034–FR-037, 001 FR-019. **Depends on**: PR 1. **Scenarios**: US2,
US3. **Files**: `app/hub/static/app.js` (`WorkLists`, `WorkRow`, `ROWS`, `NEEDS`, `NewIssue`,
`Dispatch`, `WorkQueue`), `app/hub/github.py` (`workflows`), `app/hub/web.py`,
`agents/actions/run-fix.toml` (new), `agents/prompts/run-fix.md` (new), `hubd/agents.py`
(run-fix checkout), `SECURITY.md` (one line on FR-010), tests. **Browser check**: quickstart
"After 006/PR 2".

- [ ] T014 RepoPicker with "All repositories", remembered per viewer in `localStorage` (FR-001); kind tabs PRs, Issues, Runs with counts for the selection (FR-002)
- [ ] T015 Groups: PRs Needs you / From agent sessions / Everything else; Issues Untriaged / In sessions / Backlog; Runs Failed / Running / Recent (replace `NEEDS`, `app.js:978-982`) (FR-003–FR-005)
- [ ] T016 Row: kind icon, ItemPill, title, sub-line (Part of, size, author or trigger, duration, age), state badge, SessionChips (FR-006); count + "load more" past one screen (001 FR-019)
- [ ] T017 [US2] `bestAction(item, actions)` helper: fix if failing, address if changes requested, triage if untriaged, else review / implement / investigate (FR-007); one pen-blue button per row opening Launch
- [ ] T018 [P] [US2] New action `agents/actions/run-fix.toml` (verb `fix`, object `run`, ci-fixer, full, new-branch from the run's head branch, result `pr`) and `agents/prompts/run-fix.md`; `_checkout` handles a run's branch (`hubd/agents.py:729-791`)
- [ ] T019 [US3] Work GhActions: "New issue…" (RepoPicker one, title, description, optional Part of via ItemPicker written as the body's first line, labels from `/api/labels/{repo}`, "Let Claude write it instead" → Launch issue with the text as brief) and "Run workflow…" (repository, dispatchable workflows, branch or tag, typed inputs; "no workflow can be started by hand" state) (FR-034–FR-037)
- [ ] T020 [US3] `github.workflows` adds `dispatchable` and `inputs` read from `contents/.github/workflows/<file>?ref=` with a small reader for `on.workflow_dispatch.inputs` (no YAML library); unreadable files say so
- [ ] T021 Queue view kept as a Work view (`WorkQueue`, `app.js:2581`); approving a set asks for a merge decision (existing). One `SECURITY.md` line: agents merge only under a merge decision for the current head (`hubd/server.py:535-580`), full sessions' own `gh` is a guard (FR-009, FR-010)
- [ ] T022 Tests in `tests/test_app.py`: grouping and `bestAction` per FR-007 case (fixtures from the work store); the workflow inputs reader for choice/boolean/string/environment and a workflow with none; issue create writes "Part of"; `tests/test_agents.py`: `run-fix` validates on a run and is refused on an issue; `tests/test_hubd.py`: an agent token's merge without a decision for the current head is refused (keep or extend the existing test)

---

## Dependencies

- PR 1 — Work item: depends on 004/PR 3, 005/PR 2
- PR 2 — Work: depends on PR 1

The build order of all PRs across the ten specs is in [`specs/README.md`](../README.md).

## Parallel opportunities

- Within PR 1: T001 and T002 (policy and its tests) beside the `github.py` work.
- Within PR 2: T018 (new action files).
