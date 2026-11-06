# Specs

The hub web app is specified in ten specs. Each is self-contained (its own spec, plan, research,
data model, contracts and tasks, as it needs them) and cites the others by number. All ten are
worked on branch `001-hub-app`, which is why every spec's Feature Branch line names it.

## The specs

| Spec | What it is for | FRs | SCs | Scenarios | Tasks |
|---|---|---|---|---|---|
| [001 App frame](001-app-frame/spec.md) | Header and navigation (usage meter, hubd status), phone ≤ 760 px, the rules across all views (colour and outline meanings, accessibility, live updates, scale), security and trust. | 25 | 4 | 1 | 23 |
| [002 Building blocks](002-building-blocks/spec.md) | ItemPill and item references, ItemPicker, RepoPicker, PersonaBadge with persona families and action metadata (verb, result), SessionChip. | 19 | 1 | 1 | 15 |
| [003 Needs you](003-needs-you/spec.md) | Interactions of every kind (permissions, questions, decisions incl. Go and merge decisions, suggestions, results), the Feed, the Needs-you modal, Active grants. | 22 | 2 | 2 | 12 |
| [004 Sessions](004-sessions/spec.md) | SessionView (a full chat, typed messages), session covers, PRs, view and origin, Sessions › Running, History & cleanup. | 23 | 1 | 2 | 31 |
| [005 Launch](005-launch/spec.md) | Launch stages and records, the action table, result types, the results store and applying results. | 21 | 1 | 1 | 28 |
| [006 Work](006-work/spec.md) | Work list (groups, row action, Queue view, the agent merge rule), Work item (details, diff, run log, sessions on an item), GhActions (incl. New issue, Run workflow). | 38 | 1 | 3 | 22 |
| [007 Overview and Roadmap](007-overview-roadmap/spec.md) | Overview (repositories by attention, device lock state) and Roadmap (Part-of progress). | 12 | 0 | 2 | 10 |
| [008 Knowledge](008-knowledge/spec.md) | Knowledge search, research, reports, indexes. | 9 | 0 | 1 | 7 |
| [009 Notes](009-notes/spec.md) | Notes search, states, upkeep. | 5 | 0 | 1 | 8 |
| [010 Steward](010-steward/spec.md) | The Steward panel. | 6 | 0 | 1 | 7 |

## Dependency order

A spec depends on the specs whose blocks and rules it uses. Read and build them in this order:

| Spec | Depends on |
|---|---|
| [001 App frame](001-app-frame/spec.md) | — |
| [002 Building blocks](002-building-blocks/spec.md) | 001 |
| [003 Needs you](003-needs-you/spec.md) | 001, 002 |
| [004 Sessions](004-sessions/spec.md) | 001, 002, 003 |
| [005 Launch](005-launch/spec.md) | 001, 002, 003, 004 |
| [006 Work](006-work/spec.md) | 001, 002, 003, 004, 005 |
| [007 Overview and Roadmap](007-overview-roadmap/spec.md) | 001, 002, 003, 005 |
| [008 Knowledge](008-knowledge/spec.md) | 001, 002, 003, 005 |
| [009 Notes](009-notes/spec.md) | 001, 002, 005 |
| [010 Steward](010-steward/spec.md) | 001, 002, 003, 004, 005 |

## Build order of all PRs

The twenty PRs of the ten specs, in the order they are built. `NNN/PR k` is PR k of spec NNN.

