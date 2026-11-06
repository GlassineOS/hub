# Contract: tool server and library changes for Building blocks (owned, not versioned)

Rule: a change must be safe for a session already running or resumed
([001 `contracts/tool-server-and-library.md`](../../001-app-frame/contracts/tool-server-and-library.md)).

## Action library (`agents/actions/*.toml`)

Additive fields `verb`, `result`, optional `primary_when` on every file (R2).
The new action files are listed in the specs that use them (006, 008, 009).

Changed file: `pr-fix-checks.toml` (personas `["ci-fixer", "engineer"]`).

## Persona library (`agents/personas/`)

| File | Change | PR |
|---|---|---|
| `families.toml` | **new**: `name`, `initials`, `family` per persona (R1) | PR 1 |
| `ci-fixer.md`, `researcher.md`, `archivist.md` | **new** persona prompts | PR 1 (files), used from 006/PR 2, 008/PR 1 and 009/PR 1 |
