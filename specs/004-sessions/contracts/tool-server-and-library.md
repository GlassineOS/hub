# Contract: tool server and library changes for Sessions (owned, not versioned)

Rule: a change must be safe for a session already running or resumed
([001 `contracts/tool-server-and-library.md`](../../001-app-frame/contracts/tool-server-and-library.md)).

## Tool changes (`app/hub/tools.py`)

| Tool | Change | Annotation | Safe for running sessions because | PR |
|---|---|---|---|---|
| `list_running_sessions`, `list_sessions` | rows add `covers` (refs only, never titles) | `READ` | additive fields | PR 1 |

## Action library

`validate` gains the `covers` field (`_FIELDS`, `agents.py:98`).

## Claude Code (consumed, not pinned)

| Dependency | Used for | Must be tried for real in |
|---|---|---|
| user turn via paste at an empty prompt | typed messages (R2) | PR 2 |
