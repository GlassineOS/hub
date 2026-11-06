# Contract: tool server and library changes for Work (owned, not versioned)

Rule: a change must be safe for a session already running or resumed
([001 `contracts/tool-server-and-library.md`](../../001-app-frame/contracts/tool-server-and-library.md)).

## Tool changes (`app/hub/tools.py`)

| Tool | Change | Annotation | Safe for running sessions because | PR |
|---|---|---|---|---|
| `merge_pr` | unchanged (FR-010 already enforced in hubd) | `HARD` | — | — |

## Action library (`agents/actions/*.toml`)

| File | object | persona | access | checkout | result | ceiling (plain words, 005 FR-004) | PR |
|---|---|---|---|---|---|---|---|
| `run-fix.toml` | run | ci-fixer | full | new-branch (from the run's head branch) | pr | "Branch + draft PR. Your rights, on its own branch." | PR 2 |
