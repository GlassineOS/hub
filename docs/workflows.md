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

A state has `instructions` (put in the session's next turn when it enters), `personas`, `context` (`keep`, `compact`
with a `focus`, or `fresh`), its `grant`, its `exit`s, and `final = true` if nothing follows. A grant holds `access` (`locked` or
`full`), `permission_mode`, `tools`, `hub_tools`, `asks_first`, `checkout`, `all_repos` and `github` (the capabilities of
the session's own token, such as `read`, `pr.write`, `push`).

Every state a session can be in must have the same `access` and `checkout`: a conversation keeps both, and a move that
would change them fails back. Set them once on the parent, and again on a top-level final state.

With `context = "fresh"` the session's conversation ends once it is at its prompt, and a new one of the state's persona
(the session's own if the state names it or names none, else the first the state names that the action runs) takes over
under the same name, checkout and instance: the state, the counters, the managed sessions, their open reports and the
held grant carry over. It starts from the action's first prompt and a hand-off note the hub writes from named references
only: the issue, the pull request, the instructions of the states it is in, the moves the log kept, and the rolling
summary between marks, as data. Never a transcript's words. The old conversation stays in the history, and the machine
log reads both as one session. A stopped session takes the new conversation at its next resume; one that can't resume
keeps its conversation, and the move goes back.

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

## The status line

`status = true` at the top of a workflow makes each move post one line to the session's pull request, or its issue while it
has none: `Workflow: now in <path> (<why>)`, where the reason is the exit's `when` for a judge's move, its `requires` for
one by facts or a counter, or "by hand", "rolled back", "moved back by the hub". hubd posts it as the session's persona's
GitHub App (the hub's login for a persona without one, as an applied result goes out; nothing if the App fails), and edits
that one comment on later moves; a new comment goes out at most once a minute per session. It is off in every shipped
workflow.

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

## What it cost

A session's panel has a **Cost** section for its piece of work: the session and the sessions it manages, over every
conversation it has had. It shows the most sessions that ran at once, the judge's calls with their time and cost, tokens,
cost and time per state (tokens and cost as the session's status line reported them, banked into the state it was in before
each move; a state counts the states inside it), and overrides: a move by hand that rolled back a move of the machine, or
replaced one within ten minutes. The workflows list shows each workflow's averages over its sessions: judge calls per session,
the share of the machine's moves that were overridden, and the median time from a signal to its move. Only a login reads them
(`machine.costs`).

That time, from the first signal of a pass to its move being logged, is kept with each evaluation that moved. Its fixed parts
are shown beside it: the debounce of 2 seconds, the 3 seconds a pass waits for a pull request lookup, the judge's time limit,
and the lookup itself, at most once a minute per session. The change feed doesn't carry a pull request's branch, so a new pull
request reaches its session at the next lookup, not with the feed's event.

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

On a wide screen the editor's Diagram view and the session's machine panel draw the statechart: parents as boxes around
their states, the start dot, H where an exit goes back to where it was, a double border for a final state, and each exit
labelled with how it decides (≈ a judge, = facts, # a counter, dotted by hand). The panel marks where the session is and the
exits its machine took, in the shapes and in a line of words under it; the outline beside it is its text, and stands alone on
a phone. The layout is worked out the same way every time, from the definition alone.

The editor's Text view is the definition. Its outline and inspector read what hubd parsed; ↑ and ↓ on a state's exits write the
text again through hubd, which drops its comments.

Replay runs a text over a past session's machine log, without a model: exits decided by facts and counters are evaluated on the
facts the log kept, a judge's exit takes the verdict the judge gave then if the same question was asked in the same state, and
rounds are counted by the replay's own moves. A fact the log didn't keep, or a question the judge wasn't asked, is "can't tell".
Steps after the first difference are less certain.

