# Data model: Needs you (spec 003)

Entities this spec owns, their fields, where each is stored, and how it changes state. "Today"
cites the code on `001-hub-app` at `c81fe71`; "adds" is what this spec changes. Decisions behind
each are in `research.md` (R-numbers; another spec's as `NNN Rn`).

| Entity | Lives in | Survives a hubd restart | Owner module |
|---|---|---|---|
| Interaction | projection over the four stores below | as its source | `hubd/server.py` `interaction.list` |
| Ask | memory | no (by design, `asks.py:1-9`) | `hubd/asks.py` |
| Decision / Go / grant | `state/decisions/d-*.json` | yes | `hubd/decisions.py` |

---

## Interaction (projection, R1)

One shape for every card. Never stored as such; `interaction.list` builds it each call.

| Field | Type | Notes |
|---|---|---|
| `id` | string | source-prefixed: `a:<ask id>`, `d-<hex>`, `w:<work id>`, `r:<result id>` |
| `kind` | `permission` \| `question` \| `decision` \| `suggestion` \| `result` | FR-001 |
| `status` | `pending` \| `allowed` \| `always` \| `denied` \| `answered` \| `started` \| `dismissed` \| `terminal` \| `timeout` \| `ended` | FR-002 |
| `blocking` | bool | true only for pending `permission`/`question` (FR-012) |
| `session` | name \| null | null for a Go you recorded yourself |
| `persona` | `{id, name, initials, family}` | from the session |
| `items` | `[Item ref]` | covered items of the session, or the decision's / suggestion's target |
| `made`, `waited` | seconds | `waited` drives "longest wait" (007 FR-001) |
| `handled` | `{by, where, at}` \| null | FR-011; `by` is the login user or `terminal` |
| `detail` | object | per kind, below |

`detail` per kind:

- **permission** (from `Ask.view`, `asks.py:106-112`): `tool`, `input` (or `too_long`), `always`
  (words of what Always covers, or null), `terminal`, `left`.
- **question**: `questions` (from the tool input), offered answers; answer with
  `{question: answer}` (`asks.py:241-251`).
- **decision** (from `decisions.describe`, `decisions.py:144`): `decision_kind` `go` \| `merge`,
  `says`, `scope` (Go: `actions`, `device`, `session`; merge: `repo`, `number`, `head`), `ends`
  (`runs` or `until`), `left` (runs or hours left, for Active grants), `asked_by`, `why`
  (the session's own words, shown as not yours). Eye test: `eye_test: true`, never "always"
  (FR-007). Merge: applies to `head` only; `head_moved` ends it (`decisions.py:480`) (FR-008).
- **suggestion** (from a NewWork `offered` record): `action` (with `verb`, persona), `why`, `items`,
  `notes` marked as the suggester's.
- **result** (from Results, or NewWork `done` drafts): `type`, `summary`, `payload` ([005 data model](../005-launch/data-model.md) § Result).

**Status transitions** (source op in brackets):

```text
permission: pending ─allow──► allowed      [ask.answer]
                    ─always─► always
                    ─deny───► denied
                    ─(tool ran / Esc in terminal)─► terminal
                    ─(600 s)─► timeout
                    ─(session stopped)─► ended
question:   pending ─answer─► answered | terminal | ended   (no timeout for a question that waits for good)
decision:   pending ─approve─► allowed ─(runs/hours used, End now, head moved)─► ended
                    ─deny────► denied
                    ─(24 h unanswered)─► timeout
suggestion: pending ─Launch… → Start─► started
                    ─dismiss─► dismissed
result:     pending ─apply (Post/Apply/File/Save)─► answered
                    ─set aside─► dismissed
```

**Feed grouping (FR-014):** Blocking = `blocking`, oldest first; Suggested = pending suggestions;
Results ready = pending results. Pending decisions wait for the maintainer but don't hold a turn
(FR-012), so they head the Suggested group under their own sub-heading "Decisions asked for" and are
outlined, not yellow. The header counts every pending interaction; it is yellow only when one is
blocking (001 FR-002).

**Active grants (FR-020):** decisions with status `allowed`, with `left` and "End now"
(`decision.end`).

## Decision / Go / grant (today, `hubd/decisions.py`)

Unchanged storage and rules. Fields: `id d-<hex>`, `kind go|merge`, `words`, `scope`, `ends`,
`state requested|current|using|ended`, `made`, `approved`, `ended`, `why_ended`, `asked_by`,
`why`, `for_hours`. Rules kept: only a login makes one current (`decisions.py:1-10`); eye test
never "always" and survives "I've got the device"; merge scope names a full 40-hex head and ends on
`head_moved`; `MAX_GO_HOURS = 8`, `MAX_RUNS = 20`. The Go card's form fields are today's
`GoForm` (`app.js:2442`): actions from `GO_ACTIONS`, device, session, ends after N runs or hours.
