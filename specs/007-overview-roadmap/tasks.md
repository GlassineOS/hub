---
description: "Task list for spec 007 (overview and roadmap), as a stack of pull requests"
---

# Tasks: Overview and Roadmap

**Input**: `specs/007-overview-roadmap/` — spec.md, plan.md, research.md, data-model.md, contracts/; the dev hub and browser checks are in `specs/001-app-frame/quickstart.md`.

**Organization**: by **pull request**. The format (`[P]`, `[US#]`), the tests rule and the three
steps every PR ends with are in [`specs/README.md`](../README.md) § Tasks. `[USk]` is this spec's
scenario k, `[NNN/USk]` another spec's; `NNN/PR k` is another spec's PR.

## Scenario → PR map

| Scenario | PRs |
|---|---|
| US1 See what needs attention across all repositories (P2) | 001/PR 2, PR 1 |
| US2 Follow a roadmap item's progress (P3) | PR 2 |

## Requirements of this spec built by other specs' PRs

- 001/PR 2 — Header and navigation: FR-003

---

## PR 1 — Overview (M)

**Delivers**: FR-001, FR-002, FR-004–FR-008, 001 FR-019, 001 SC-002. **Depends on**: 002/PR 2, 001/PR 2.
**Files**: `app/hub/static/app.js` (`Overview`, `NeedsYou`, `RepoDetail`), `app/hub/github.py`
(`overview`, `_repo_row`), `tests/test_app.py`. **Browser check**: quickstart "After 007/PR 1".

- [ ] T001 Needs-you card from interaction `counts`: total, by kind, longest wait; opens the modal (FR-001); replaces `NeedsYou` (`app.js:264-291`)
- [ ] T002 Four stats: running sessions, open issues, open PRs with how many fail, Knowledge indexed documents (`DocsStat`, `app.js:356`) (FR-002)
- [ ] T003 `github.overview` rows add `attention` (failing runs, waiting sessions, open PRs, last activity) and `last_commit`/`last_activity` (`app/hub/github.py:189-203`, `:320-332`)
- [ ] T004 Layers sorted by attention, 5 each then "Show N more"; text filter; "Needs attention only"; "Collapse all"/"Expand all"; Unplaced line kept (FR-004–FR-006, FR-008)
- [ ] T005 Repository row: run strip (`Strip`, `app.js:220`), last commit, last activity, SessionChips, "Launch…" (FR-007)
- [ ] T006 Tests in `tests/test_app.py`: attention order on a fixture with each factor; "Show N more" count; an Overview of 60 repositories and 500 items is served from the store without a `gh` call (001 SC-002 at host level)

---

## PR 2 — Roadmap (M)

**Delivers**: FR-009–FR-012. **Depends on**: 005/PR 2. **Files**: `app/hub/static/app.js`
(`Roadmap`), `app/hub/github.py` (`project`, `_board`, `_rollup_subs`), `app/hub/workstore.py`
(Part-of query), `config/` (column map), `tests/test_app.py`, `tests/test_workstore.py`.
**Browser check**: quickstart "After 007/PR 2".

- [ ] T007 Column map from Status option names to Planned / In progress / In review / Done, configurable with the defaults in R2; unknown options go to Planned with a note (`_board`, `app/hub/github.py:1114`)
- [ ] T008 Progress per repository = sub-issues (`_rollup_subs`, `app/hub/github.py:1104`) ∪ issues whose body has "Part of hub#N" from `WorkStore.with_bodies` (`app/hub/workstore.py:331`), each issue once
- [ ] T009 Card: ref and target, title, progress bar per repository with counts in words, who works on it, SessionChips, "Plan issues…" → Launch road; opening a card shows its Work item with road and docs actions (FR-010–FR-012)
- [ ] T010 Tests: Part-of parsing (first line, mid-body, another repo's ref, a quoted line not counted); union without double counting; column mapping including an unknown option

---

## Dependencies

- PR 1 — Overview: depends on 002/PR 2, 001/PR 2
- PR 2 — Roadmap: depends on 005/PR 2

The build order of all PRs across the ten specs is in [`specs/README.md`](../README.md).
