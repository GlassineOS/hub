# Data model: Sessions (spec 004)

Entities this spec owns, their fields, where each is stored, and how it changes state. "Today"
cites the code on `001-hub-app` at `c81fe71`; "adds" is what this spec changes. Decisions behind
each are in `research.md` (R-numbers; another spec's as `NNN Rn`).

| Entity | Lives in | Survives a hubd restart | Owner module |
|---|---|---|---|
| Session | `state/sessions/<name>/session.json` + marker files | yes | `hubd/agents.py` |

---

## Session

Stored as today in `state/sessions/<name>/` (`hubd/agents.py:1032-1036`): `session.json`
`{name, session_id, config, title, object, full, created, started_by}` plus marker files
`waiting`, `idle`, `ended`, `asks-open`, `context`. This feature adds fields to `config` and two
files.

| Field | Where | Today / adds |
|---|---|---|
| `config.covers` | `session.json` | **adds** (R1): `[{repo, number}]`, 1 + up to 5; first = primary. `config.repo`/`config.number` mirror the first |
| `config.also_numbers` | `session.json` | today; read-only for old records, folded into `covers` by `describe()` |
| `prs` | derived | **adds**: `[{repo, number, state}]` from `_pr_of(repo, branch)` (`agents.py:1903`), cached 60 s |
| `view` | `view.json` | **adds**: `{mode: "embedded"\|"background", where: SCREEN, ref?}`; default `background` for sessions without one |
| `origin` | `session.json` | **adds**: `{launch: id, from: {view, ref?}, by: "you"\|"steward"\|<session>}`; `null` for old sessions |
| `permission_mode` | derived | **adds**: the action's `permission_mode` (`agents.py:947`) or `dontAsk`/default in words |
| `persona`, `model`, `effort`, `action`, `full`, `posts_as` | `describe()` | today (`agents.py:1483-1494`) |
| `family`, `persona_name`, `initials` | derived | **adds**, from families.toml |
| state word | marker files | today: `Working`, `Waiting for you`, `Idle`, `Stopped` (`agents.py:1170-1173`) |

```text
start ──► Working ◄──► Idle
            │  ▲
            ▼  │ (answered)
       Waiting for you
            │
            ▼
         Stopped ──resume──► Working
```

The state a SessionChip shows is in
[002 data model](../002-building-blocks/data-model.md) § SessionChip state.

**View transitions (FR-010):** `embedded ⇄ background` by `agent.view`; a session is embedded in at
most one place; leaving that view doesn't change it (it stays embedded there); Stop asks first
(FR-011, today's `Confirm` in `Shells`, `app.js:2246`).
