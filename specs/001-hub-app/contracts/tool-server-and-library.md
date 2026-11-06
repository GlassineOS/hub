# Contract: tool server tools and the action/persona library (owned, not versioned)

Rule (constitution, Contracts): a change must be safe for a session already running or resumed.
A session's tool list is fixed in its scope when it starts (`hubd/agents.py:188-193`, `:496-502`)
and checked again on resume against the action as it is then (`SECURITY.md` "Resuming a session").

## Tool changes (`app/hub/tools.py`)

| Tool | Change | Annotation | Safe for running sessions because | PR |
|---|---|---|---|---|
| `submit_result(type: str, payload: dict)` | **new**. Hands in the session's result; the person applies it | `WRITE` (nothing outside the hub changes until a login applies it) | sessions started before don't list it; their scope refuses it | 7 |
| `submit_drafts(drafts)` | unchanged | `WRITE` | — | — |
| `suggest_session(action, repo, number, why, notes, also_numbers)` | adds optional `covers: list[str]` (`repo#N`, ≤ 5, may cross repositories); `also_numbers` stays accepted and is folded in | `WRITE` | old argument still works | 7 |
| `plan_work(action, repo, why, …)` | accepts actions with `object` `notes`/`knowledge` (repo may be omitted for those) | `WRITE` | additive | 15/16 |
| `list_running_sessions`, `list_sessions` | rows add `covers` (refs only, never titles) | `READ` | additive fields | 3 |
| `review_pr`, `label_issue` | unchanged; **removed from new `pr-review` / `issue-triage` sessions' tool lists** (R9) | `HARD` / `WRITE` | a running session keeps them | 7 |
| `merge_pr` | unchanged (FR-107a already enforced in hubd) | `HARD` | — | — |

Tests (`tests/test_app.py` tool section, `tests/test_hubd.py`): the new tool is listed only for a
token whose action names it; a token from a session started with the old tool list still reaches
`review_pr`; `submit_result` with the wrong `type` or an unknown payload key is refused with words.

## Action library (`agents/actions/*.toml`)

Additive fields `verb`, `result`, optional `primary_when` on every file (R2). New files:

| File | object | persona | access | checkout | result | ceiling (plain words, FR-051) | PR |
|---|---|---|---|---|---|---|---|
| `run-fix.toml` | run | ci-fixer | full | new-branch (from the run's head branch) | pr | "Branch + draft PR. Your rights, on its own branch." | 12 |
| `knowledge-research.toml` | knowledge | researcher | locked | false | report | "Read-only. Hands in a report; nothing is posted." | 15 |
| `notes-compact.toml` | notes | archivist | locked | false | notes | "Read-only. Proposes note operations; you apply them; nothing is deleted." | 16 |
| `notes-sweep.toml` | notes | docs-writer | locked | false | drafts | "Read-only. Hands in draft issues." | 16 |

Changed files: `pr-review.toml` (`result = "comment"`, `hub_tools` swaps `review_pr` for
`submit_result`), `issue-triage.toml` (`result = "labels"`, same swap for `label_issue`),
`pr-fix-checks.toml` (personas `["ci-fixer", "engineer"]`). Each prompt in `agents/prompts/` says
how to hand in. `validate` gains the `covers` field (`_FIELDS`, `agents.py:98`).

## Persona library (`agents/personas/`)

| File | Change | PR |
|---|---|---|
| `families.toml` | **new**: `name`, `initials`, `family` per persona (R1) | 1 |
| `ci-fixer.md`, `researcher.md`, `archivist.md` | **new** persona prompts | 1 (files), used from 12/15/16 |
| `steward-buttons.toml` | `screen` values: `Docs` → `Knowledge` where present; no `Device` | 5 |

## Claude Code (consumed, not pinned)

| Dependency | Used for | Must be tried for real in |
|---|---|---|
| `statusLine` setting and its JSON on stdin | usage meter (R7) | PR 5 |
| user turn via paste at an empty prompt | typed messages (R5) | PR 6 |
| planner `--json-schema` answer with the new `steps` field | plan steps (R6) | PR 7 |
