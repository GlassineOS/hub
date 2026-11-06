# Contract: web API, shared rules and the header (internal)

Owned, internal, unversioned: ships with the app (`app/hub/web.py`). Every route keeps today's
rules: login cookie, same origin for writes (`web.py:32-40`), Host allowlist, errors as
`{"error": words}` with the status `page_error` gives. Shapes reference `../data-model.md`.
Each spec lists the routes it adds or changes in its own `contracts/web-api.md`; "PR n" there is that
spec's PR, "NNN/PR n" another spec's.

## Header

| Method, path | Reply | Source | PR |
|---|---|---|---|
| `GET /api/host` | adds `hubd: "<socket path or address>"` (FR-005); on failure the app shows "hubd can't be reached" | `ping` | PR 2 |
| `GET /api/usage` | `{known, used_pct?, resets_at?, cost_today_usd?, allowance_usd?, low, words}` | `usage.status` (new) | PR 2 |

## Reused unchanged

`/api/login`, `/api/logout`, `/api/issues…`, `/api/prs` list, `/api/prs/{repo}/{n}/threads`,
thread resolve/reply, `/api/runs…`, `/api/runs/{repo}/{id}/log?all=1`, `/api/queue`,
`/api/decisions…` (behind interactions), `/api/device/holding`, `/api/work/search`,
`/api/docs/*`, `/api/agents/*` steps other than those above, `/api/shells/{name}/attach`
(WebSocket).
