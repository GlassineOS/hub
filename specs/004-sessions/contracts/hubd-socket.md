# Contract: hubd socket ops for Sessions (internal)

One JSON line per request and reply on the unix socket. The login gate and its prefixes are in
[001 `contracts/hubd-socket.md`](../../001-app-frame/contracts/hubd-socket.md).

## Login ops (the page)

| Op | Request | Reply | Notes |
|---|---|---|---|
| `shell.list` | `{token}` | each `agent` adds `covers`, `prs`, `view`, `origin`, `permission_mode`, `family`, `persona_name`, `initials` | `describe()` folds `also_numbers` into `covers` for old records |
| `agent.view` **new** | `{token, name, mode, where, ref?}` | `{view}` | writes `view.json`; `where` from `SCREENS` |
| `agent.say` **new** | `{token, name, text, where}` | `{sent, queued}` | `Agents._send(name, text)`; 1–4000 chars, no control characters; paste via `tmux load-buffer -` on stdin (R2) |
| `agent.past` | `{token, persona?, repo?, outcome?}` | rows add `persona_name`, `family`, `covers` | |
| `agent.cleanup` | `{token, after_merge?}` | rows add `command` (exact `git worktree remove …` line) | the command shown is the one `_remove_if_safe` runs |
