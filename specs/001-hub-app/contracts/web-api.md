# Contract: web API added or changed (internal)

Owned, internal, unversioned: ships with the app (`app/hub/web.py`). Every route keeps today's
rules: login cookie, same origin for writes (`web.py:32-40`), Host allowlist, errors as
`{"error": words}` with the status `page_error` gives. Shapes reference `../data-model.md`.
"PR n" is the stack position in `../tasks.md`.

Existing routes this feature reuses unchanged are listed at the end.

## Sessions

| Method, path | Body / query | Reply | hubd op | PR |
|---|---|---|---|---|
| `GET /api/shells` | — | today's list; each `agent` adds `covers`, `prs`, `view`, `origin`, `permission_mode`, `family`, `persona_name`, `initials`, `pending` (count of pending interactions) | `shell.list` (changed) | 3 |
| `POST /api/agents/view` | `{name, mode: "embedded"\|"background", where, ref?}` | `{view}` | `agent.view` (new) | 3 |
| `POST /api/agents/say` | `{name, text, where}` | `{sent: bool, queued: int}` | `agent.say` (new) | 6 |
| `POST /api/agents/press` | unchanged; still refuses a `text` field | | `agent.press` | — |
| `POST /api/agents/past` | adds filters `{persona?, repo?, outcome?}` | rows add `persona_name`, `family`, `covers` | `agent.past` (changed) | 10 |
| `POST /api/agents/cleanup` | unchanged | rows add `command` (the exact removal command, FR-146) | `agent.cleanup` (changed) | 10 |

`POST /api/agents/send` stays a 400 (unknown step): the chat route is `say`. The test at
`tests/test_app.py:768` changes to assert `say` passes `text` and `press` still drops it.

## Interactions (Needs you)

| Method, path | Body / query | Reply | hubd op | PR |
|---|---|---|---|---|
| `GET /api/interactions` | `?session=` optional (FR-152) | `{items: [Interaction], counts: {pending, blocking, by_kind: {…}, longest_wait}, grants: [Interaction]}` | `interaction.list` (new) | 4 |
| `POST /api/interactions/{id}/answer` | `{verdict, reason?, answers?, words?, scope?, ends?, where}` | `{item: Interaction}` | `interaction.answer` (new, dispatches) | 4 |

`verdict` per kind: permission `allow|always|deny`; question `answer`; decision
`approve|deny|end`; suggestion `dismiss` (Launch… is a page action); result
`apply|dismiss|keep`. `GET /api/asks`, `/api/decisions`, `/api/new-work` stay for one release so a
page loaded before the deploy keeps working; the app stops using them in PR 4/7.

## Launch

| Method, path | Body | Reply | hubd op | PR |
|---|---|---|---|---|
| `POST /api/new-work` | today's fields **plus** `covers`, `repos`, `from`, `background` | `{work: Launch}` | `work.start` (changed: accepts item actions; FR-058 check) | 7 |
| `POST /api/new-work/{id}/background` | `{on: bool}` | `{work}` | `work.background` (new) | 7 |
| `POST /api/new-work/{id}/approve` | today + plan `steps` echoed for display only | `{work}` | `work.approve` | 7 |
| `GET /api/new-work` | — | records add `v`, `covers`, `from`, `plan`, `background`, `result`, `stage` | `work.list` (changed) | 7 |

`POST /api/agents/plan` and `/api/agents/start` remain for one release, then go (PR 9 removes the
callers; a follow-up removes the routes).

## Results

| Method, path | Body | Reply | hubd op | PR |
|---|---|---|---|---|
| `GET /api/results` | `?type=&kept=1&session=` | `{results: [Result]}` (20, `?after=` for more) | `result.list` (new) | 7 |
| `POST /api/results/{id}/apply` | `{indexes?}` (notes ops, labels issues) | `{result}` | `result.apply` (new, login, scope-checked) | 7 (comment, labels), 15 (notes) |
| `POST /api/results/{id}/keep` | `{kept: bool}` | `{result}` | `result.keep` (new) | 7 |
| `POST /api/results/{id}/dismiss` | — | `{result}` | `result.dismiss` (new) | 7 |

## Header

| Method, path | Reply | Source | PR |
|---|---|---|---|
| `GET /api/host` | adds `hubd: "<socket path or address>"` (FR-086); on failure the app shows "hubd can't be reached" | `ping` | 5 |
| `GET /api/usage` | `{known, used_pct?, resets_at?, cost_today_usd?, allowance_usd?, low, words}` | `usage.status` (new) | 5 |

