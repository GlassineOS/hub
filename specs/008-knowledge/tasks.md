---
description: "Task list for spec 008 (knowledge), as a stack of pull requests"
---

# Tasks: Knowledge

**Input**: `specs/008-knowledge/` — spec.md, plan.md, research.md, data-model.md, contracts/; the dev hub and browser checks are in `specs/001-app-frame/quickstart.md`.

**Organization**: by **pull request**. The format (`[P]`, `[US#]`), the tests rule and the three
steps every PR ends with are in [`specs/README.md`](../README.md) § Tasks. `[USk]` is this spec's
scenario k, `[NNN/USk]` another spec's; `NNN/PR k` is another spec's PR.

## Scenario → PR map

| Scenario | PRs |
|---|---|
| US1 Research a question (P2) | PR 1 |

---

## PR 1 — Knowledge (L)

**Delivers**: FR-001–FR-009, 005 FR-020 (save/list), FR-006. **Depends on**: 005/PR 2. **Scenario**: US1.
**Files**: `app/hub/static/app.js` (`Docs`, `DocsSearch`, `DocsTabs`), `app/hub/web.py`,
`app/hub/github.py`, `app/hub/docsearch.py` (status only), `agents/actions/knowledge-research.toml`
(new), `agents/prompts/knowledge-research.md` (new), `hubd/agents.py` (`object = "knowledge"` in
`validate`), `app/hub/tools.py` (`plan_work` accepts it), tests. **Browser check**: quickstart
"After 008/PR 1". **Real claude**: one research session ending in a report.

- [ ] T001 [P] [US1] Action `agents/actions/knowledge-research.toml` (verb research, object knowledge, researcher, locked, read tools + `docs_search`, `work_search`, repo readers, `submit_result`; result report) and its prompt
- [ ] T002 [US1] `validate` and `_name` accept `object = "knowledge"` (no repo, no number, like `project`, `hubd/agents.py:257-260`); `plan_work` accepts it without a repo
- [ ] T003 [US1] `GET /api/knowledge/search` combining `docs.search` and `github.work_search` with domains, repos, open-only, mode; `GET /api/knowledge/indexes` from `docs.status` and `work_status` (FR-001–FR-003, FR-009)
- [ ] T004 [US1] Knowledge view: search box with meaning/exact; domain chips with Code "planned" and unselectable; RepoPicker (many); "Open only"; ranked / grouped by repository; result cards with kind, title, score, marked snippet, SessionChips, Open, "Pin as context"; "Try" chips when empty (FR-001–FR-005)
- [ ] T005 [US1] No good hits (best score under a threshold, R1) → offer to research; "Research this… (N pins)" flyout with question, scope, pins, "Plan a research session…" → Launch research (FR-006, FR-007)
- [ ] T006 [US1] Earlier reports in the flyout from `result.list(type=report, kept)`; each opens or "Follow up" → Launch with the report as a pin; index list with "Run docs CI now" (`/api/docs/reindex`) and "Ingest now" (`/api/work/sync`) (FR-008, FR-009)
- [ ] T007 Tests: research action validates with no repo and is refused with one; the report payload shape; `/api/knowledge/search` merges domains and marks matches; a planned domain can't be requested

---

## Dependencies

- PR 1 — Knowledge: depends on 005/PR 2

The build order of all PRs across the ten specs is in [`specs/README.md`](../README.md).

## Parallel opportunities

- Within PR 1: T001.
