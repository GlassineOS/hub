# Research: App frame (spec 001)

Decisions for the open technical questions in `plan.md`. Each one says what was chosen, why,
and what else was looked at. Paths and line numbers are on branch `001-hub-app` at `c81fe71`.
Nothing here was tried for real: these are readings of the code, and the PR that builds each
decision says what it tried (browser, real `claude`, real GitHub).

Decisions the maintainer already made are not reopened here: sessions are full chats (004 FR-008);
agents merge only under an approved merge decision for the PR head (006 FR-010), the Queue view stays
in Work; Decisions, Go and Active grants become Interaction cards and a filter in the Needs-you
modal; no Device page (device lock on Overview); a small budget meter in the header; navigation
Overview, Roadmap, Work, Knowledge, Notes, Sessions.

---

## R1. Usage budget meter (FR-006)

- **Decision:** hubd adds a `statusLine` command to each session's settings (where `_hooks` writes
  the hooks, `hubd/agents.py:841`) that copies Claude Code's status-line JSON to
  `<session>/status.json`. A new `usage.status` op reads the newest one: if it carries rate-limit
  fields (a used percentage and a reset time), the meter shows those; otherwise it sums today's
  `cost.total_cost_usd` across sessions and planner runs and compares it with an optional
  `HUBD_DAILY_USAGE_USD` allowance; with neither, the meter says "usage not known". It is low at
  80 % and says so in words (FR-006). The GitHub API budget (`Budget`, `app.js:2415`) leaves the
  header and moves to Overview's stats line.
- **Consumed contract:** the status-line input is Claude Code's, not pinned (constitution,
  Contracts). Which fields the installed version sends must be tried with a real `claude` in that
  PR; until then the code path that reads them is marked untested.
- **Alternatives:** parsing transcripts for token counts (no prices, no allowance); a manual figure
  only (always stale); leaving the GitHub budget in place (it is not what FR-006 asks for).

## R2. Remembered per-viewer state

- **Decision:** `localStorage` with try/catch, as the Steward rail does (`app.js:2659`): Work's
  repository selection (006 FR-001), Steward width (010 FR-001), RepoPicker recents and pins (002 FR-006).
  Nothing that must be shared or reliable. Work's filter stays in `sessionStorage` as today.
- **Rationale:** one maintainer; these are conveniences, and the pattern is already used.
- **Alternatives:** settings kept in hubd (a new login op and store for state that can be lost harmlessly).

## R3. Front-end structure

- **Decision:** `app.js` stays one file (no build step; vendor libraries pinned in
  `app/fetch-vendor.sh`). Shared components go in one section near the top, after the helpers
  (`app.js:120-220`), with a comment heading each. CSS adds tokens for the family tints and the
  night-paper terminal to `:root` (`style.css:14-21`), with dark-mode values.
- **Static checks:** `tests/test_app.py` already reads `app.js` as text to pin NAV
  (`tests/test_app.py:914-939`). The yellow rule (FR-011) becomes a test that `--mark` and `#ffd86b`
  appear only in rules whose selectors name waiting states (`.waiting`, `.mark`, `[data-waits]`).
- **Alternatives:** splitting into ES modules (a later, separate change; every PR here would
  conflict with it).

## R4. Phone layout

- **Decision:** CSS at `@media (max-width: 760px)` (the spec's breakpoint; `style.css` uses 720 px
  and 1000 px today, lines 279 and 284 — 720 becomes 760). The header renders "New" and "Menu"; Menu
  is a sheet with the nav, Needs you and the user line. Modals become full sheets by one class. The
  Steward becomes a floating button. Diffs, logs and terminals scroll inside their own box
  (`overflow-x: auto`); the page never does. Tested by hand at 390 px.
- **Rationale:** the spec names 760 px; one phone breakpoint keeps the rules in one block.
- **Alternatives:** keeping 720 px (contradicts FR-007); a JavaScript layout switch (CSS does it without
  a redraw, which matters on e-ink).
