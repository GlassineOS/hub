# Contract: hubd socket ops added or changed (internal)

One JSON line per request and reply on the unix socket (`hubd/server.py:1-12`). Owned, internal,
ships with the app. Every op below that acts for the person sits behind the login check at
`hubd/server.py:200-216`, which today covers ops starting `agent.`, `ask.`, `work.`, `decision.`,
`notes.` and the shell ops. **New prefixes `interaction.`, `result.` and `usage.` are added to that
tuple**, so a token can't reach them. Token ops (tool server) are listed separately.

## Login ops (the page)

| Op | Request | Reply | Notes |
|---|---|---|---|
| `shell.list` | `{token}` | each `agent` adds `covers`, `prs`, `view`, `origin`, `permission_mode`, `family`, `persona_name`, `initials` | `describe()` folds `also_numbers` into `covers` for old records |
| `agent.view` **new** | `{token, name, mode, where, ref?}` | `{view}` | writes `view.json`; `where` from `SCREENS` |
| `agent.say` **new** | `{token, name, text, where}` | `{sent, queued}` | `Agents._send(name, text)`; 1–4000 chars, no control characters; paste via `tmux load-buffer -` on stdin (R5) |
| `agent.context` | `{token, name, screen, kind?, selection?, repos?}` | `{}` | `SCREENS` becomes `Overview, Roadmap, Work, Knowledge, Notes, Sessions, Queue` (drops `Docs`, `Device`, `Decisions`); adds `repos` (≤ 3 named, else a count) for SEES chips (FR-157) |
| `agent.actions` | `{token, object?}` | actions add `verb`, `result`, `family`, `persona_name` | |
| `agent.past` | `{token, persona?, repo?, outcome?}` | rows add `persona_name`, `family`, `covers` | |
| `agent.cleanup` | `{token, after_merge?}` | rows add `command` (exact `git worktree remove …` line) | the command shown is the one `_remove_if_safe` runs |
| `interaction.list` **new** | `{token, session?}` | `{items, counts, grants}` | projection, `research.md` R3 |
| `interaction.answer` **new** | `{token, id, verdict, where, …}` | `{item}` | dispatches by id prefix to `ask.answer`, `decision.approve\|deny\|end`, `work.dismiss`, `result.apply\|dismiss\|keep`; records `handled.by` = the login's user |
| `work.start` | today + `covers`, `repos`, `from`, `background` | `{work}` | accepts item actions; refuses an item whose kind isn't the action's `object` (FR-058), naming the item |
| `work.background` **new** | `{token, id, on}` | `{work}` | |
| `work.list` | `{token}` | records add `v`, `covers`, `from`, `plan`, `background`, `result`, `stage` | |
| `result.list` **new** | `{token, type?, kept?, session?, after?}` | `{results}` | |
| `result.apply` **new** | `{token, id, indexes?}` | `{result}` | checks the producing action's tool list covers the write (R8); goes out as that persona's App or the person |
| `result.keep` / `result.dismiss` **new** | `{token, id, …}` | `{result}` | |
| `notes.totals` **new** | `{token}` | `{by_label, by_topic, source}` | `notes stats --json` when the tool has it, else from the last search |
| `notes.apply` **new** | `{token, result, indexes}` | `{ops}` | closed op list → `notes add`/`notes set …`; words after `--`; same env and `-I` as `find` (`hubd/notes.py:107-131`) |
| `usage.status` **new** | `{token}` | usage reading (data-model) | reads `status.json` files |
| `ping` | — | adds `socket` (the address the app shows) | |

Unchanged and reused: `ask.list`/`ask.answer`, `decision.*`, `work.plan|approve|dismiss|cancel|claim|filed|hand|discard|bring_back`,
`agent.press|interrupt|state|resume|resume_past|past_search|past_transcript|cleanup_remove|steward|buttons|draft|manifest`,
`device.status`, `decision.holding`, `notes.status|find`, `shell.new|kill|attach`.

## Token ops (the tool server, a session's own token)

| Op | Tool | Request | Reply | Notes |
|---|---|---|---|---|
| `result.submit` **new** | `submit_result` | `{agent_token, type, payload}` | `{ok, id}` or `{refused, error}` | refused unless the token's action has `result == type`; one pending result per session (a new one replaces it while pending); payload closed shape (data-model § Result) |
| `work.submit` | `submit_drafts` | unchanged | | stays for `drafts` |

`STARTED_OPS`, `WORK_TOOL_OPS`, `DECISION_TOOL_OPS`, `REPO_OPS` (`server.py:60-103`) are unchanged.
`result.submit` joins a new `RESULT_TOOL_OPS` map checked like `WORK_TOOL_OPS` (`server.py:714-722`).

## Merge (unchanged, cited for FR-107a)

`op: "gh"` with `pr merge` goes through `Hubd.merge` (`server.py:535-562`): a login merges the head
the page showed; a token merges only under a merge decision for that head
(`_merge_decision`, `server.py:564-580`); `--match-head-commit` is required by the policy
(`ghpolicy.py:203-204`). Full sessions' own `gh` in their shell is a guard, not a limit
(`SECURITY.md` "Guards, not limits").
