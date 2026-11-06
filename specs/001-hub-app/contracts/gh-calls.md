# Contract: `gh` calls and ghpolicy entries (consumed GitHub, owned policy)

`hubd/ghpolicy.py` is an allowlist and fails closed. Every row marked **new entry** changes the
policy and lands with allowed and refused cases in `tests/test_ghpolicy.py` in the same PR
(`CLAUDE.md`). Rows marked "test line" use an already allowed shape but still get an `ALLOWED` line,
so a later tightening of the path pattern can't silently break them.

Every GhActions action (FR-069–FR-081) runs as the logged-in maintainer: the app calls
`hubd.gh(..., login=token)` or a route whose hubd op runs under the host login, never an agent
token (FR-070).

| GhActions action | Call | Policy | Disabled when (shown in words, FR-071) |
|---|---|---|---|
| PR: Merge… (squash/merge/rebase) | `pr merge N -R O/R --<method> --match-head-commit <sha>` | today (`ghpolicy.py:154-182`, `:203-204`) | checks running; review not approved (`reviewDecision`); N review threads open (FR-074) |
| PR: Mark ready | `pr ready N -R O/R` | today | not a draft |
| PR: Update branch | `pr update-branch N -R O/R` | today | 0 behind (count from compare, below) |
| PR: Labels… | `pr edit N -R O/R --add-label L --remove-label L` | **new entry**: `pr edit` only with `--add-label`/`--remove-label`; refused with `--title`, `--body`, `--body-file`, `--base`, `--add-reviewer`, `--add-assignee`, `--milestone` | — |
| PR: Close / Reopen | `pr close N -R O/R` / `pr reopen N -R O/R` | close today; **reopen is a new entry** (`pr reopen` not in `_COMMANDS["pr"]`) | merged PRs can't reopen |
| Issue: Close as completed / not planned | `issue close N -R O/R --reason completed\|"not planned"` | today | already closed |
| Issue: Reopen | `issue reopen N -R O/R` | today | open |
| Issue: Labels… | `issue edit N -R O/R --add-label/--remove-label` | today (`issue edit` allowed); test line | — |
| Issue: Assign to me | `issue edit N -R O/R --add-assignee @me` | passes today; **allowed case `@me`, refused case for `--add-assignee someone-else` and `--remove-assignee`** (narrowing, so it's a policy change) | assigned to you |
| Run: Re-run failed / all | `run rerun ID -R O/R [--failed]` | today | running |
| Run: Cancel run | `run cancel ID -R O/R` | today | completed |
| Run: Download full log | `run view ID -R O/R --log` | today | — |
| Work: New issue… | `issue create -R O/R --title T --body-file - [--label L]` | today | — |
| Work: Run workflow… | `workflow run FILE -R O/R --ref REF -f k=v` | today (`@file` refused, `ghpolicy.py:115-117`) | no `workflow_dispatch` workflow (FR-080) |
| any: Open on GitHub | a link, no call | — | — |

Reads added (all under `repos/GlassineOS/<repo>/…`, read-only, test lines):

| Use | Path |
|---|---|
| behind count (FR-073) | `repos/GlassineOS/R/compare/<base>...<head>` |
| workflow inputs (FR-079) | `repos/GlassineOS/R/contents/.github/workflows/<file>?ref=<ref>` |
| repository labels (Labels…) | `repos/GlassineOS/R/labels?per_page=100` |
| failed step (FR-119) | `repos/GlassineOS/R/actions/runs/<id>/jobs` |

Refused cases to add with them: `compare/../../x`, a `%2e%2e` path, `contents/` with `{` placeholders,
a path outside `GlassineOS`.

## GraphQL documents

| Document | Use | Policy | PR |
|---|---|---|---|
| `pr_review_add.graphql` **new** | Post a comment result: one review with inline threads (FR-064) | mutation, run only by name; its `pullRequestId` must be the organization's (checked like `content_owner.graphql`) | 7 |
| `pr_threads.graphql` | threads for Conversation ticks (FR-115) | today | — |

## Agent writes (FR-175, SC-005)

Agents reach GitHub only through tools, each a fixed `gh` shape above or today's. Tests per kind
(issue, PR, run, workflow, api, graphql) keep at least one refused agent call:
`tests/test_ghpolicy.py` `REFUSED` already covers most; the PR that adds `pr edit` adds
`pr edit --body-file /etc/passwd` and `pr edit --add-reviewer x`.
