# Data model: Building blocks (spec 002)

Entities this spec owns, their fields, where each is stored, and how it changes state. "Today"
cites the code on `001-hub-app` at `c81fe71`; "adds" is what this spec changes. Decisions behind
each are in `research.md` (R-numbers; another spec's as `NNN Rn`).

| Entity | Lives in | Survives a hubd restart | Owner module |
|---|---|---|---|
| Item ref | nowhere (a value) | n/a | `app.js` helpers, `hubd` regexes |
| Persona family | `agents/personas/families.toml` | yes (file) | `hubd/agents.py` `Library` |

---

## Item ref

A value, never stored on its own.

| Field | Type | Rule |
|---|---|---|
| `kind` | `issue` \| `pr` \| `run` \| `roadmap` | |
| `repo` | string | `_REPO_RE` (`hubd/agents.py:93`), organization repositories only |
| `number` | int > 0 | for runs, the run id |
| `workflow` | string | runs only, the workflow name for display |

Written `repo#N` (issues, PRs, roadmap items: the roadmap item is its `hub#N` issue) and
`workflow #N` (runs) (FR-001). Parsed in hubd by the existing selection pattern
(`_SELECTION_RE`, `agents.py:132`) widened to `run:` refs. In the app an **ItemPill** takes
`{kind, repo, number, title?, state}`; `state` is one of `open`, `draft`, `merged`, `closed`,
`failing`, `running` and maps to an outline and icon (FR-003, 001 FR-012), never a fill.

## Persona family (R1)

`agents/personas/families.toml`, one table per persona file stem:

| Field | Type | Rule |
|---|---|---|
| `name` | string ≤ 40 | display name ("Code reviewer") |
| `initials` | 1–2 letters | |
| `family` | `build` \| `review` \| `investigate` \| `write` \| `organise` | exactly one (FR-011) |

`Library` refuses to load if a persona file has no entry, an entry has no file, or a family is
unknown. Tints are CSS tokens, not data (FR-012). `steward` → the reserved "S" badge (FR-013).
Plain shells have no persona (FR-014). New personas: `ci-fixer` (build), `researcher`
(investigate), `archivist` (organise).

## Action (owned library, additive fields, R2)

Existing TOML fields stay. Adds:

| Field | Type | Rule |
|---|---|---|
| `verb` | string | the spec's short name; unique across actions that have one |
| `result` | `comment` \| `pr` \| `labels` \| `findings` \| `drafts` \| `report` \| `notes` \| `none` | |
| `object` | adds `notes`, `knowledge` | to today's `issue`, `pr`, `run`, `repo`, `project` |
| `primary_when` | optional list | row rule inputs for 006 FR-007 (`failing`, `changes-requested`, `untriaged`) |

`agent.actions` returns `verb`, `result`, `family` of the first persona, and the ceiling in plain
words (005 FR-004).

## SessionChip state

The Session itself is in [004 data model](../004-sessions/data-model.md).

**State shown on a SessionChip (FR-016)** maps from the state word: `Working` → RUNNING,
`Waiting for you` → WAITING (yellow, with the count of pending interactions for that session),
`Idle` → RUNNING (at its prompt; the chip says "idle" in its accessible name), `Stopped` → DONE;
ATTACHED when tmux reports `attached > 0` and the session isn't waiting.
