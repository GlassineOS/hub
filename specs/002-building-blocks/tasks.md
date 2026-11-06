---
description: "Task list for spec 002 (building blocks), as a stack of pull requests"
---

# Tasks: Building blocks

**Input**: `specs/002-building-blocks/` — spec.md, plan.md, research.md, data-model.md, contracts/; the dev hub and browser checks are in `specs/001-app-frame/quickstart.md`.

**Organization**: by **pull request**. The format (`[P]`, `[US#]`), the tests rule and the three
steps every PR ends with are in [`specs/README.md`](../README.md) § Tasks. `[USk]` is this spec's
scenario k, `[NNN/USk]` another spec's; `NNN/PR k` is another spec's PR.

## Scenario → PR map

| Scenario | PRs |
|---|---|
| US1 Pick items and repositories by keyboard (P2) | PRs 1, 2 |

## Requirements of this spec built by other specs' PRs

- 004/PR 1 — Session covers[], prs[], view, origin: FR-019
- 004/PR 3 — SessionView: FR-018
- 004/PR 4 — Sessions › Running and History & cleanup: FR-015

---

## PR 1 — Persona families and action metadata (S) — done (hub #27)

**Delivers**: FR-011, FR-013 (data), FR-014 (data), 005 FR-012 (metadata), 005 FR-013, 005 FR-004 (words).
**Depends on**: 001/PR 1. **Files**: `agents/personas/families.toml` (new), `agents/personas/ci-fixer.md`,
`researcher.md`, `archivist.md` (new), `agents/actions/*.toml`, `hubd/agents.py` (`Library`,
`actions`), `tests/test_agents.py`. **Browser check**: none (no UI change).

- [x] T001 [P] Write `agents/personas/families.toml` with `name`, `initials`, `family` for all ten personas in `agents/personas/` plus `ci-fixer`, `researcher`, `archivist` (R1; Steward = `organise`)
- [x] T002 [P] Write persona prompts `agents/personas/ci-fixer.md`, `agents/personas/researcher.md`, `agents/personas/archivist.md` in the style of `agents/personas/engineer.md` (trailer rule, no `Signed-off-by`)
- [x] T003 [P] Add `verb` and `result` to every file in `agents/actions/` per the table in research R2 (`result = "none"` for the "More…" actions); `pr-fix-checks.toml` personas become `["ci-fixer", "engineer"]`
- [x] T004 Load `families.toml` in `Library.__init__` (`hubd/agents.py:210`), add `Library.family(persona)`, and refuse to load when a persona file lacks an entry, an entry lacks a file, or a family is outside the five
- [x] T005 Validate `verb` (unique where present) and `result` (closed list) when actions load, and return `verb`, `result`, `family`, `persona_name` from `Agents.actions()` (`hubd/agents.py:396`)
- [x] T006 Tests in `tests/test_agents.py`: library refuses a missing family, an unknown family, a duplicate verb, an unknown result; `agent.actions` rows carry the new fields; every shipped action loads

---

## PR 2 — Shared components (M) — done (hub #28)

**Delivers**: FR-001–FR-010, FR-012–FR-019 (UI), 001 FR-011–FR-012, 001 FR-015 (for these components),
SC-001. **Depends on**: PR 1. **Files**: `app/hub/static/app.js` (new component section after the
helpers, `app.js:120-220`), `app/hub/static/style.css`, `app/hub/web.py`/`hubd/server.py`
(families in `shell.list`), `tests/test_app.py`. **Browser check**: quickstart rows "After 002/PR 2".
Each component is adopted in one existing place in this PR, so none is dead code.

- [x] T007 Add CSS tokens for the five family tints, pen blue, mark yellow and night paper to `:root` and the dark block in `app/hub/static/style.css:14-21`; outline styles double/heavy/solid/dashed for severity (001 FR-012)
- [x] T008 Add `ref(item)` helper and `ItemPill({kind, repo, number, title, state, removable, onRemove})` to `app/hub/static/app.js`: kind icon (reuse `StateIcon`, `app.js:143`), `repo#N` / `workflow #N`, title when there's room, state by outline + icon + accessible name, link to the Work item route, optional remove button (FR-001–FR-004)
- [x] T009 Add `PersonaBadge({persona})` (initials on the family tint, `aria-label` = persona name; reserved pen-blue "S" for `steward`; a separate plain-shell badge) and `FamilyLegend` to `app/hub/static/app.js` (FR-012–FR-015)
- [x] T010 Add `SessionChip({session, pending, onOpen})` to `app/hub/static/app.js`: badge, short name, RUNNING/WAITING/DONE/ATTACHED in words, yellow + "N waiting" only when waiting (FR-016, FR-017)
- [x] T011 Add `RepoPicker({value, onChange, many, allowAll, groups})`: type-to-filter, recents and pins first from `localStorage` (try/catch), then by layer from `/api/overview` groups; >3 selected renders "N repos"; full keyboard (FR-005–FR-007, FR-010)
- [x] T012 Add `ItemPicker({repos, kind, many, onPick})` over `GET /api/work/search` (`app/hub/web.py:202`) and refs typed as `repo#N`; candidates as ItemPills; keyboard (FR-008–FR-010)
- [x] T013 Return `family`, `persona_name`, `initials` in each `agent` of `shell.list` (`hubd/server.py:217-221`) via `describe()` (`hubd/agents.py:1483`)
- [x] T014 Adopt: `WorkRow`'s `sesschip` (`app.js:996`) → `SessionChip`; `WorkRow` ref → `ItemPill`; `RepoSelect` (`app.js:926`) → `RepoPicker` in `NewIssue` and `Dispatch`; Sessions list items (`app.js:2202`) show `PersonaBadge`
- [x] T015 Static tests in `tests/test_app.py`: the five tint values and `#2747b8` / `#ffd86b` defined once as tokens; `ItemPill` never sets a background from state; `RepoPicker` renders a count past 3 (search the component's source for the `> 3` rule)

---

## Dependencies

- PR 1 — Persona families and action metadata: depends on 001/PR 1
- PR 2 — Shared components: depends on PR 1

The build order of all PRs across the ten specs is in [`specs/README.md`](../README.md).

## Parallel opportunities

- Within PR 1: T001, T002, T003 (different files).
