# Feature Specification: Workflows

**Feature Branch**: `spec-workflows`
**Created**: 2026-11-13
**Status**: Draft
**Input**: "Workflows: state machines over personas that drive instructions, tool access and which agents start"
(GlassineOS/hub#52), with the design in GlassineOS/ui `designs/hub` (the machine diagram and outline, the
workflow editor, the state chip, the machine panel, the widening confirm, the definition change, the change
request and the design spike).

## Context

A session's work moves through steps: implement, get it reviewed, fix, get it merged. Each step needs different
instructions, different tools and different helpers. A **workflow** puts all three under one mechanism: a state
machine that a session holds. Its state says what the agent is told, what it may use and which other sessions it
brings in. Its moves are written in plain language, judged by a small model, and checked against facts the hub
already has.

The workflow is the permission model. What a session may do is what its state grants, and nothing else grants
anything. Within that grant an agent works without asking. What lies outside it goes up a chain of owners, and
only what no agent in the chain may decide reaches the maintainer, through the Steward.

Every action of Launch (005) is a workflow; most have one state. It uses the session view and chips (Sessions,
004; Building blocks, 002), Needs you (003) for decisions and confirms, the Steward (010), and design sessions
(011) for design spikes.

## User Scenarios & Testing

### User Story 1 - A session moves through its workflow (Priority: P1)

The maintainer launches "implement" on an issue and the session carries the work from a branch to a merge-ready
pull request, getting new instructions and tools at each step.

**Why this priority**: This is what a workflow is for.

**Independent Test**: Launch implement on the dev hub with a stub agent, push a branch, open a pull request, let
checks pass and a review return, and follow the states.

**Acceptance Scenarios**:

1. **Given** an implement session in state implement, **When** its turn ends and the judge finds the change
   complete but no pull request is open, **Then** the session stays in implement and the log shows the proposal,
   the evidence and the failed fact.
2. **Given** the pull request is open and its checks pass, **When** the next evaluation holds, **Then** the
   session moves to review, the next turn starts with review's instructions, and a reviewer session starts under
   it.
3. **Given** the reviewer returns "changes requested", **When** the review state's exits are tried, **Then** the
   session moves to fix, and after three rounds of fix without a pass it is sent up to its owner instead.
4. **Given** a move whose new state grants more than the old, **When** it would happen, **Then** it waits for the
   maintainer's confirm, which shows what the new state adds, takes away and keeps.

---

### User Story 2 - See where a session stands (Priority: P1)

The maintainer sees each session's state wherever the session shows and opens its machine to see why.

**Why this priority**: A machine nobody can see can't be trusted or corrected.

**Independent Test**: Open Sessions, a work item and the Steward panel with sessions in different states; open a
session's machine panel.

**Acceptance Scenarios**:

1. **Given** a session in review inside work, **When** it shows anywhere, **Then** its chip reads the path of
   states (for example "work › review") and its kind (holds, moving, waits for someone, sent up, over) in words.
2. **Given** the machine panel of a session, **When** the maintainer opens it, **Then** it shows the machine, the
   current state's exits in order with each check, its value and its result, the parent's exits, the sessions
   running under the state, and the history with evidence and counters.
3. **Given** the machine panel, **When** the maintainer moves the session by hand, rolls back a move or pauses
   the machine, **Then** that happens, is logged as theirs, and a widening move by hand still shows the confirm.

---

### User Story 3 - Sessions bring in other sessions (Priority: P1)

A state starts the sessions it manages, gives each a defined context, and uses what they return.

**Why this priority**: Review and QA by separate agents is the reason for an implementor; a returned verdict has
to be a fact, not a reading of a transcript.

**Independent Test**: Enter review on the dev hub; check the reviewer starts with the named context, returns a
verdict, and that leaving review stops it.

**Acceptance Scenarios**:

1. **Given** review manages a code reviewer with `start` automatic, **When** the session enters review, **Then**
   a reviewer session starts whose owner is the session, with the pull request, the diff since its last round and
   the owner's summary as context, and with a grant no wider than the owner's.
2. **Given** the reviewer returns `verdict: pass`, **When** review's exits are tried, **Then** the exit that
   requires a passing verdict holds as a fact.
3. **Given** an owner session ends, crashes or is lost, **When** that is noticed, **Then** every session it
   manages ends too.

---

