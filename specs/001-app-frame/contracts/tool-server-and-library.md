# Contract: tool server and library, shared rule (owned, not versioned)

Rule (constitution, Contracts): a change must be safe for a session already running or resumed.
A session's tool list is fixed in its scope when it starts (`hubd/agents.py:188-193`, `:496-502`)
and checked again on resume against the action as it is then (`SECURITY.md` "Resuming a session").
Each spec lists its tool, action and persona changes in its own `contracts/tool-server-and-library.md`.

## Persona library (`agents/personas/`)

| File | Change | PR |
|---|---|---|
| `steward-buttons.toml` | `screen` values: `Docs` → `Knowledge` where present; no `Device` | PR 2 |

## Claude Code (consumed, not pinned)

| Dependency | Used for | Must be tried for real in |
|---|---|---|
| `statusLine` setting and its JSON on stdin | usage meter (R1) | PR 2 |
