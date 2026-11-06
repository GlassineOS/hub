# Contract: web API routes for Work (internal)

Owned, internal, unversioned: ships with the app (`app/hub/web.py`). Every route keeps the rules
in [001 `contracts/web-api.md`](../../001-app-frame/contracts/web-api.md). Shapes reference `../data-model.md` or the
spec named. "PR n" is this spec's PR in `../tasks.md`; "NNN/PR n" is another spec's.

## Work and GitHub actions (as the maintainer)

| Method, path | Body / query | Reply | `gh` call | New ghpolicy entry? | PR |
|---|---|---|---|---|---|
| `GET /api/prs/{repo}/{n}` | — | adds `behind_by`, `merge_blockers: [{why}]` (checks running, not approved, N threads open: FR-031) | `api repos/O/R/compare/<base>...<head>` | no (allowed path); add test line | PR 1 |
| `POST /api/prs/{repo}/{n}/labels` | `{add, remove}` | `{labels}` | `pr edit N --add-label/--remove-label` | **yes** | PR 1 |
| `POST /api/issues/{repo}/{n}/assign-me` | — | `{assignees}` | `issue edit N --add-assignee @me` | no (passes today); add allowed + refused cases | PR 1 |
| `GET /api/runs/{repo}/{id}/failed-step` | — | `{job, step, lines: [{n, text, error: bool}], log_url}` | `api repos/O/R/actions/runs/<id>/jobs` + today's `--log-failed` | no; add test line | PR 1 |
| `GET /api/prs/{repo}/{n}/files` | — | `[{path, additions, deletions, large: bool}]` | today's `pr view --json files` | no | PR 1 |
| `GET /api/prs/{repo}/{n}/diff?path=` | unchanged | hunks parsed in the app | today | no | PR 1 |
| `GET /api/workflows/{repo}` | adds `?inputs=<file>&ref=` | adds `dispatchable: bool`, `inputs: [{name, type: choice\|boolean\|string\|environment, options?, default?, required}]` | `api repos/O/R/contents/.github/workflows/<file>?ref=` | no; add test line | PR 2 |
| `POST /api/workflows/{repo}/{file}/dispatch` | unchanged (inputs typed by the form) | | today | no | PR 2 |
| `POST /api/issues/{repo}` | adds `part_of` (written as the body's first line "Part of …") | | today (`issue create --body-file -`) | no | PR 2 |
| `GET /api/labels/{repo}` | — | `[{name, color, description}]` | `api repos/O/R/labels` | no; add test line | PR 1 |

Merge stays `POST /api/prs/{repo}/{n}/merge` with `head` (FR-010, `hubd/server.py:535-562`).
Close/reopen/ready/update-branch/rerun/cancel and full-log download are today's routes.