### User Story 4 - Blockers go up the chain (Priority: P2)

An agent that meets something outside its grant reports to its owner rather than waiting for the maintainer.

**Why this priority**: Most blockers can be settled by an agent above; the maintainer sees only what is theirs.

**Independent Test**: Make a reviewer hit an action outside its grant and follow the report to its owner, the
repository maintainer, the Steward and Needs you.

**Acceptance Scenarios**:

1. **Given** a managed session hits an action outside its grant, **When** it reports, **Then** its owner gets a
   structured report (blocker or decision, evidence, proposal) and decides within its own grant, changes the
   session's state, or sends it up.
2. **Given** a report reaches the Steward and no agent may decide it, **When** the Steward sends it on, **Then**
   it is a decision in Needs you, with the chain it came through.

---

### User Story 5 - Change a workflow (Priority: P2)

The maintainer edits a workflow, or asks for a change in words and gets a checked draft to approve.

**Why this priority**: Workflows are meant to be tuned from what the measurements show.

**Independent Test**: Ask for a change in words; check the draft comes back with the diff and checks, that a
problem keeps Approve disabled, and that saving makes a new version.

**Acceptance Scenarios**:

1. **Given** the editor, **When** the maintainer opens a workflow, **Then** it shows the definition as a diagram,
   an outline and text, with an inspector for a state and for an exit, and the checks with a replay.
2. **Given** a request in words, **When** the Workflow author's draft is ready, **Then** Needs you shows the
   request, what changed and why, the before and after state by state and exit by exit, the checks and a replay,
   and the maintainer can save, open it in the editor, ask for changes or discard it.
3. **Given** a definition change with a problem the checks find, **When** the maintainer looks at it, **Then**
   Approve is disabled with the reason beside it until the problem is fixed or the change is sent back.
4. **Given** a definition change that grants a sensitive item, **When** it is shown, **Then** that item carries a
   warning that stands out.

---

### User Story 6 - A design spike inside the work (Priority: P3)

Work meets a design question that no accepted board answers, and a state brings in a Designer.

**Why this priority**: It reuses design sessions (011) through the same mechanism.

**Independent Test**: Enter a state that manages a design spike; check the Designer starts and that the owner
waits for the accepted design.

**Acceptance Scenarios**:

1. **Given** a state that manages a design spike, **When** its start holds, **Then** a design session (011)
   starts whose owner is the session, and the maintainer gets a "Look at the design" decision that opens the
   design view on the spike's boards.
2. **Given** the spike's pull request is merged, **When** the owner's exits are tried, **Then** the accepted
   design is a fact they can require; accepting stays the maintainer's.

### Edge Cases

- Two exits of a state hold at once: the first in order moves; the checks flag pairs that can hold together
  without the order saying which wins.
- The judge is unreachable or answers out of form: no move happens, the evaluation is logged as failed, and it
  is tried again on the next matching signal.
- A definition changes while sessions run on it: each session takes the new version at its next move, and keeps
  the old one until then.
- A session is resumed or relaunched: its machine continues in the state it was in, with its counters.
- A managed session's workflow needs more than its owner holds: it starts only after approval at a level above
  the owner.
- Text from outsiders in a transcript (issue bodies, review comments, logs) asks for a move: the judge treats it
  as data and a move still needs its facts.
- A move is rolled back by hand: the session returns to the earlier state; effects outside the hub that already
  happened (a push, a comment) stay and the log says so.

## Requirements

Each requirement is one testable statement. A requirement of another spec is cited with the spec's name and
number, as in "Launch (005) FR-012".

### Functional Requirements

#### Definitions

- **FR-001**: A workflow is a definition the hub stores, with versions, per organization and overridable per
  repository. It has a text form that holds the whole definition, and a version is never changed after it is
  saved.
- **FR-002**: A definition is a hierarchical state machine: states may hold states. A state inside a parent takes
  the parent's grant as well as its own, and the parent's exits apply in any of its states.
- **FR-003**: Each state names: the persona or personas active in it; the instructions added when it is entered;
  its grant (FR-030); its context on entry (keep, compact with a focus, or a fresh session with a hand-off); the
  sessions it manages (FR-040); and whether it is a final state.
