# Contract: tool server and library changes for Knowledge (owned, not versioned)

Rule: a change must be safe for a session already running or resumed
([001 `contracts/tool-server-and-library.md`](../../001-app-frame/contracts/tool-server-and-library.md)).

## Tool changes (`app/hub/tools.py`)

| Tool | Change | Annotation | Safe for running sessions because | PR |
|---|---|---|---|---|
| `plan_work(action, repo, why, …)` | accepts actions with `object` `notes`/`knowledge` (repo may be omitted for those) | `WRITE` | additive | PR 1, 009/PR 1 |

## Action library (`agents/actions/*.toml`)

| File | object | persona | access | checkout | result | ceiling (plain words, 005 FR-004) | PR |
|---|---|---|---|---|---|---|---|
| `knowledge-research.toml` | knowledge | researcher | locked | false | report | "Read-only. Hands in a report; nothing is posted." | PR 1 |
