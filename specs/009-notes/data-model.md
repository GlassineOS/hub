# Data model: Notes (spec 009)

Entities this spec owns, their fields, where each is stored, and how it changes state. "Today"
cites the code on `001-hub-app` at `c81fe71`; "adds" is what this spec changes. Decisions behind
each are in `research.md` (R-numbers; another spec's as `NNN Rn`).

---

## Note op (R1)

| Field | Type | Rule |
|---|---|---|
| `op` | `merge` \| `distil` \| `answer` \| `supersede` \| `status` \| `retract` \| `flag` | |
| `topic` | `[a-z0-9-]{1,40}` | |
| `ids` | `[note id]` | the tool's id format; ≥ 1 |
| `words` | str ≤ 2000 | new text for merge/distil/answer/supersede |
| `why` | str ≤ 500 | |
| `command` | str | built by hubd from the fields, never taken from the payload; shown verbatim |
| `state` | `pending` \| `applied` \| `failed` | per op; `failed` keeps the tool's message |

No op maps to a deletion. `merge`/`distil` = `notes add` + `notes set --replaces` per id.