- **FR-004**: Each exit of a state names: the state it goes to and, for a parent state, whether it enters at the
  first state or where the session last was (history); who decides it (a judge question, facts, a counter or by
  hand only); `when`, the plain-language question a judge answers; `requires`, the facts the hub checks; `on`,
  the signals on which it is tried; `move`, automatic or on the agent's request; and `approve`, the level that
  must agree (FR-052).
- **FR-005**: A state's exits are tried in their order and the first that holds moves; a child's exits are tried
  before its parent's.
- **FR-006**: `requires` holds only facts the hub can check itself: the change feed, git, check results, the
  machine's counters and what managed sessions returned. A judge never decides a fact.
- **FR-007**: Each machine keeps counters: rounds per state, time spent and tokens used. Exits can test them, so
  every loop ends at a count the definition sets.
- **FR-008**: The hub checks a definition before it is saved or approved: every state can be reached and has an
  exit or is final; every loop is bounded by a counter; every fact named in `requires` is known; two exits of a
  state that can hold at once are flagged unless their order decides; and each sensitive item (FR-034) is marked.
  A problem stops a save or an approval; a mark only shows.
- **FR-009**: A definition, saved or a draft, can be replayed on a past session's history, showing where it would
  have moved differently.
- **FR-010**: Each action of Launch (005) FR-012 is a default workflow. One whose work has no steps has one state,
  whose grant is the action's ceiling.

#### Instances and signals

- **FR-011**: A workflow instance belongs to a session and is kept with the session's record. It survives a stop,
  a resume and a resume under a new launch, with its state, counters and history.
- **FR-012**: Implementation work on git must have a pull request and should have an issue. A machine can't
  leave its implementing states without a pull request; without an issue, the pull request stands for it.
- **FR-013**: Signals are: change feed events (a pull request opened, a review submitted, checks changed, an issue
  labelled, …); session events (a turn ended, the session ended, after a tool use, before compaction); and hub
  events (a decision answered, a session started or stopped, a managed session returned or ended).
- **FR-014**: For each signal the hub finds, without a model, the instances it concerns (by repository, issue or
  pull request, state, and the exits whose `on` names it). Evaluations are debounced per instance.
- **FR-015**: For an exit with a `when`, a judge model gets the current state, its exits, the facts, the
  session's rolling summary and the turn that just ended, and answers in a fixed form: the exit or none, a quote
  as evidence, and a confidence. The hub then checks `requires` and `approve` before anything moves.
- **FR-016**: The judge sits behind a provider choice: a small subscription model by default, or any endpoint
  that speaks the common chat-completions protocol (a local model server or a hosted one). Each workflow may name
  its judge.
- **FR-017**: The hub keeps a rolling summary per session, updated on signals, as the judge's input.
- **FR-018**: Every evaluation and every move is logged: the signal, the state, the proposal, the evidence, each
  check with its value, the judge, its time and its cost, and who moved it.

#### Moves

- **FR-020**: On a move the session gets the new state's instructions at its next turn, without the maintainer
  typing them.
- **FR-021**: The new state's context on entry is applied: kept, compacted with the state's focus once the
  session is idle, or a new session of the state's persona started with a hand-off note.
- **FR-022**: A move that narrows the grant takes effect in the running session.
- **FR-023**: A move that widens the grant resumes the same conversation under a new launch with the new state's
  grant. The hub tells a widening move by comparing the two states' effective grants (parent and own, and the
  sessions they manage).
- **FR-024**: A widening move waits for the maintainer's confirm, which shows what the new state adds, takes away
  and keeps, how the session resumes, and a mark on each sensitive item. A widening move by hand shows it too.
- **FR-025**: A move starts, stops or keeps the managed sessions as the states say, can post a status line to the
  pull request or issue, and raises a decision when `approve` asks for one.
- **FR-026**: The maintainer can move a session to any state by hand, roll back the last move, and pause and
  resume its machine. Each is logged as the maintainer's.

#### Grants

- **FR-030**: A state's grant is a list of capabilities: on GitHub (issues and pull requests: create, read,
  update, delete; comment and review; label and assign; push; merge; workflow runs: trigger, re-run, cancel,
  approve), the shell (where it runs: the checkout, a sandbox or the dev hub, and what it may reach), the web
  (fetch, search), the hub's tools (notes, code search, the code map, …) and the sessions it may manage.
- **FR-031**: A session can do what its state's effective grant allows and nothing more, and does it without
  asking. The hub enforces the grant through the session's tools, its permission mode, a check before each tool
  use and the hub's tool server.
