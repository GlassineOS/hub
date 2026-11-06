# Contract: web API routes for Sessions (internal)

Owned, internal, unversioned: ships with the app (`app/hub/web.py`). Every route keeps the rules
in [001 `contracts/web-api.md`](../../001-app-frame/contracts/web-api.md). Shapes reference `../data-model.md` or the
spec named. "PR n" is this spec's PR in `../tasks.md`; "NNN/PR n" is another spec's.

## Sessions

| Method, path | Body / query | Reply | hubd op | PR |
|---|---|---|---|---|
| `GET /api/shells` | — | today's list; each `agent` adds `covers`, `prs`, `view`, `origin`, `permission_mode`, `family`, `persona_name`, `initials`, `pending` (count of pending interactions) | `shell.list` (changed) | PR 1 |
| `POST /api/agents/view` | `{name, mode: "embedded"\|"background", where, ref?}` | `{view}` | `agent.view` (new) | PR 1 |
| `POST /api/agents/say` | `{name, text, where}` | `{sent: bool, queued: int}` | `agent.say` (new) | PR 2 |
| `POST /api/agents/press` | unchanged; still refuses a `text` field | | `agent.press` | — |
| `POST /api/agents/past` | adds filters `{persona?, repo?, outcome?}` | rows add `persona_name`, `family`, `covers` | `agent.past` (changed) | PR 4 |
| `POST /api/agents/cleanup` | unchanged | rows add `command` (the exact removal command, FR-021) | `agent.cleanup` (changed) | PR 4 |

`POST /api/agents/send` stays a 400 (unknown step): the chat route is `say`. The test at
`tests/test_app.py:768` changes to assert `say` passes `text` and `press` still drops it.
