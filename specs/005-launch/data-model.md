# Data model: Launch (spec 005)

Entities this spec owns, their fields, where each is stored, and how it changes state. "Today"
cites the code on `001-hub-app` at `c81fe71`; "adds" is what this spec changes. Decisions behind
each are in `research.md` (R-numbers; another spec's as `NNN Rn`).

| Entity | Lives in | Survives a hubd restart | Owner module |
|---|---|---|---|
| Launch record | `state/newwork/<id>.json` | yes | `hubd/newwork.py` |
| Result (incl. Knowledge report, Note ops) | `state/results/<id>.json` (new) | yes | `hubd/results.py` (new) |

---

## Launch record (extends NewWork, R1)

`state/newwork/<id>.json`. Existing fields (`newwork.py:117-123`, `server.py:690-708`): `id`,
`state`, `session`, `session_id`, `drafts`, `error`, `made`, `by`, `driver`, `action`, `repo`,
`notes`, `describe`, `paths`, `why`, `context`, `pins`, `model`, `planner_model`, `spec`,
`planner_pick`, `planner_cost_usd`, `number`, `also_numbers`, `title`.

Adds (`v: 2`):

| Field | Type | Rule |
|---|---|---|
| `v` | 2 | absent = old record, read as today |
| `covers` | `[Item ref]` | 0–6; kind must match the action's object (FR-011) |
| `repos` | `[repo]` | RepoPicker selection for repo/notes/knowledge actions; ≤ 6 |
| `from` | `{view, ref?}` | where Launch was opened (FR-001, FR-010); `view` from the closed SCREENS list |
| `plan` | `{steps: [{what, touches[]}]}` | planner output (FR-006) |
| `background` | bool | FR-008 |
| `result` | result id \| null | when the session hands one in |
| `stage` | derived | `brief` (page only) → `planning` → `plan` (= `planned`) → `run` (`starting`, `running`, `started`) → `result` (`done`, `filed`) |

```text
(page: brief) ─Plan──► planning ─ok──► planned ─Start──► starting ─► running ─hand in─► done ─file/apply─► filed
                          │              │  ▲                │           │                │
                          │              └──┘ edit, plan again│           │                └─set aside─► dismissed
                          └─fail─► failed ◄──────────────────┴───────────┘ (stopped without a result)
suggestion: offered ─Launch…─► (page: brief prefilled) ─Plan──► planning …
```

Item sessions that end in a PR (no hand-in) go `starting → started`, as today
(`server.py:787-790`); their result card appears when `prs[]` finds the PR.

## Result (new store, R2)

`state/results/<id>.json`, 0700, at most 200 kept (oldest settled pruned first).

| Field | Type | Rule |
|---|---|---|
| `id` | `r-<12 hex>` | |
| `type` | as Action `result` | must equal the producing action's `result` |
| `session`, `session_id`, `launch` | | who handed it in |
| `items` | `[Item ref]` | the session's covers |
| `state` | `pending` \| `applying` \| `applied` \| `dismissed` | `applying` on restart → `pending` with a note to check GitHub first (as `newwork.INTERRUPTED`) |
| `kept` | bool | reports saved to Knowledge |
| `payload` | per type, below | every string capped; links printed in full when shown |
| `made`, `applied_at`, `applied_by`, `note` | | |

Payloads (closed shapes, unknown keys refused):

- **comment** (FR-017): `{summary: str ≤ 8000, event: "comment"|"request-changes"|"approve", notes: [{path, line, side, body ≤ 2000}] ≤ 50}`.
- **pr** (FR-016): `{repo, number}`; the card reads title and "Closes …" lines from GitHub.
- **labels** (FR-018): `{issues: [{ref, add: [label] ≤ 6, remove: [label] ≤ 6, part_of: ref|null, why}] ≤ 20}`.
- **findings** (FR-019): `{cause: str, fix: str, files: [path] ≤ 20, run: ref}`.
- **drafts** (FR-015): stays in the NewWork record (`clean_drafts`, `newwork.py:38`), projected.
- **report** (FR-020): `{question, answer, unsettled: [str] ≤ 20, sources: [{link, why}] ≤ 30, followups: [str] ≤ 10}`.
- **notes** (FR-021): `{ops: [Note op] ≤ 40}` (Note op: [009 data model](../009-notes/data-model.md)).
