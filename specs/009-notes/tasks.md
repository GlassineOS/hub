---
description: "Task list for spec 009 (notes), as a stack of pull requests"
---

# Tasks: Notes

**Input**: `specs/009-notes/` — spec.md, plan.md, research.md, data-model.md, contracts/; the dev hub and browser checks are in `specs/001-app-frame/quickstart.md`.

**Organization**: by **pull request**. The format (`[P]`, `[US#]`), the tests rule and the three
steps every PR ends with are in [`specs/README.md`](../README.md) § Tasks. `[USk]` is this spec's
scenario k, `[NNN/USk]` another spec's; `NNN/PR k` is another spec's PR.

## Scenario → PR map

| Scenario | PRs |
|---|---|
| US1 Keep notes useful (P3) | PR 1 |

## Decisions needed before building

- **Before PR 1:** an issue in the workspace repository asks for `notes stats --json` (R1). PR 1
  ships with the fallback if it isn't there yet.

---

## PR 1 — Notes (L)

**Delivers**: FR-001–FR-005, 005 FR-021, US1. **Depends on**: 005/PR 2; workspace `notes stats` optional
(R1). **Files**: `app/hub/static/app.js` (`NotesPage`), `hubd/notes.py`, `hubd/server.py`,
`app/hub/web.py`, `agents/actions/notes-compact.toml`, `notes-sweep.toml` (new), prompts,
`hubd/agents.py` (`object = "notes"`), `SECURITY.md` (Notes section), `tests/test_notes.py`,
`tests/test_hubd.py`. **Browser check**: quickstart "After 009/PR 1" (dev workspace has no notes tool,
so check the missing state; the full flow needs the live workspace).

- [ ] T001 [US1] Notes view on its own route: search on a button press, ≤ 500 characters, never in the address; 20 rows, more up to 100, then a limit box with a copyable `notes find --limit` command (FR-001, FR-002; extend `NotesPage`, `app.js:2609-2638`)
- [ ] T002 [US1] Rows: trust label (CURRENT, OPEN QUESTION, HISTORY, RETRACTED, ARCHIVE·UNREVIEWED, NO STATUS) in words, title, topic (from `where`), date when the tool gives one; expandable long rows; states empty with legend, no results, more available, limit, tool missing, tool failed with its message, warnings, "indexing" badge (FR-003, FR-004)
- [ ] T003 [US1] `notes.totals` (`notes stats --json` when present, else counted from the last search, `source` says which) and `GET /api/notes/totals`; "Keep notes useful" flyout with totals per label and topic and "Compact…"/"Sweep…" for all or per topic → Launch (FR-005)
- [ ] T004 [P] [US1] Actions `notes-compact.toml` (archivist, result notes) and `notes-sweep.toml` (docs-writer, result drafts), object `notes`, with prompts; `validate` accepts `object = "notes"` with an optional topic in `notes`
- [ ] T005 [US1] `notes.apply` in `hubd/notes.py` + `hubd/server.py`: closed op list mapped to `notes add`/`notes set …` per R1, every argument checked, words after `--`, same env and `-I` as `find`; the shown `command` is built by hubd; no op deletes (005 FR-021)
- [ ] T006 [US1] Notes result card: each op with its exact command, apply one or all, per-op state and the tool's message on failure
- [ ] T007 Tests in `tests/test_notes.py`: each op's argv; a topic or id outside the format refused; words never become flags; a fake tool records nothing like a delete; `tests/test_hubd.py`: `notes.apply` refused for a token
- [ ] T008 Update `SECURITY.md` "Notes" (hubd's first notes write: login only, closed ops, no deletes)

---

## Dependencies

- PR 1 — Notes: depends on 005/PR 2

The build order of all PRs across the ten specs is in [`specs/README.md`](../README.md).

## Parallel opportunities

- Within PR 1: T004.
