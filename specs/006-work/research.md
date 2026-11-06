# Research: Work (spec 006)

Decisions for the open technical questions in `plan.md`. Each one says what was chosen, why,
and what else was looked at. Paths and line numbers are on branch `001-hub-app` at `c81fe71`.
Nothing here was tried for real: these are readings of the code, and the PR that builds each
decision says what it tried (browser, real `claude`, real GitHub).

---

## R1. GitHub calls: reads under the allowed `gh api` path, three new write shapes

- **Reads, no policy change:** `gh api repos/GlassineOS/<repo>/(.*)` is already allowed read-only
  (`hubd/ghpolicy.py:50-54`). Used for the behind count (`compare/<base>...<head>`), workflow inputs
  (`contents/.github/workflows/<file>?ref=<ref>`, parsed in the app container with a small YAML
  subset reader for `on.workflow_dispatch.inputs`; no YAML library), repository labels (`labels`),
  and the failed step of a run (`actions/runs/<id>/jobs`). Each new path shape gets a line in
  `tests/test_ghpolicy.py` `ALLOWED` and a traversal case in `REFUSED`. `reviewDecision` is already
  in `_PR_FIELDS` (`app/hub/github.py:25`).
- **New allowlist entries (ghpolicy change, tests in the same PR):**
  1. PR labels: `pr edit <n> --add-label/--remove-label` — `pr edit` is not in
     `_COMMANDS["pr"]` (`ghpolicy.py:30`). Allowed only with `--add-label`/`--remove-label`, refused
     with `--title`, `--body`, `--base`, `--add-reviewer` etc. (If `gh issue edit` on a PR number
     is found to work with the installed `gh`, that path needs no entry; to be tried for real.)
  2. "Assign to me": `issue edit <n> --add-assignee @me` already passes `_check_flags`; it gets an
     allowed case and a refused case for any other login.
  3. Reopen a PR (FR-030 "Close/Reopen"): `pr reopen` is not in `_COMMANDS["pr"]` either; added
     with an allowed case and a refused `--comment-file` case.
  4. Inline review comments for a comment result: a new GraphQL document
     `hubd/graphql/pr_review_add.graphql` (`addPullRequestReview` with `threads`), whose pull request
     id is checked to belong to the organization like the existing content-id checks.
- **Rationale:** the policy is an allowlist of what the app runs; reads through the existing path
  need no widening, writes are named one by one.
- **Alternatives:** `gh api -X POST` for reviews (would make `gh api` writable, against
  `ghpolicy.py:13-16`); reading workflow files from the hub's seed copies (`hubd/seeds.py`) —
  possible, but can lag the branch the person picks.
