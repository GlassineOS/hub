# Contract: agent writes to GitHub (owned policy)

`hubd/ghpolicy.py` is an allowlist and fails closed. The GhActions calls the maintainer makes are in
[006 `contracts/gh-calls.md`](../../006-work/contracts/gh-calls.md).

## Agent writes (FR-022, SC-001)

Agents reach GitHub only through tools, each a fixed `gh` shape above or today's. Tests per kind
(issue, PR, run, workflow, api, graphql) keep at least one refused agent call:
`tests/test_ghpolicy.py` `REFUSED` already covers most; the PR that adds `pr edit` adds
`pr edit --body-file /etc/passwd` and `pr edit --add-reviewer x`.
