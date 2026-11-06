# Research: Launch (spec 005)

Decisions for the open technical questions in `plan.md`. Each one says what was chosen, why,
and what else was looked at. Paths and line numbers are on branch `001-hub-app` at `c81fe71`.
Nothing here was tried for real: these are readings of the code, and the PR that builds each
decision says what it tried (browser, real `claude`, real GitHub).

---

## R1. Launch records: generalize NewWork

- **Decision:** every Launch, for every action kind, is a record in the existing `NewWork` store
  (`hubd/newwork.py`, folder `state/newwork`), extended with fields (`data-model.md` § Launch). The
  record's `state` is the stage: `brief` lives only in the page; a record is made when planning
  starts (FR-010 "every Launch is recorded"); `planning` → `planned` → `starting` → `running`
  (or `started` for item sessions, as today, `hubd/server.py:787-790`) → `done` with a result →
  `filed`/`dismissed`; `failed` on any error. Records carry `v: 2`; records without `v` read as
  today.
- **What moves:** item actions plan in the browser today (`plans` Map, `app.js:540`; `agents.plan`
  via `agent.plan`). They now go through `work.start` with `covers`, and `work.start`'s refusal of a
  `number` (`hubd/server.py:829-830`) is replaced by the FR-011 kind check. `agent.plan`/`agent.start`
  stay for one release so a page loaded before the deploy still works, then go.
- **Plan steps (FR-006):** the planner schema (`Library.schema`, `hubd/agents.py:233`) gains
  `steps: [{what, touches: [string]}]` (at most 12 steps, 8 touches each, 300 characters). Steps are
  planner text and go into the prompt below the existing "prepared by a planner" banner
  (`agents.py:829-831`).
- **Background (FR-008):** the record has `background: bool`, set by `work.background`; the toast
  and Needs you read it. The session's own `view.json` (004 R1) follows.
- **Restart:** `_after_restart` (`newwork.py:82`) already fails `planning`/`starting`; the same
  applies to item launches.
- **Rationale:** the store already has the stages, on disk, survives restarts, and is what
  suggestions use; two stores would mean two "started" rules.
- **Alternatives:** a new `launches` module (duplicates `_after_restart`, pruning, Steward
  notifications); keeping item plans in the browser (no FR-010 record, lost on reload).

## R2. Results: one store, handed in by a tool, applied by a login

- **Decision:** a new `hubd/results.py` store (`state/results/<id>.json`, 0700, pruned like
  `newwork`), a new tool `submit_result(type, payload)` that validates the payload against a closed
  shape per type (`data-model.md` § Result) and refuses any type other than the session's action's
  `result`. `drafts` keeps `submit_drafts` (unchanged for running sessions). Applying a result is a
  login op `result.apply` that runs the write **under the session's own scope**: it checks that the
  producing action lists the tool the write needs (`review_pr`, `label_issue`, `edit_issue`, …) and
  goes out through the same path as that tool, so a result can never do more than its session could
  (FR-014, 001 FR-024). The person's press is the go-ahead; the write goes out as the persona's App when
  there is one (`SECURITY.md` "Personas on GitHub"), else as the person.
- **Per type:** `comment` → one review with inline notes (needs a GraphQL document, 006 R1);
  `labels` → `label_issue` per issue plus "Part of" via `edit_issue` with its `expected` guard;
  `findings` → nothing to apply, "Start a fix session" opens Launch; `report` → `result.keep` marks
  it saved for Knowledge (stays in hubd state, never committed anywhere); `notes` → `notes.apply`
  (009 R1); `pr` → nothing to apply, the card links the PR from `prs[]`.
- **Rationale:** the drafts flow (`submit_drafts` → nothing filed until you choose,
  `docs/orchestrator.md:88-108`) is the proven pattern; reusing the session's scope keeps the ceiling
  enforced in one place.
- **Alternatives:** the session posts directly as today and the card only shows what it did (no
  "Post" step, contradicts FR-017/FR-018); applying as the person with no scope check (a result
  could exceed its action).

## R3. Departures this forces on running actions (say before building)

- **`pr-review` posts its own review today** (`agents/actions/pr-review.toml`, tool `review_pr`).
  With `result = "comment"` it hands in the summary and inline notes and the person presses Post
  (FR-017). New sessions lose `review_pr` from their tool list and gain `submit_result`; a session
  already running keeps the tools it started with (its scope is frozen in its token,
  `agents.py:496`), so it may still post directly. **Needs the maintainer's yes before the Launch
  backend PR**: it changes what an existing action does.
- **`issue-triage` labels directly today.** Same change, `result = "labels"`, same rule for running
  sessions.
