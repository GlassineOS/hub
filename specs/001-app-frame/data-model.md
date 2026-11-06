# Data model: App frame (spec 001)

Entities this spec owns, their fields, where each is stored, and how it changes state. "Today"
cites the code on `001-hub-app` at `c81fe71`; "adds" is what this spec changes. Decisions behind
each are in `research.md` (R-numbers; another spec's as `NNN Rn`).

| Entity | Lives in | Survives a hubd restart | Owner module |
|---|---|---|---|
| Usage reading | `state/sessions/<name>/status.json` (new) | yes | `hubd/agents.py` |

---

## Usage reading (R1)

`state/sessions/<name>/status.json`: the last status-line JSON Claude Code sent, written by the
status-line command, capped at 16 KiB. `usage.status` returns
`{known: bool, used_pct?: number, resets_at?: seconds, cost_today_usd?: number, allowance_usd?: number, low: bool, words: str}`.
