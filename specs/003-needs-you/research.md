# Research: Needs you (spec 003)

Decisions for the open technical questions in `plan.md`. Each one says what was chosen, why,
and what else was looked at. Paths and line numbers are on branch `001-hub-app` at `c81fe71`.
Nothing here was tried for real: these are readings of the code, and the PR that builds each
decision says what it tried (browser, real `claude`, real GitHub).

---

## R1. One Interaction model: a projection, not a new store

- **Decision:** a hubd read op `interaction.list` (behind the login check at
  `hubd/server.py:200`) that projects four existing sources and one new one into one shape
  (`data-model.md` § Interaction):
  - `Asks` (`hubd/asks.py`, memory) → `permission` / `question`;
  - `Decisions` (`hubd/decisions.py`, disk) → `decision` (Go and merge);
  - `NewWork` offers (`hubd/newwork.py`, disk) → `suggestion`; finished drafts → `result` of type
    `drafts`;
  - **new** `Results` store (005 R2) → `result` of the other types.

  Ids keep their source as a prefix (`a:`, `d-…` as today, `w:`, `r:`) so an answer goes to the
  existing op for that source: `ask.answer`, `decision.approve|deny|end`, `work.*`, `result.*`. A
  new `interaction.answer` op only dispatches; it adds no rule of its own.
- **Status mapping (FR-002):** asks keep their states, with `stopped` shown as `ended`; decisions
  `requested` → `pending`, `current`/`using` → `allowed` (shown under Active grants), `ended` after
  approve → `ended`, ended without approval → `denied`, expired request → `timeout`; offers
  `offered`/`planned` → `pending`, `planning`/`starting`/`running`/`started` → `started`,
  `dismissed` → `dismissed`; results `pending` → `pending`, applied → `answered`, set aside →
  `dismissed`. "always" stays the ask's own Always (FR-003). An eye-test Go can't be granted as
  "always" (`decisions.py` `EYE_TEST`, already refused).
- **Who and where (FR-011):** every settle records `by` (the login user, or `terminal`) and `where`
  (the view the page sent: one of the closed `SCREENS` list, plus `Needs you`, `SessionView`). `where`
  is a page claim, checked against the list and shown as such, never trusted for anything.
- **Live updates (FR-013, SC-002):** the app polls `interaction.list` every 3 s, as `Hub` polls
  `asks` today (`app/hub/static/app.js:2763`). Answers made in the terminal show within one poll.
  No push channel is added.
- **Rationale:** the stores have different lifetimes on purpose: an ask lives only while its hook
  holds a connection (`asks.py:1-9`); decisions and drafts survive restarts. Merging them would
  change what a running session's hook sees. The seam already exists: `Hub` sums three sources into
  `asks.waiting` (`app.js:2777`).
- **Alternatives:** one new on-disk interaction table (rewrites asks' hook protocol and the
  decision rules; risks sessions already running); keeping three lists in the app (no single status
  vocabulary, no "handled in this view").