| Step | PR | Title | Size | Depends on | Status |
|---|---|---|---|---|---|
| 1 | [001/PR 1](001-app-frame/tasks.md) | Dev hubd: configurable tool server port | S | — | done (hub #26) |
| 2 | [002/PR 1](002-building-blocks/tasks.md) | Persona families and action metadata | S | 001/PR 1 | done (hub #27) |
| 3 | [002/PR 2](002-building-blocks/tasks.md) | Shared components | M | 002/PR 1 | done (hub #28) |
| 4 | [004/PR 1](004-sessions/tasks.md) | Session covers[], prs[], view, origin | M | 002/PR 1 | to build |
| 5 | [003/PR 1](003-needs-you/tasks.md) | Interactions, Feed and the Needs-you modal | L | 002/PR 2, 004/PR 1 | to build |
| 6 | [001/PR 2](001-app-frame/tasks.md) | Header and navigation | M | 003/PR 1 | to build |
| 7 | [004/PR 2](004-sessions/tasks.md) | Typed messages: sessions are chats | S | 001/PR 2 | to build |
| 8 | [005/PR 1](005-launch/tasks.md) | Launch records, stages and results: backend | L | 004/PR 1, 003/PR 1 | to build |
| 9 | [004/PR 3](004-sessions/tasks.md) | SessionView | L | 002/PR 2, 004/PR 2, 005/PR 1 | to build |
| 10 | [005/PR 2](005-launch/tasks.md) | Launch UI | L | 005/PR 1, 004/PR 3 | to build |
| 11 | [004/PR 4](004-sessions/tasks.md) | Sessions › Running and History & cleanup | M | 004/PR 3 | to build |
| 12 | [006/PR 1](006-work/tasks.md) | Work item | L | 004/PR 3, 005/PR 2 | to build |
| 13 | [006/PR 2](006-work/tasks.md) | Work | M | 006/PR 1 | to build |
| 14 | [007/PR 1](007-overview-roadmap/tasks.md) | Overview | M | 002/PR 2, 001/PR 2 | to build |
| 15 | [007/PR 2](007-overview-roadmap/tasks.md) | Roadmap | M | 005/PR 2 | to build |
| 16 | [008/PR 1](008-knowledge/tasks.md) | Knowledge | L | 005/PR 2 | to build |
| 17 | [009/PR 1](009-notes/tasks.md) | Notes | L | 005/PR 2 | to build |
| 18 | [010/PR 1](010-steward/tasks.md) | Steward panel | M | 004/PR 3, 005/PR 2 | to build |
| 19 | [001/PR 3](001-app-frame/tasks.md) | Phone ≤ 760 px | M | 010/PR 1 | to build |
| 20 | [001/PR 4](001-app-frame/tasks.md) | Cross-cutting checks and leftovers | S | 001/PR 3 | to build |

- The SessionView (004/PR 3) comes before the Launch UI (005/PR 2), because the run stage embeds a
  compact SessionView (005 FR-007); the device lock card lands with the header (001/PR 2), which removes
  the Device page (007 R1).
- 002/PR 2 and 004/PR 1 could be built at the same time (002/PR 2 is front end + one hubd field, 004/PR 1 is
  hubd); they both touch `hubd/agents.py`'s `describe()`. 002/PR 2 is done, so only 004/PR 1 is left.
- 005/PR 1 (backend) can be built while 001/PR 2 and 004/PR 2 are in review: it doesn't touch `app.js`; its UI
  comes in 005/PR 2.
- 007/PR 1, 007/PR 2, 008/PR 1, 009/PR 1 have no logical dependency on each other; they all edit `app.js`, so merge
  one at a time and rebase.
- Across the stack: 005/PR 1 backend in parallel with 001/PR 2 and 004/PR 2; 007/PR 1 in parallel with 005/PR 1, 004/PR 3, 005/PR 2, 004/PR 4, 006/PR 1, 006/PR 2.

Increments:

- **First usable increment (scenarios 003/US1 and 003/US2):** 001/PR 1, 002/PR 1, 002/PR 2, 004/PR 1, 003/PR 1, 001/PR 2. After 001/PR 2 the
  maintainer answers any blocking prompt from any screen through the header (003 SC-001, 003 SC-002),
  with Decisions, Go and grants in the modal and the device lock on Overview.
- **Second increment (scenarios 005/US1, 006/US1 and 006/US2):** 004/PR 2, 005/PR 1, 004/PR 3, 005/PR 2, 004/PR 4, 006/PR 1, 006/PR 2: chat, Launch
  with records and results, SessionView, Work and Work item with GhActions.
- **Then** the P2/P3 views (007/PR 1, 007/PR 2, 008/PR 1, 009/PR 1), the Steward panel (010/PR 1), phone (001/PR 3) and
  the final checks (001/PR 4).
- Each PR's body states the FRs it delivers, what was tried for real, and what wasn't.

## Tasks: format and closing steps (all specs)

Tasks are organised by **pull request**, not by user story, at the maintainer's request. Each
spec's PRs are in dependency order; each PR is independently reviewable, leaves `make check` green
(`make check PYTHON=.venv/bin/python`) and the app usable, with no half-migrated screen on `main`.

**Tests** are required: the constitution's Tests principle and each spec's Acceptance section ask
for host tests with every change. Each PR lists them as tasks; write them with or before the code.

Format: `[ID] [P?] [US#?] Description`

- **[P]**: can run in parallel with other [P] tasks of the same PR (different files, no dependency
  between them). `app/hub/static/app.js` is one file, so its tasks are never [P] with each other.
- **[US#]**: the spec scenario (user story) the task serves; `[NNN/USk]` is scenario k of spec NNN.
- Every PR ends with the same three steps, written once here and not repeated: run
  `make check PYTHON=.venv/bin/python`; do the PR's browser check
  ([001 quickstart](001-app-frame/quickstart.md) §3) and record in the PR body what was checked and
  what wasn't tried for real; run `.glassine/org/scripts/safety-scan.sh --staged` before
  committing, with an `Assisted-by:` trailer.

## IDs

FR, SC, R, T, scenario (US) and PR numbers count from 1 inside each spec. Another spec's ID carries
its number first: `001 FR-011`, `005 R2`, `005/PR 1`, `[003/US1]`.

## Where shared things live

- The dev hub and the browser checks for every PR: [001 quickstart](001-app-frame/quickstart.md).
- The technical context and the constitution check for all specs: [001 plan](001-app-frame/plan.md).
- The rules every view follows (colour, outline, accessibility, live updates, scale, security):
  [001 spec](001-app-frame/spec.md); device scope and risk for all specs: the same spec.
- Web API and hubd socket rules (login gate, shared ops), the running-session rule for tools, and
  agent writes to GitHub: [001 contracts](001-app-frame/contracts/).
- Decisions the maintainer already made: [001 research](001-app-frame/research.md).
- The task format: this file.
- [MAPPING.md](MAPPING.md): the IDs of the single hub-app spec these ten were written from
  (`specs/001-hub-app/`), mapped to their new homes, for code comments and commits that cite them.
