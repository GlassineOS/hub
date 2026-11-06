---
description: "Task list for spec 010 (steward), as a stack of pull requests"
---

# Tasks: Steward

**Input**: `specs/010-steward/` — spec.md, plan.md, contracts/; the dev hub and browser checks are in `specs/001-app-frame/quickstart.md`.

**Organization**: by **pull request**. The format (`[P]`, `[US#]`), the tests rule and the three
steps every PR ends with are in [`specs/README.md`](../README.md) § Tasks. `[USk]` is this spec's
scenario k, `[NNN/USk]` another spec's; `NNN/PR k` is another spec's PR.

## Scenario → PR map

| Scenario | PRs |
|---|---|
| US1 Plan new work from the current view (P2) | PR 1 |

## Requirements of this spec built by other specs' PRs

- 004/PR 2 — Typed messages: sessions are chats: FR-006
- 004/PR 3 — SessionView: FR-003

---

## PR 1 — Steward panel (M)

**Delivers**: FR-001–FR-006. **Depends on**: 004/PR 3, 005/PR 2. **Files**: `app/hub/static/app.js`
(`Steward`, `StewardSession`, `StewardModel`, `seenFrom`, `keptRail`), `app/hub/static/style.css`,
`hubd/agents.py` (`set_context` repos), `tests/test_app.py`, `tests/test_agents.py`.
**Browser check**: quickstart "After 010/PR 1".

- [ ] T001 Resizable panel 320–760 px with a keyboard-operable handle, width in `localStorage` (FR-001)
- [ ] T002 Default open on Overview, Roadmap, Work and Work item; collapsed on Sessions, Knowledge and Notes; a viewer's own choice per view remembered (replace `keptRail`, `app.js:2659`) (FR-002)
- [ ] T003 Compact `SessionView` with the model and `StewardModel`'s select (FR-003)
- [ ] T004 SEES chips: view, selected repositories (≤ 3, else a count), open item; `agent.context` carries `repos` (FR-004)
- [ ] T005 Waiting strip: count of the Steward's pending interactions, opens Needs you filtered to `steward` (FR-005)
- [ ] T006 "＋ Plan new work with the Steward": sends the current view's context as a request with the person's own words (`agent.say`) (FR-006)
- [ ] T007 Tests: default open/closed per view (static); `set_context` validates `repos` names and caps them

---

## Dependencies

- PR 1 — Steward panel: depends on 004/PR 3, 005/PR 2

The build order of all PRs across the ten specs is in [`specs/README.md`](../README.md).
