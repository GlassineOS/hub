# Contract: `gh` calls for Launch results (owned policy)

The allowlist rules are in [006 `contracts/gh-calls.md`](../../006-work/contracts/gh-calls.md).

## GraphQL documents

| Document | Use | Policy | PR |
|---|---|---|---|
| `pr_review_add.graphql` **new** | Post a comment result: one review with inline threads (FR-017) | mutation, run only by name; its `pullRequestId` must be the organization's (checked like `content_owner.graphql`) | PR 1 |
