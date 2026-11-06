---
description: "Task list for spec 003 (needs you), as a stack of pull requests"
---

# Tasks: Needs you

**Input**: `specs/003-needs-you/` — spec.md, plan.md, research.md, data-model.md, contracts/; the dev hub and browser checks are in `specs/001-app-frame/quickstart.md`.

**Organization**: by **pull request**. The format (`[P]`, `[US#]`), the tests rule and the three
steps every PR ends with are in [`specs/README.md`](../README.md) § Tasks. `[USk]` is this spec's
scenario k, `[NNN/USk]` another spec's; `NNN/PR k` is another spec's PR.

## Scenario → PR map

| Scenario | PRs |
|---|---|
| US1 Answer a blocking prompt from any screen (P1) | PR 1, 001/PR 2 |
| US2 Grant a Go for a device run (P2) | PR 1, 001/PR 2 |

## Requirements of this spec built by other specs' PRs

- 005/PR 1 — Launch records, stages and results: backend: FR-010
- 005/PR 2 — Launch UI: FR-009, FR-010

---

## PR 1 — Interactions, Feed and the Needs-you modal (L)

**Delivers**: FR-001–FR-009, FR-011–FR-017, FR-018–FR-022, 001 FR-011 (cards), SC-001, SC-002.
Result data (FR-010) comes in 005/PR 1, result cards in 005/PR 2. **Depends on**: 002/PR 2, 004/PR 1. **Scenarios**: US1, US2.
**Files**: `hubd/server.py`, `app/hub/web.py`, `app/hub/static/app.js` (`Ask`, `Inbox`,
`SessionTabs`, `ActiveDecisions`, `DecisionsPage`, `GoPanel`, `DecisionRow`, `WorkWaiting`,
`SuggestedSession`, `Hub`), `app/hub/static/style.css`, `tests/test_hubd.py`, `tests/test_app.py`.
**Browser check**: quickstart rows "After 003/PR 1". The old Sessions › Needs you and Active tabs and the
`#/decisions` route open the modal (with the matching filter) instead, so no screen is
half-migrated.

- [ ] T001 [US1] Add `interaction.` to the login-gated prefixes at `hubd/server.py:200` and implement `interaction.list` projecting `Asks.list()` (`hubd/asks.py:202`), `Decisions` (`hubd/decisions.py`), NewWork offers and done drafts (`hubd/newwork.py:233`) into the data-model Interaction shape, with `counts` (pending, blocking, by kind, longest wait) and `grants` (allowed decisions with `left`)
- [ ] T002 [US1] Implement `interaction.answer` dispatching by id prefix to `ask.answer`, `decision.approve|deny|end`, `work.dismiss`; record `handled = {by: login user, where, at}` on the source (asks: a field on `Ask`; decisions and offers: a field in their record)
- [ ] T003 [US2] Map statuses per research R1, including decisions' `timeout` (request older than `REQUEST_LIFE`, `hubd/decisions.py:38`) and asks' `stopped` → `ended`; eye-test Go can't be "always" (already in `decisions.py`; assert it)
- [ ] T004 Expose `GET /api/interactions` and `POST /api/interactions/{id}/answer` in `app/hub/web.py` (routes list `:412-462`); keep `/api/asks`, `/api/decisions`, `/api/new-work` for old pages
- [ ] T005 [US1] Replace the `asks` and `decisions` polls in `Hub` (`app.js:2763-2777`) with one 3 s poll of `/api/interactions`; keep the `/api/new-work` poll until 005/PR 2, as `NewWork`, `StartForm` and `SetAside` read `asks.work`; keep the "failed read keeps what we knew" rule (`app.js:2765`)
- [ ] T006 [US1] Add `InteractionCard` with one body per kind, reusing `AskContent`/`AskQuestion` (`app.js:1426-1480`) for permission and question, `DecisionRow`'s approve/deny form (`app.js:2497`) for decisions, `GoForm` fields (`app.js:2442`) for the Go card (actions, device, ends after N runs/hours; eye-test note, FR-007), `SuggestedSession` (`app.js:1885`) for suggestions (its "Launch…" opens today's `StartForm` until 005/PR 2)
- [ ] T007 [US1] Add `Feed({items, filter, dense, session})`: groups Blocking (oldest first), Suggested (with "Decisions asked for" first), Results ready; filter All / The Steward / Other sessions; dense one-line mode; each card links its session (SessionChip) and items (ItemPill) (FR-014–FR-017)
- [ ] T008 [US1] Add `NeedsYouModal`: opens over any view, sheet class at phone width, focus trap, Esc closes and returns focus to the opener (FR-018, FR-022, 001 FR-016); filters include "Active grants" (Go and merge decisions in force with what's left and "End now", FR-020) and a session filter (FR-021); "Record a go…" and "I've got the device" from `GoPanel` (`app.js:2473`) move into it
- [ ] T009 [US1] "N handled in this view" line: interactions settled since the view mounted, with final status, who and where, until the route changes (FR-011)
- [ ] T010 Open the modal from a temporary "Needs you" entry on the Sessions tab bar and from the Sessions nav count (`app.js:2798-2801`) until 001/PR 2 moves it to the header; route `#/shells?tab=needs`, `tab=active` and `#/decisions` to the modal with the matching filter; delete `Inbox`, `ActiveDecisions`, `DecisionsPage` and `SessionTabs`' needs/active tabs (`app.js:1991-2045`, `:2157-2168`, `:2526-2546`)
- [ ] T011 Tests in `tests/test_hubd.py`: `interaction.list` refuses a token; every status in FR-002 produced from a fixture of each source; answering through `interaction.answer` settles the source and records `handled.by`; a token can't call `interaction.answer`; eye-test Go refused as "always"; Go `left` counts down after `decision.use`
- [ ] T012 Tests in `tests/test_app.py`: `/api/interactions` needs a login and same origin for answers; replace `test_decisions_wait_under_needs_you_and_stand_under_active_without_a_nav_entry` and `test_queue_and_notes_are_tabs_and_the_go_is_in_needs_you` (`tests/test_app.py:914-943`) with checks that `GoPanel` is in `NeedsYouModal` and `DecisionsPage` is gone

---

## Dependencies

- PR 1 — Interactions, Feed and the Needs-you modal: depends on 002/PR 2, 004/PR 1

The build order of all PRs across the ten specs is in [`specs/README.md`](../README.md).
