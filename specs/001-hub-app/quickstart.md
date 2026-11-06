# Quickstart: run the dev hub and check the UI (spec 001)

How to check each PR of the stack for real, beside `make check`. Commands run from the root of
your checkout or worktree. Never point any of this at the live hub's checkout or its state folder.

## 1. Host tests

```sh
make check PYTHON=.venv/bin/python
# = node --check app/hub/static/app.js && .venv/bin/python -m pytest -q
```

Baseline at `c81fe71`: 1509 passed, 1 skipped, about 2 minutes. Every PR leaves this green and adds
the tests its entry in `tasks.md` lists.

## 2. The dev hub

```sh
.dev/run.sh &            # app on http://127.0.0.1:19094, password: dev
# logs: .dev/hubd.log, .dev/app.log; stop: kill $(cat .dev/hubd.pid); pkill -f 'hub.main' (the app)
```

What it is (`.dev/run.sh`):

- `tests/dev_hubd.py` on `.dev/hubd.sock`, state in `.dev/state`, workspace `.dev/ws`, any password
  but `dev` refused. The tool server is on 19095 (PR 0 makes that port an argument so parallel runs
  don't collide).
- Its own tmux server (`.dev/bin/tmux`), so sessions you start here never mix with the live hub's.
- A **read-only `gh`** (`.dev/bin/gh`): `list`, `view`, `diff`, `checks`, `api` GETs and GraphQL
  queries pass; every write is refused with `dev gh: refused: …`. So every GhActions write
  (merge, close, labels, re-run, dispatch, filing drafts, posting a result) **fails on purpose**
  here. Check the button, its confirmation, its disabled reason and the error shown; the write itself
  is tried for real only by the maintainer on the live hub.
- `DEV_CLAUDE=false` by default: planners fail at once ("the planner didn't answer…") and sessions
  exit as they start. To walk Launch through planning and plan, use a stub that answers any planner
  schema with its first allowed values (keep it outside git, e.g. `.dev/bin/claude-stub`):

  ```python
  #!/usr/bin/env python3
  # dev only: answers a planner's --json-schema with the first allowed value of each field.
  import json, sys, time
  a = sys.argv
  if "-p" not in a:              # an interactive session: stay up so its terminal can be opened
      print("stub session: no model here"); time.sleep(3600); sys.exit(0)
  schema = json.loads(a[a.index("--json-schema") + 1])
  def fill(s):
      if "enum" in s: return s["enum"][0]
      t = s.get("type")
      if t == "object": return {k: fill(v) for k, v in s.get("properties", {}).items()}
      if t == "array": return []
      return "stub" if t == "string" else 0
  print(json.dumps({"structured_output": fill(schema), "total_cost_usd": 0}))
  ```

  ```sh
  chmod +x .dev/bin/claude-stub
  DEV_CLAUDE=$PWD/.dev/bin/claude-stub .dev/run.sh &
  ```

  A real `claude` (`DEV_CLAUDE=claude`) is needed only for the checks marked "real claude" below,
  and it spends usage.

## 3. Browser checks

Open http://127.0.0.1:19094, sign in with `dev`. Check at 1440 px and at 390 px (browser device
toolbar), keyboard only once per PR, and once with "reduce motion" on. Record in the PR what was
checked and what wasn't.

| After PR | Check | Expected |
|---|---|---|
| 2 | A Work row and the Sessions list | ItemPill with kind icon, ref, title; state by outline/icon, no fill; PersonaBadge initials on the family tint; SessionChip with RUNNING/WAITING/DONE in words |
| 2 | RepoPicker on Work | type to filter, arrows, Enter, Esc; more than 3 picked shows "N repos" |
| 4 | Header "Needs you" from Overview, Work, Knowledge | modal opens over the view; Esc closes and focus returns to the button (FR-153, FR-169) |
| 4 | Start a session with the stub, have it wait (or use `tests/test_asks.py`-style fixtures through a dev ask) | permission card with Allow / Always / Deny; after answering, "1 handled in this view" shows it and the count drops |
| 4 | Filter "Active grants" | a Go recorded from the Go card lists runs or hours left and "End now" |
| 5 | Header | nav Overview, Roadmap, Work, Knowledge, Notes, Sessions; current view marked; "＋ New work"; user and hubd address; stop hubd (`kill $(cat .dev/hubd.pid)`) → header says hubd can't be reached |
| 5 | Overview device card | "free" or the lock line in words with an age; no Device page in the nav; `#/device` lands on Overview |
| 5 | Usage meter | words and a bar; "usage not known" with the stub; **real claude** to see used % |
| 6 | Steward panel and a session: type a message, press Send | the words appear as your turn in the terminal; mid-turn they show "queued"; control characters refused with words. **Real claude** for the transcript showing them as yours |
| 7 | (backend only) | `make check`; `.dev/state/newwork/*.json` records carry `v: 2`, `covers`, `from` |
| 8 | Sessions › a session | header tinted by family; covered items as pills; "Also on these items" when more than one; terminal on night paper, scrolled to the end; scroll up while output arrives: position kept; inline card answers like Needs you; Session spec disclosure; Stop asks first |
| 9 | "＋ New work", a Work row's blue button, a suggestion's "Launch…" | five stages named; brief shows result type and ceiling in words; planner model choice; plan shows steps and touches (stub: one empty plan); Start; "Send to background" → toast with a link |
| 10 | Sessions › Running, History & cleanup | groups; badges-only narrowing; legend; History filters and transcript search; cleanup rows show the exact command; "Select safe" picks only safe rows |
| 11 | A PR, an issue, a run (any public repository) | breadcrumb; black split button "On GitHub, as <the host user>"; disabled Merge names why; Files changed with per-file diff and "Large file — load the diff"; run shows the failed step with error lines marked; Sessions on the item as persona tabs |
| 12 | Work | kind tabs with counts; groups per FR-101–103; one blue action per row; Queue view; New issue… and Run workflow… forms (writes refused by the dev gh) |
| 13 | Overview | Needs-you card; four stats; layers sorted by attention, 5 then "Show N more"; filter, attention switch, collapse/expand; Unplaced line |
| 14 | Roadmap | four columns; per-repository progress bars; "Plan issues…" opens Launch with road |
| 15 | Knowledge | meaning/exact; Docs and Work items, Code "planned"; pins; no-hits → "Research this…" flyout; index states |
| 16 | Notes | search on a button press, not in the address bar; trust labels; 20 → more → 100 → limit box with a copyable command; "Keep notes useful" flyout. `.dev/ws` has no notes tool: the "notes tool missing" state shows |
| 17 | Steward | resize 320–760 px, width kept after reload; open by default on Overview/Roadmap/Work/Work item, collapsed on Sessions/Knowledge/Notes; SEES chips; waiting strip opens Needs you filtered to the Steward |
| 18 | 390 px, every view | header "New" and "Menu" only; nothing scrolls sideways (diffs and terminals scroll in their box); Steward is a floating button opening a full sheet; Launch, Needs you and flyouts are sheets; targets ≥ 44 px |
| 19 | Keyboard-only pass of scenarios 1–4 | every control reachable, focus visible, modals trap focus |

## 4. What only the maintainer can try

On the live hub, after a PR merges and is deployed there: a GhActions write as themselves (one
merge, one label, one re-run), posting a comment result, applying a labels result, a typed message
to the real Steward, a research session ending in a report, and the usage meter with real numbers.
Each PR names which of these it needs.
