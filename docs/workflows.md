# Workflows

A session holds a state machine: its **workflow** (spec 012). The state it is in says what it is told, what it may use and
when it moves on. Every action runs on one, in `agents/workflows/<action>.toml`; most have one state, whose grant is what the
action allows. `implement` is the first with steps: implement, review and fix inside `work`, then `merge-ready`, or
`escalated` when the fix rounds run out. hubd refuses to start on a file its checks refuse.

## The file

```toml
schema = 1
name = "implement"            # the file's name
initial = "work"              # a parent starts in its own `initial`, down to a state with no children

[state.work]                  # a parent: its grant and its exits hold in every state under it
initial = "implement"
[state.work.grant]
tools = ["Read", "Grep", "Bash"]
checkout = "new-branch"
github = ["read", "pr.write"]

[state.implement]
parent = "work"
instructions = "Make the change, push it and open a draft pull request."
[state.implement.grant]       # added to the parent's: lists are joined, levels take the wider
github = ["push"]
[[state.implement.exit]]
to = "review"
decided_by = "judge"          # judge, facts, counter or hand
when = "The change is complete."
requires = ["pr.open", "pr.checks == pass"]
on = ["turn.end", "feed:pr.checks"]
```

A state has `instructions` (put in the session's next turn when it enters), `personas`, `context` (`keep`, or `compact`
with a `focus`), its `grant`, its `exit`s, and `final = true` if nothing follows. A grant holds `access` (`locked` or
`full`), `permission_mode`, `tools`, `hub_tools`, `asks_first`, `checkout`, `all_repos` and `github` (the capabilities of
the session's own token, such as `read`, `pr.write`, `push`).

Every state a session can be in must have the same `access` and `checkout`: a conversation keeps both, and a move that
would change them fails back. Set them once on the parent, and again on a top-level final state.

## Exits

The exits of a state are tried in order, its own before its parents', and the first that holds moves.

- `decided_by`: `judge` asks a small model the `when` question; `facts` and `counter` need only `requires`; `hand`
  moves only when the maintainer moves it.
- `requires`: facts the hub checks itself, each `name`, `not name` or `name op value`, joined by `or`; the list is their AND.
  A fact the hub can't tell holds neither way. A judge never decides a fact.
- `on`: the signals on which the exit is tried. Nothing else wakes it, so a session with no matching signal costs nothing.
- `move`: `auto`, or `on-request`: tried only when the session asks with the `request_move` tool. The request stands in for
  the judge; `requires` and `approve` still decide. Such an exit needs no `on`.
- `approve`: `none`, or a level that must agree first: `me` (the maintainer), `owner`, `maintainer`, `steward`. An exit
  that holds and needs one doesn't move; it becomes a "Workflow approval" card in Needs you, and approving it makes the
  move if the session is still there and `requires` still holds. `owner` asks the session that manages it, as an approval
  report it answers with `answer_report`; `steward` asks the Steward session the same way. With no such session running (or,
  for `maintainer`, always) the card goes to the maintainer.
- `enter`: for a parent target, `first` (its first state) or `history` (where the session last was under it).

## Managed sessions

A state can run other sessions under it, each an entry in its `manages` list; a parent's entries run in every state under it.

```toml
[[state.review.manages]]
name = "reviewer"             # the entry, and the fact prefix: managed.reviewer.<field>
persona = "reviewer"
workflow = "pr-review"        # an action that runs this workflow as this persona starts it
start = "auto"                # on entering the state, or "on-request": the owner's start_managed tool
when = ""                     # for start = "auto": a plain-language condition the judge tests on the owner's turn end
max = 1                       # how many of this entry run at once
reuse = "fresh"               # or "resume": the entry's last session, when it has stopped, gets the new round
on_exit = "stop"              # when the owner leaves the state: stop, keep, or handover (to an entry of the same name, workflow, persona and returns; else it stops)
with = ["pr", "diff.since_last_round"]   # what its first prompt names
returns = { verdict = ["pass", "fail"], findings = "text-list" }  # what it hands back with return_result
```

- **What a managed session starts with** is its action's prompt and a hub-written block that names the references in `with`:
  the owner's issue or pull request, the head the last round reviewed (`diff.since_last_round`), a brief from the library,
  and with `owner.summary` the owner's rolling summary between marks, as data. Never the owner's transcript.
- **Its grant is capped by what its owner holds**, at all times: when the owner narrows, so do the sessions it manages. Each list is the intersection of the two, each level the lower, and a checkout it
  can't push to fits under any checkout. A workflow that needs more than that waits for an approval above the owner
  (its own owner's session if that holds the extra items itself, else the maintainer), and the start comes after the yes;
  the instance keeps what was approved.
- **Returns** are checked against `returns`: every field, each one of its values, or for `"text-list"` up to 20 lines of
  up to 500 characters, which go to the owner's next turn as a marked data block and are never a fact. The values are kept
  as the owner's facts `managed.<entry>.<field>` (a new head of the pull request voids them), cleared when a new round starts; each return signals `hub:managed.return`, and the end of a
  managed session `hub:managed.end`.
- **When the owner ends**, crashes or is lost, its managed sessions end with it; hubd checks on start and every 30 seconds.
- **Reports**: a managed session sends a `blocker` or `decision` up with `report_up` (evidence and a proposal); the owner
  answers with `answer_report` (`approve` or `deny`, a note) or sends it on with `report_up` and `forward`. A report from the
  top of the chain is a decision in Needs you. Every report and answer is in the machine log.
- Tools that come with the role, not the grant: `start_managed` (a state with on-request entries), `answer_report` (a state
  that manages), `return_result` and `report_up` (a managed session; `report_up` also for any session whose workflow moves).
  At most 8 managed sessions run at once in all.
- **Naming the item.** An owner on no single item (a repository's maintainer, the Steward) names what a managed session
  works on with `start_managed`'s `item`: a repository alone for an action on a repository, `repo#N` for one on an issue
  or pull request. A maintainer names only items of its own repository; an owner on its own item names none. A wrong item
  is refused before the `when` is judged.
- **The owner's pull request.** A pull request a managed session opens on its own branch is carried as its owner's, so the
  owner's `pr.*` facts and the sessions it starts next (a reviewer, a QA engineer) see it. A design session's pull request
  isn't: it only feeds the owner's `design.accepted`.
- **Waking for a `when`.** An auto entry's `when` is judged on the owner's turn ends; on entering a state with one, an owner
  idle at its prompt is woken with fixed words, so it gets a turn to judge.
- **Actions only for managed sessions.** An action with `managed_only = true` (the engineer, the QA audit, the design check,
  the workflow review) is on no menu and starts only under an owner. One with `per_repo = true` (the repository maintainer)
  runs once per repository at a time.

## Facts and signals

Facts: `pr.open`, `pr.merged`, `pr.checks` (`pass`, `fail`, `pending`), `pr.review` (`approved`, `changes_requested`,
`none`), `pr.reviewed` (a review came since the newest head; `not pr.reviewed` means pushed since the review), `branch.pushed`, `issue.linked`, the counters `rounds.<state>`, `time.<state>` (seconds) and `tokens.<state>`, and
`managed.<entry>.<field>` for what a managed session returns, `started.<entry>` (a session of that entry, in force
there, started this round: so an exit can wait for it, or hold only when none started), `report.answered` (the session's
last report up has its answer), `design.accepted` (a design session it manages has its pull request merged; unknown
before one is open), and for a Workflow author's drafts `draft.ok`, `draft.sensitive` and `drafts.failed` (failed drafts
in a row in the current round of its state). A pull request's checks and review count only since its newest
head: after a push they are unknown until the feed sees them again. The session's pull request is found by its branch,
looked up at most once a minute.

Signals: the session's own hooks (`turn.end`, `session.end`, `tool.after`, `compact.before`), the change feed's
(`feed:pr.opened`, `feed:pr.checks`, `feed:pr.review`, `feed:pr.head`, `feed:pr.state`, …, for the items the session covers
and the pull requests the hub has found for it), and the hub's (`hub:decision`, `hub:managed.return`, `hub:managed.end`).

## What the checks refuse

- a state that can't be reached, or isn't final and has no exit;
- a cycle of states with no exit that tests a counter of a state on it, so every loop ends at a count (the `implement`
  workflow's review and fix rounds end at `rounds.fix >= 3`);
- an exit whose `requires` names an unknown fact, or never moves because an earlier one always holds first;
- an exit that leaves the states whose grant has `push` for a state without it, other than a final state, without
  `pr.open` among its `requires`: implementation leaves its states only with a pull request. A move by hand isn't held to it.

Grants of sensitive items (merging, `merge_pr`, approving fork runs, making a repository public or deleting one) and `full`
access are marked; a mark adds no rule.

## Moves and the confirm

A move that narrows the grant takes effect at once in the running session. One that adds anything resumes the same
conversation under a new launch once the session is at its prompt. A move to a capability the session has never held in
this instance waits for the maintainer's confirm, a "Workflow move" card that shows what it adds, takes away and keeps; a
later move back into what it held already doesn't ask again. In `implement`, review drops `push` and fix gets it back without
a confirm, as implement held it. `merge_pr` asks first in every state, so merge-ready needs no confirm: a call shows a card, and allowing it is the merge decision.

While a "Workflow approval" card is up for where a session is, nothing else is tried for it, as for a pending confirm.

Every evaluation and move is in the machine log, with each check and the value it saw, the judge, its time and its cost.

## Versions and the editor

The file under `agents/workflows` is version 0 of the organisation's workflow. Saving one in the editor (`#/workflows`) writes the
next version under hubd's state folder (`workflows/<scope>/<name>/v<N>.toml`, the scope `org` or `GlassineOS__<repo>` for one
repository's override), and a version never changes after. A session on a repository runs that repository's newest override,
else the organisation's newest saved version, else the file. It takes a new version at its next move; one whose state the new
version drops keeps its own until it is moved by hand, and its panel says so.

A save is refused while the checks find a problem, or the library's own checks would refuse the version at start, or a newer
version was saved since the one the editor opened. Only a login saves. A change can also go to Needs you as a "Workflow change"
card, with the outline diff (state by state, exit by exit), the text diff, the checks, the sensitive marks and a replay: Approve
saves it, and waits while a problem stands; Ask for changes and Discard end it.

The editor's Text view is the definition. Its outline and inspector read what hubd parsed; ↑ and ↓ on a state's exits write the
text again through hubd, which drops its comments.

Replay runs a text over a past session's machine log, without a model: exits decided by facts and counters are evaluated on the
facts the log kept, a judge's exit takes the verdict the judge gave then if the same question was asked in the same state, and
rounds are counted by the replay's own moves. A fact the log didn't keep, or a question the judge wasn't asked, is "can't tell".
Steps after the first difference are less certain.


## The default workflows

- **`implementor`** coordinates one issue: in `implement` an engineer (the `engineer` workflow, which writes the change and
  opens the pull request on its own branch) runs under it and hands back `done` or `blocked`; with the change done, checks
  passing and no design spike waiting, `review` starts a code reviewer, `qa` a QA engineer (`qa-audit`) when the change is
  user-facing and, on request, a design check; a fail goes to `fix`, which resumes the same engineer, and three fix rounds
  end in `escalated`. `merge-ready` asks first with `merge_pr`. The implementor holds a shell, a new branch and `push` in
  `implement` and `fix` so its engineer starts within its grant; it doesn't edit. When the work meets a design question no
  accepted board answers, a design spike (a full design session on GlassineOS/ui) starts after your approval, raises a
  "Look at the design" card that opens its design view, and the work waits for its pull request to be merged.
- **`repo-maintainer`** runs once per repository, started by the Steward: it reads the repository's issues, pull requests and
  runs, starts implementors for ready issues (at most 3; the first asks you, as it holds more than the maintainer) and
  reports stalls up. It ends at its token budget.
- **`workflow-change`** is the Workflow author's: it reads a workflow, drafts with `draft_workflow` (checked, diffed and
  replayed like a save, but never saved), and asks to move on. A draft that grants a sensitive item goes to a code reviewer
  (`workflow-review`) first; three failed drafts in a row send it to ask you with `report_up`. On entering `propose`, the hub
  puts the newest passing draft in Needs you as a "Workflow change" card; only your approval saves it. The editor's "Ask for
  a change…" starts one with your request as its notes.
- **`project-steward`** can start repository maintainers (`start_managed`, with the repository as the item) and answers what
  they report up.