## Work and GitHub actions (as the maintainer)

| Method, path | Body / query | Reply | `gh` call | New ghpolicy entry? | PR |
|---|---|---|---|---|---|
| `GET /api/prs/{repo}/{n}` | — | adds `behind_by`, `merge_blockers: [{why}]` (checks running, not approved, N threads open: FR-074) | `api repos/O/R/compare/<base>...<head>` | no (allowed path); add test line | 11 |
| `POST /api/prs/{repo}/{n}/labels` | `{add, remove}` | `{labels}` | `pr edit N --add-label/--remove-label` | **yes** | 11 |
| `POST /api/issues/{repo}/{n}/assign-me` | — | `{assignees}` | `issue edit N --add-assignee @me` | no (passes today); add allowed + refused cases | 11 |
| `GET /api/runs/{repo}/{id}/failed-step` | — | `{job, step, lines: [{n, text, error: bool}], log_url}` | `api repos/O/R/actions/runs/<id>/jobs` + today's `--log-failed` | no; add test line | 11 |
| `GET /api/prs/{repo}/{n}/files` | — | `[{path, additions, deletions, large: bool}]` | today's `pr view --json files` | no | 11 |
| `GET /api/prs/{repo}/{n}/diff?path=` | unchanged | hunks parsed in the app | today | no | 11 |
| `GET /api/workflows/{repo}` | adds `?inputs=<file>&ref=` | adds `dispatchable: bool`, `inputs: [{name, type: choice\|boolean\|string\|environment, options?, default?, required}]` | `api repos/O/R/contents/.github/workflows/<file>?ref=` | no; add test line | 12 |
| `POST /api/workflows/{repo}/{file}/dispatch` | unchanged (inputs typed by the form) | | today | no | 12 |
| `POST /api/issues/{repo}` | adds `part_of` (written as the body's first line "Part of …") | | today (`issue create --body-file -`) | no | 12 |
| `GET /api/labels/{repo}` | — | `[{name, color, description}]` | `api repos/O/R/labels` | no; add test line | 11 |

Merge stays `POST /api/prs/{repo}/{n}/merge` with `head` (FR-107a, `hubd/server.py:535-562`).
Close/reopen/ready/update-branch/rerun/cancel and full-log download are today's routes.

## Overview, Roadmap

| Method, path | Change | PR |
|---|---|---|
| `GET /api/overview` | rows add `attention` (sort key: failing runs, waiting sessions, open PRs, last activity) and `last_commit`, `last_activity` (FR-090, FR-093) | 13 |
| `GET /api/project` | items add `column` (one of the four, R14) and `progress: [{repo, done, total}]` from sub-issues ∪ "Part of" | 14 |
| `GET /api/device` | unchanged; read by the Overview card | 5 |

## Knowledge

| Method, path | Body / query | Reply | PR |
|---|---|---|---|
| `GET /api/knowledge/search` | `?q=&mode=meaning\|exact&domains=docs,work&repos=&open=1&k=` | `{results: [{domain, kind, title, score, snippet, marks: [[start,end]], ref?, link, sessions?}], domains: [{id, state: "ready"\|"indexing"\|"planned"\|"failed", age}]}` | 15 |
| `GET /api/knowledge/indexes` | — | `[{id, state, age, action: "reindex"\|"sync"\|null}]` from `docs/status` and `work/status` | 15 |

"Run docs CI now" and "Ingest now" call today's `POST /api/docs/reindex` and `POST /api/work/sync`.

## Notes

| Method, path | Body | Reply | hubd op | PR |
|---|---|---|---|---|
| `POST /api/notes/find` | unchanged (POST keeps words out of addresses) | rows add `topic`, `date` when the tool gives them | `notes.find` | 16 |
| `GET /api/notes/totals` | — | `{by_label: {…}, by_topic: {…}, source: "stats"\|"last-search"}` | `notes.totals` (new; R12) | 16 |
| `POST /api/notes/apply` | `{result, indexes}` | `{ops: [{state, command, said}]}` | `notes.apply` (new, login only) | 16 |

## Reused unchanged

`/api/login`, `/api/logout`, `/api/issues…`, `/api/prs` list, `/api/prs/{repo}/{n}/threads`,
thread resolve/reply, `/api/runs…`, `/api/runs/{repo}/{id}/log?all=1`, `/api/queue`,
`/api/decisions…` (behind interactions), `/api/device/holding`, `/api/work/search`,
`/api/docs/*`, `/api/agents/*` steps other than those above, `/api/shells/{name}/attach`
(WebSocket).
