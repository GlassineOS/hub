# Research: Notes (spec 009)

Decisions for the open technical questions in `plan.md`. Each one says what was chosen, why,
and what else was looked at. Paths and line numbers are on branch `001-hub-app` at `c81fe71`.
Nothing here was tried for real: these are readings of the code, and the PR that builds each
decision says what it tried (browser, real `claude`, real GitHub).

---

## R1. Notes upkeep: totals and applying operations

- **Facts:** the `notes` CLI (workspace repository, consumed) has `add`, `set` (`--replaces`,
  `--retract`, `--close`, `--by`, `--why`, `--open`), `lint` and `find --json`. hubd runs only `find`
  (`hubd/notes.py:107-131`). There is no `merge`, `distil`, `flag` or totals command.
- **Decision:**
  - **Operations** map onto existing verbs, each an exact command shown on the card: `supersede` →
    `notes set TOPIC WORDS --replaces ID`; `retract` → `notes set TOPIC --retract ID --why …`;
    `answer` → `notes set TOPIC WORDS --close ID --by ID`; `status` → `notes set TOPIC --open|…`;
    `merge`/`distil` → one `notes add` (the merged text) followed by `notes set --replaces` for each
    merged id; `flag` → `notes set TOPIC --open --why …`. None deletes (005 FR-021). hubd gains
    `notes.apply(op)` behind the login: a closed op list, every argument checked
    (topic `[a-z0-9-]+`, ids from the tool's own format, words after `--`), run as `find` is run
    (`-I`, fixed env, no shell). A `SECURITY.md` "Notes" paragraph change in the same PR: this is
    hubd's first notes write.
  - **Totals per label and topic (FR-005):** need a `notes stats --json` command in the workspace
    repository. That is a change in another repository (constitution IV); until it lands, the flyout
    shows totals counted from the last search's rows and says so. Filed as a dependency in the Notes
    PR.
- **Alternatives:** hubd reading `notes/` files itself (they never passed the safety scan,
  `hubd/notes.py:3-8`, and the format is the tool's business).
