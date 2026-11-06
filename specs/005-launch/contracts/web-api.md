# Contract: web API routes for Launch (internal)

Owned, internal, unversioned: ships with the app (`app/hub/web.py`). Every route keeps the rules
in [001 `contracts/web-api.md`](../../001-app-frame/contracts/web-api.md). Shapes reference `../data-model.md` or the
spec named. "PR n" is this spec's PR in `../tasks.md`; "NNN/PR n" is another spec's.

## Launch

| Method, path | Body | Reply | hubd op | PR |
|---|---|---|---|---|
| `POST /api/new-work` | today's fields **plus** `covers`, `repos`, `from`, `background` | `{work: Launch}` | `work.start` (changed: accepts item actions; FR-011 check) | PR 1 |
| `POST /api/new-work/{id}/background` | `{on: bool}` | `{work}` | `work.background` (new) | PR 1 |
| `POST /api/new-work/{id}/approve` | today + plan `steps` echoed for display only | `{work}` | `work.approve` | PR 1 |
| `GET /api/new-work` | — | records add `v`, `covers`, `from`, `plan`, `background`, `result`, `stage` | `work.list` (changed) | PR 1 |

`POST /api/agents/plan` and `/api/agents/start` remain for one release, then go (PR 2 removes the
callers; a follow-up removes the routes).

## Results

| Method, path | Body | Reply | hubd op | PR |
|---|---|---|---|---|
| `GET /api/results` | `?type=&kept=1&session=` | `{results: [Result]}` (20, `?after=` for more) | `result.list` (new) | PR 1 |
| `POST /api/results/{id}/apply` | `{indexes?}` (notes ops, labels issues) | `{result}` | `result.apply` (new, login, scope-checked) | PR 1 (comment, labels), 009/PR 1 (notes) |
| `POST /api/results/{id}/keep` | `{kept: bool}` | `{result}` | `result.keep` (new) | PR 1 |
| `POST /api/results/{id}/dismiss` | — | `{result}` | `result.dismiss` (new) | PR 1 |
