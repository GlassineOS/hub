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
on_exit = "stop"              # when the owner leaves the state: stop, keep, or handover (to an entry of the same name)
with = ["pr", "diff.since_last_round"]   # what its first prompt names
returns = { verdict = ["pass", "fail"] } # what it may hand back with return_result
```

- **What a managed session starts with** is its action's prompt and a hub-written block that names the references in `with`:
  the owner's issue or pull request, the head the last round reviewed (`diff.since_last_round`), a brief from the library,
  and with `owner.summary` the owner's rolling summary between marks, as data. Never the owner's transcript.
- **Its grant is capped by its owner's** where the owner is when it starts (not again on later moves). Each list is the intersection of the two, each level the lower, and a checkout it
  can't push to fits under any checkout. A workflow that needs more than that waits for an approval above the owner
  (its own owner's session, or the maintainer), and the start comes after the yes; the instance keeps what was approved.
- **Returns** are checked against `returns` (every field, one of its values) and kept as the owner's facts
  `managed.<entry>.<field>`, cleared when a new round starts; each return signals `hub:managed.return`, and the end of a
  managed session `hub:managed.end`.
- **When the owner ends**, crashes or is lost, its managed sessions end with it; hubd checks on start and every 30 seconds.
- **Reports**: a managed session sends a `blocker` or `decision` up with `report_up` (evidence and a proposal); the owner
  answers with `answer_report` (`approve` or `deny`, a note) or sends it on with `report_up` and `forward`. A report from the
  top of the chain is a decision in Needs you. Every report and answer is in the machine log.
- Tools that come with the role, not the grant: `start_managed` (a state with on-request entries), `answer_report` (a state
  that manages), `return_result` and `report_up` (a managed session; `report_up` also for any session whose workflow moves).
  At most 8 managed sessions run at once in all.

## Facts and signals

Facts: `pr.open`, `pr.merged`, `pr.checks` (`pass`, `fail`, `pending`), `pr.review` (`approved`, `changes_requested`,
`none`), `pr.reviewed` (a review came since the newest head; `not pr.reviewed` means pushed since the review), `branch.pushed`, `issue.linked`, the counters `rounds.<state>`, `time.<state>` (seconds) and `tokens.<state>`, and
`managed.<entry>.<field>` for what a managed session returns. A pull request's checks and review count only since its newest
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
