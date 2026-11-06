# Contract: tool server and library changes for Launch (owned, not versioned)

Rule: a change must be safe for a session already running or resumed
([001 `contracts/tool-server-and-library.md`](../../001-app-frame/contracts/tool-server-and-library.md)).

## Tool changes (`app/hub/tools.py`)

| Tool | Change | Annotation | Safe for running sessions because | PR |
|---|---|---|---|---|
| `submit_result(type: str, payload: dict)` | **new**. Hands in the session's result; the person applies it | `WRITE` (nothing outside the hub changes until a login applies it) | sessions started before don't list it; their scope refuses it | PR 1 |
| `submit_drafts(drafts)` | unchanged | `WRITE` | — | — |
| `suggest_session(action, repo, number, why, notes, also_numbers)` | adds optional `covers: list[str]` (`repo#N`, ≤ 5, may cross repositories); `also_numbers` stays accepted and is folded in | `WRITE` | old argument still works | PR 1 |
| `review_pr`, `label_issue` | unchanged; **removed from new `pr-review` / `issue-triage` sessions' tool lists** (R3) | `HARD` / `WRITE` | a running session keeps them | PR 1 |

Tests (`tests/test_app.py` tool section, `tests/test_hubd.py`): the new tool is listed only for a
token whose action names it; a token from a session started with the old tool list still reaches
`review_pr`; `submit_result` with the wrong `type` or an unknown payload key is refused with words.

## Action library (`agents/actions/*.toml`)

Changed files: `pr-review.toml` (`result = "comment"`, `hub_tools` swaps `review_pr` for
`submit_result`), `issue-triage.toml` (`result = "labels"`, same swap for `label_issue`). Each prompt in
`agents/prompts/` says how to hand in.

## Claude Code (consumed, not pinned)

| Dependency | Used for | Must be tried for real in |
|---|---|---|
| planner `--json-schema` answer with the new `steps` field | plan steps (R1) | PR 1 |
