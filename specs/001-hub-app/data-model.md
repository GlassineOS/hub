# Data model: Hub app (spec 001)

Entities the views share, their fields, where each is stored, and how it changes state. "Today"
cites the code on `001-hub-app` at `c81fe71`; "adds" is what this feature changes. Decisions behind
each are in `research.md` (R-numbers).

Stores at a glance:

| Entity | Lives in | Survives a hubd restart | Owner module |
|---|---|---|---|
| Item ref | nowhere (a value) | n/a | `app.js` helpers, `hubd` regexes |
| Persona family | `agents/personas/families.toml` | yes (file) | `hubd/agents.py` `Library` |
| Session | `state/sessions/<name>/session.json` + marker files | yes | `hubd/agents.py` |
| Interaction | projection over the four stores below | as its source | `hubd/server.py` `interaction.list` |
| Ask | memory | no (by design, `asks.py:1-9`) | `hubd/asks.py` |
| Decision / Go / grant | `state/decisions/d-*.json` | yes | `hubd/decisions.py` |
| Launch record | `state/newwork/<id>.json` | yes | `hubd/newwork.py` |
| Result (incl. Knowledge report, Note ops) | `state/results/<id>.json` (new) | yes | `hubd/results.py` (new) |
| Usage reading | `state/sessions/<name>/status.json` (new) | yes | `hubd/agents.py` |

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
`failing`, `running` and maps to an outline and icon (FR-003, FR-165), never a fill.

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
| `primary_when` | optional list | row rule inputs for FR-105 (`failing`, `changes-requested`, `untriaged`) |

`agent.actions` returns `verb`, `result`, `family` of the first persona, and the ceiling in plain
words (FR-051).

## Session

Stored as today in `state/sessions/<name>/` (`hubd/agents.py:1032-1036`): `session.json`
`{name, session_id, config, title, object, full, created, started_by}` plus marker files
`waiting`, `idle`, `ended`, `asks-open`, `context`. This feature adds fields to `config` and two
files.

| Field | Where | Today / adds |
|---|---|---|
| `config.covers` | `session.json` | **adds** (R4): `[{repo, number}]`, 1 + up to 5; first = primary. `config.repo`/`config.number` mirror the first |
| `config.also_numbers` | `session.json` | today; read-only for old records, folded into `covers` by `describe()` |
| `prs` | derived | **adds**: `[{repo, number, state}]` from `_pr_of(repo, branch)` (`agents.py:1903`), cached 60 s |
| `view` | `view.json` | **adds**: `{mode: "embedded"\|"background", where: SCREEN, ref?}`; default `background` for sessions without one |
| `origin` | `session.json` | **adds**: `{launch: id, from: {view, ref?}, by: "you"\|"steward"\|<session>}`; `null` for old sessions |
| `permission_mode` | derived | **adds**: the action's `permission_mode` (`agents.py:947`) or `dontAsk`/default in words |
| `persona`, `model`, `effort`, `action`, `full`, `posts_as` | `describe()` | today (`agents.py:1483-1494`) |
| `family`, `persona_name`, `initials` | derived | **adds**, from families.toml |
| state word | marker files | today: `Working`, `Waiting for you`, `Idle`, `Stopped` (`agents.py:1170-1173`) |

**State shown on a SessionChip (FR-016)** maps from the state word: `Working` → RUNNING,
`Waiting for you` → WAITING (yellow, with the count of pending interactions for that session),
`Idle` → RUNNING (at its prompt; the chip says "idle" in its accessible name), `Stopped` → DONE;
ATTACHED when tmux reports `attached > 0` and the session isn't waiting.

```text
start ──► Working ◄──► Idle
            │  ▲
            ▼  │ (answered)
       Waiting for you
            │
            ▼
         Stopped ──resume──► Working
```

