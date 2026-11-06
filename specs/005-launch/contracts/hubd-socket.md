# Contract: hubd socket ops for Launch (internal)

One JSON line per request and reply on the unix socket. The login gate and its prefixes are in
[001 `contracts/hubd-socket.md`](../../001-app-frame/contracts/hubd-socket.md).

## Login ops (the page)

| Op | Request | Reply | Notes |
|---|---|---|---|
| `work.start` | today + `covers`, `repos`, `from`, `background` | `{work}` | accepts item actions; refuses an item whose kind isn't the action's `object` (FR-011), naming the item |
| `work.background` **new** | `{token, id, on}` | `{work}` | |
| `work.list` | `{token}` | records add `v`, `covers`, `from`, `plan`, `background`, `result`, `stage` | |
| `result.list` **new** | `{token, type?, kept?, session?, after?}` | `{results}` | |
| `result.apply` **new** | `{token, id, indexes?}` | `{result}` | checks the producing action's tool list covers the write (R2); goes out as that persona's App or the person |
| `result.keep` / `result.dismiss` **new** | `{token, id, …}` | `{result}` | |

## Token ops (the tool server, a session's own token)

| Op | Tool | Request | Reply | Notes |
|---|---|---|---|---|
| `result.submit` **new** | `submit_result` | `{agent_token, type, payload}` | `{ok, id}` or `{refused, error}` | refused unless the token's action has `result == type`; one pending result per session (a new one replaces it while pending); payload closed shape (data-model § Result) |
| `work.submit` | `submit_drafts` | unchanged | | stays for `drafts` |

`STARTED_OPS`, `WORK_TOOL_OPS`, `DECISION_TOOL_OPS`, `REPO_OPS` (`server.py:60-103`) are unchanged.
`result.submit` joins a new `RESULT_TOOL_OPS` map checked like `WORK_TOOL_OPS` (`server.py:714-722`).
