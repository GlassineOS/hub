# Contract: tool server and library changes for Notes (owned, not versioned)

Rule: a change must be safe for a session already running or resumed
([001 `contracts/tool-server-and-library.md`](../../001-app-frame/contracts/tool-server-and-library.md)).

## Action library (`agents/actions/*.toml`)

| File | object | persona | access | checkout | result | ceiling (plain words, 005 FR-004) | PR |
|---|---|---|---|---|---|---|---|
| `notes-compact.toml` | notes | archivist | locked | false | notes | "Read-only. Proposes note operations; you apply them; nothing is deleted." | PR 1 |
| `notes-sweep.toml` | notes | docs-writer | locked | false | drafts | "Read-only. Hands in draft issues." | PR 1 |
