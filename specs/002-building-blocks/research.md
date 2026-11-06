# Research: Building blocks (spec 002)

Decisions for the open technical questions in `plan.md`. Each one says what was chosen, why,
and what else was looked at. Paths and line numbers are on branch `001-hub-app` at `c81fe71`.
Nothing here was tried for real: these are readings of the code, and the PR that builds each
decision says what it tried (browser, real `claude`, real GitHub).

---

## R1. Where the persona family and display data live

- **Decision:** a new `agents/personas/families.toml`, read by `Library` like
  `steward-buttons.toml` (`hubd/agents.py:218`). One table per persona id:
  `name` (display name, e.g. "Code reviewer"), `initials` (1–2 letters), `family` (one of
  `build`, `review`, `investigate`, `write`, `organise`). `Library` refuses to load when a persona
  `.md` has no entry or a family is outside the five, so a new persona can't ship without one. The
  Steward is `organise` in the file but the app draws it with its own pen-blue "S" (FR-013); a plain
  shell is not a persona and has its own badge (FR-014).
- **Rationale:** persona `.md` files are pasted into the session's prompt
  (`_write_persona`, `hubd/agents.py:958`), so front matter would reach the model. A separate file
  keeps prompt text and UI metadata apart and is additive to the owned action/persona contract: a
  session already running never reads it.
- **Alternatives:** front matter in each `.md` (leaks into the prompt, needs stripping);
  hard-coding the table in `app.js` (the library is the owned contract, and `hubd` needs the family
  for `interaction.list` and history filters).

## R2. Action short names, result types, and the 005 FR-012 table

- **Decision:** every action TOML gains `verb` (the spec's short name: review, address, fix,
  implement, triage, investigate, issue, sec, arch, road, docs, deps, compact, sweep, research) and
  `result` (`comment`, `pr`, `labels`, `findings`, `drafts`, `report`, `notes`). The table maps onto
  existing files like this:

  | verb | file | persona today | change |
  |---|---|---|---|
  | review | `pr-review.toml` | reviewer | `result = "comment"` (see 005 R3) |
  | address | `pr-address-review.toml` | engineer | `result = "pr"` |
  | fix (PR) | `pr-fix-checks.toml` | engineer | persona `ci-fixer` added as first choice |
  | fix (run) | **new** `run-fix.toml` | ci-fixer | full, `checkout = "new-branch"` from the run's head branch |
  | implement | `issue-implement.toml` | engineer | `result = "pr"` |
  | triage | `issue-triage.toml` | triager | `result = "labels"` (see 005 R3) |
  | investigate | `run-diagnose.toml` | ci-diagnostician | `result = "findings"` |
  | issue, sec, arch, road, docs, deps | `new-*.toml` | as today | `result = "drafts"` (exists: `submit_drafts`) |
  | compact | **new** `notes-compact.toml` | **new** archivist | `object = "notes"`, `result = "notes"` |
  | sweep | **new** `notes-sweep.toml` | docs-writer | `object = "notes"`, `result = "drafts"` |
  | research | **new** `knowledge-research.toml` | **new** researcher | `object = "knowledge"`, `result = "report"` |

  The actions the spec's table doesn't list (`pr-explain`, `pr-merge-prep`, `pr-session`,
  `pr-security-audit`, `issue-docs`, `issue-session`, `run-explain`, `run-flaky`, `run-slow`) stay
  in the library, with `result = "none"` where they only talk in the terminal, and appear under a
  "More…" menu in Launch, never as a row's blue button. **This departs from 005 FR-012's "the action
  library has these actions"**: the spec reads as a closed list; removing working actions isn't
  asked for anywhere else. Said here before it's built.
- **"Kernel engineer (the repository's engineer)":** there is one `engineer` persona today. The
  display name can come from `config/repos.toml` (optional `engineer = "Kernel engineer"` per
  repository); the persona file stays the same. A per-repository persona prompt is out of scope.
- **Ceiling vs item kind (005 FR-011):** the action's `object` already decides this (`validate`,
  `hubd/agents.py:248-268`). Launch adds a check across `covers[]` (004 R1): every covered item must be
  of the action's object kind, and the refusal says which item and why.
- **Rationale:** smallest change to an owned contract; old sessions keep their action text.
- **Alternatives:** renaming files to the short names (breaks history rows and resumes that name the
  old id: `hubd/history.py`); a separate verb→file map in the app (two sources of truth).