**View transitions (FR-029):** `embedded ⇄ background` by `agent.view`; a session is embedded in at
most one place; leaving that view doesn't change it (it stays embedded there); Stop asks first
(FR-030, today's `Confirm` in `Shells`, `app.js:2246`).

## Interaction (projection, R3)

One shape for every card. Never stored as such; `interaction.list` builds it each call.

| Field | Type | Notes |
|---|---|---|
| `id` | string | source-prefixed: `a:<ask id>`, `d-<hex>`, `w:<work id>`, `r:<result id>` |
| `kind` | `permission` \| `question` \| `decision` \| `suggestion` \| `result` | FR-031 |
| `status` | `pending` \| `allowed` \| `always` \| `denied` \| `answered` \| `started` \| `dismissed` \| `terminal` \| `timeout` \| `ended` | FR-032 |
| `blocking` | bool | true only for pending `permission`/`question` (FR-042) |
| `session` | name \| null | null for a Go you recorded yourself |
| `persona` | `{id, name, initials, family}` | from the session |
| `items` | `[Item ref]` | covered items of the session, or the decision's / suggestion's target |
| `made`, `waited` | seconds | `waited` drives "longest wait" (FR-087) |
| `handled` | `{by, where, at}` \| null | FR-041; `by` is the login user or `terminal` |
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
  (FR-037). Merge: applies to `head` only; `head_moved` ends it (`decisions.py:480`) (FR-038).
- **suggestion** (from a NewWork `offered` record): `action` (with `verb`, persona), `why`, `items`,
  `notes` marked as the suggester's.
- **result** (from Results, or NewWork `done` drafts): `type`, `summary`, `payload` (§ Result).

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

**Feed grouping (FR-044):** Blocking = `blocking`, oldest first; Suggested = pending suggestions;
Results ready = pending results. Pending decisions wait for the maintainer but don't hold a turn
(FR-042), so they head the Suggested group under their own sub-heading "Decisions asked for" and are
outlined, not yellow. The header counts every pending interaction; it is yellow only when one is
blocking (FR-083).

**Active grants (FR-151):** decisions with status `allowed`, with `left` and "End now"
(`decision.end`).

## Launch record (extends NewWork, R6)

`state/newwork/<id>.json`. Existing fields (`newwork.py:117-123`, `server.py:690-708`): `id`,
`state`, `session`, `session_id`, `drafts`, `error`, `made`, `by`, `driver`, `action`, `repo`,
`notes`, `describe`, `paths`, `why`, `context`, `pins`, `model`, `planner_model`, `spec`,
`planner_pick`, `planner_cost_usd`, `number`, `also_numbers`, `title`.

Adds (`v: 2`):

| Field | Type | Rule |
|---|---|---|
| `v` | 2 | absent = old record, read as today |
| `covers` | `[Item ref]` | 0–6; kind must match the action's object (FR-058) |
| `repos` | `[repo]` | RepoPicker selection for repo/notes/knowledge actions; ≤ 6 |
| `from` | `{view, ref?}` | where Launch was opened (FR-048, FR-057); `view` from the closed SCREENS list |
| `plan` | `{steps: [{what, touches[]}]}` | planner output (FR-053) |
| `background` | bool | FR-055 |
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

## Result (new store, R8)

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

- **comment** (FR-064): `{summary: str ≤ 8000, event: "comment"|"request-changes"|"approve", notes: [{path, line, side, body ≤ 2000}] ≤ 50}`.
- **pr** (FR-063): `{repo, number}`; the card reads title and "Closes …" lines from GitHub.
- **labels** (FR-065): `{issues: [{ref, add: [label] ≤ 6, remove: [label] ≤ 6, part_of: ref|null, why}] ≤ 20}`.
- **findings** (FR-066): `{cause: str, fix: str, files: [path] ≤ 20, run: ref}`.
- **drafts** (FR-062): stays in the NewWork record (`clean_drafts`, `newwork.py:38`), projected.
- **report** (FR-067): `{question, answer, unsettled: [str] ≤ 20, sources: [{link, why}] ≤ 30, followups: [str] ≤ 10}`.
- **notes** (FR-068): `{ops: [Note op] ≤ 40}`.

### Note op (R12)

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

## Decision / Go / grant (today, `hubd/decisions.py`)

Unchanged storage and rules. Fields: `id d-<hex>`, `kind go|merge`, `words`, `scope`, `ends`,
`state requested|current|using|ended`, `made`, `approved`, `ended`, `why_ended`, `asked_by`,
`why`, `for_hours`. Rules kept: only a login makes one current (`decisions.py:1-10`); eye test
never "always" and survives "I've got the device"; merge scope names a full 40-hex head and ends on
`head_moved`; `MAX_GO_HOURS = 8`, `MAX_RUNS = 20`. The Go card's form fields are today's
`GoForm` (`app.js:2442`): actions from `GO_ACTIONS`, device, session, ends after N runs or hours.

## Knowledge report

A Result of type `report` with `kept: true`. Listed by `result.list(type="report", kept=true)`;
"Follow up" opens Launch with `pins: [{kind: "text", label: "<report id>: <question>"}]`.

## Device lock view (R11)

Read only: `device.status` lines (words with an age, `hubd/devices.py:329`) and
`decision.holding_view` (`decisions.py:354`). No new fields.

## Usage reading (R7)

`state/sessions/<name>/status.json`: the last status-line JSON Claude Code sent, written by the
status-line command, capped at 16 KiB. `usage.status` returns
`{known: bool, used_pct?: number, resets_at?: seconds, cost_today_usd?: number, allowance_usd?: number, low: bool, words: str}`.