- **FR-032**: Each persona acts on GitHub under its own GitHub App, created from the hub through GitHub's app
  manifest flow with one confirm by the maintainer on GitHub. A review by the reviewer visibly comes from it.
- **FR-033**: For each state the hub gives the session a GitHub token limited to that state's repositories and
  permissions, renewed before it expires, so any command the session runs can do only what the token allows.
  Where branch rules can fence merging, the hub uses them; where they can't, a grant that allows pushing allows
  merging, and the confirm and the definition change say so.
- **FR-034**: These items are sensitive: merging to the default branch; approving workflow runs from forks;
  making a repository public; deleting a repository. A definition change or a confirm that grants one marks it.
  The mark adds no rule.

#### Managed sessions

- **FR-040**: A state's `manages` entries name, for each session it may start: the persona and its workflow;
  `start` (automatic when `when` holds, or on the owning agent's request, checked against `when` and `max`);
  `max`, how many run at once; `reuse` (resume the same session or start a fresh one for a later round); `with`,
  the initial context; `returns`, the shape of the result; and `on_exit` (stop, keep, or hand over to the next
  state).
- **FR-041**: `with` holds only named references the hub fills in from facts: the issue, the pull request, the
  diff since the last round, the owner's summary, notes topics, a brief template with slots. It never copies
  free text from a transcript.
- **FR-042**: What a managed session returns, in the shape its `returns` names, is a fact for its owner's exits;
  its return and its end are signals to its owner.
- **FR-043**: A managed session's grant is its workflow's, capped at its owner's effective grant. A workflow that
  needs more starts only after approval at a level above the owner.
- **FR-044**: A managed session's owner is the session whose state started it. When an owner ends, crashes or is
  lost, the sessions it manages end with it.
- **FR-045**: A `manages` entry on a parent state holds in all of its states.

#### Owners and escalation

- **FR-050**: Ownership is a chain: managed session → implementor → repository maintainer → Steward → the
  maintainer. Each session knows its owner.
- **FR-051**: An agent that meets an action outside its grant, or a decision its state marks as not its own,
  reports to its owner: blocker or decision, the evidence, and what it proposes. The owner decides within its own
  grant, changes the session's state (which may widen its grant, FR-023), or sends it up. The Steward brings
  what no agent may decide to Needs you as a decision, with the chain it came through.
- **FR-052**: `approve` names a level in the chain: none, owner, maintainer (the repository maintainer), steward,
  or me (the maintainer). The default workflows set merging at me: agents merge only under an approved merge
  decision for the pull request's head. Moving a level lower is a definition change (FR-060).
- **FR-053**: Every report and answer is in the log, so the maintainer can see how a decision was made and by
  whom.

#### Changing workflows

- **FR-060**: A definition changes only by the maintainer saving it, in the editor or by approving a proposed
  change. The Steward proposes changes; a reviewer reviews each before it reaches the maintainer.
- **FR-061**: The editor shows one definition as a diagram, an outline and text, with an inspector for a state
  (parent, kind, instructions, context on entry, the grant with inherited items marked by where they come from,
  sensitive items marked, the sessions it manages, its exits in order with a way to reorder them) and for an exit
  (all of FR-004, and whether it widens). Below it are the checks and the replay, then saving as a new version or
  sending it to the Steward as a proposal. It opens any workflow, `workflow-change` included.
- **FR-062**: Asking for a change in words starts the `workflow-change` workflow: a Workflow author drafts the
  change in a state that may read workflows and session history and write drafts, and may not save. The hub
  checks and replays each draft. A draft that grants a sensitive item goes to a reviewer first. After three
  failed drafts the author asks the maintainer.
- **FR-063**: A proposed change reaches Needs you with the request, what changed and why, the before and after as
  an outline diff (state by state and exit by exit, with each row added, removed, changed or moved in the order
  of exits; "only what changes" folds the rest but keeps a changed state's other exits), both diagrams and the
  text diff, the warnings, the checks and the replay, and the actions save, open in the editor, ask for changes
  and discard.

#### Personas and default workflows

- **FR-070**: The persona library has: an **Implementor** (one session per piece of work, carrying its pull
  request and issue and coordinating the engineer, reviewer and QA engineer as managed sessions); a **QA
  engineer** (runs the change, audits whether it can be tested and whether what is tested matters, keeps the
  repository's test setup in order; it runs things where the reviewer reads); a **Repository maintainer** (one
  session per repository, tracking its issues and pull requests through triage, ready, in progress, in review,
  merge-ready, merged and released, starting implementors for ready work, watching for stalls, and taking its
  share of an epic from the Steward); and a **Workflow author** (FR-062).
- **FR-071**: The Steward owns the workflow definitions and the epics that span repositories, splits an epic into
  each repository's share for its maintainer, and brings the maintainer the decisions that are theirs.
- **FR-072**: The default workflows include implement (work holding implement, review and fix, then
  merge-ready), a QA audit, a design spike and `workflow-change`, besides the one-state workflows of FR-010.
- **FR-073**: A design spike is a managed session, the design action of Design sessions (011), started by a
  state when work meets a design question no accepted board answers (at triage, while implementing or for an
  epic). Its merged pull request is a fact its owner's exits can require; merging it stays the maintainer's. It
  raises a "Look at the design" decision that opens its design view on its boards.
- **FR-074**: The Designer checks user-facing pull requests against the accepted boards when a state manages it
  for that.

#### Where it shows

- **FR-080**: A state chip shows wherever a session shows (Sessions, the work item, the Steward panel and session
  chips): the path of states, and its kind (holds, moving, waits for someone, sent up, over) in words and edge,
  never by fill alone.
- **FR-081**: The session view has a Workflow row with the chip, and a machine panel (User Story 2) that shows
  the diagram, or the outline when narrow.
- **FR-082**: The editor, the machine panel, the confirm and the two decisions work at phone width (App frame
  (001) SC-003) and by keyboard (App frame (001) SC-004).

#### Cost

- **FR-090**: The hub measures and shows per piece of work: the sessions that ran at once, judge calls, tokens and
  time, and how often a judge's call was later overridden by hand.

### Key Entities

- **Workflow**: a versioned definition of states and exits, per organization with repository overrides.
- **State**: a node of the machine with persona, instructions, grant, context on entry, managed sessions, exits;
  may hold states.
- **Exit**: a possible move from a state, with who decides, `when`, `requires`, `on`, `move` and `approve`.
- **Instance**: a session's machine: its workflow version, current state, counters and history.
- **Grant**: the capabilities a state allows; the effective grant adds those of its parents.
- **Managed session**: a session a state started, with its owner, context, and what it returns.
- **Report**: a blocker or decision sent up the chain, with evidence and a proposal.
- **Definition change**: a proposed new version with its diff, checks, replay and warnings.

## Contracts

| Contract | Owned / consumed | Version | Spec location |
|---|---|---|---|
| Workflow definition text form | owned | 1 | this spec, FR-001 to FR-010 |
| Judge answer form | owned | 1 | this spec, FR-015 |
| Chat-completions protocol for local or hosted judges | consumed | the common form | the provider's documentation |
| GitHub App manifest flow and installation tokens | consumed | GitHub's current API | GitHub's documentation |

## Device scope and risk

No device risk. Workflows act only on GitHub and the hub; a device run stays the maintainer's go.

## Acceptance

Host level: the definition checks, the text form round trip, effective grants and widening, routing, the
judge's answer form with a fake judge, moves and their effects with a stub agent, managed sessions ending with
their owner, the chain of reports, and the scoped tokens against a fake GitHub. Dev hub: one implement workflow
from a branch to merge-ready, with the cost measurements (FR-090).

## Out of scope

- Workflows that act outside GitHub and the hub.
- Keeping managed sessions alive after their owner ends.

## Success criteria

- **SC-001**: An implement session goes from a pushed branch to merge-ready on the dev hub with no move typed by
  the maintainer except the merge decision.
- **SC-002**: No session can use a capability its state does not grant: every attempt in the acceptance tests is
  refused.
- **SC-003**: A move happens within ten seconds of the signal that makes it hold, judge time included.
- **SC-004**: A loop between two states ends at the count the definition sets, in every test.
- **SC-005**: Evaluations run only on matching signals: a session with no matching signal costs no judge call.

## Assumptions

- The change feed (the hub's structured record of issue, pull request and run changes) carries the facts exits
  require and never outsiders' text.
- The agent runtime lets the hub add instructions at a turn's end, check each tool use before it runs, resume a
  conversation under a new launch and compact on request.
