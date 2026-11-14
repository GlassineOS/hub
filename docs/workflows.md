# Workflows

A session holds a state machine: its **workflow** (spec 012). The state it is in says what it is told, what it may use and
when it moves on. Every workflow is one file, `agents/workflows/<name>.toml`: its states, its `[launch]` (what Launch shows and
runs with) and its `[[start]]`s, the buttons it puts on an item's page (see Starts). Most have one state, whose grant is what
the session may do. `implement` is the first with steps: implement, review and fix inside `work`, then `merge-ready`, or
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
log reads both as one session. A stopped session takes the new conversation at its next resume, and keeps the one it
had until a resume goes through; a running one that can't resume keeps its conversation, and the move goes back.

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
on_pr = ""                    # the workflow it runs instead when the owner is on a pull request and no issue (the engineer's: pr-engineer)
start = "auto"                # on entering the state, or "on-request": the owner's start_managed tool
when = ""                     # for start = "auto": a plain-language condition the judge tests on the owner's turn end
max = 1                       # how many of this entry run at once
reuse = "fresh"               # or "resume": the entry's last session, when it has stopped, gets the new round
on_exit = "stop"              # when the owner leaves the state: stop, keep, or handover (to an entry of the same name, workflow, persona and returns; else it stops)
with = ["pr", "diff.since_last_round"]   # what its first prompt names
returns = { verdict = ["pass", "fail"], findings = "text-list" }  # what it hands back with return_result
```

- **What a managed session starts with** is its action's prompt and a hub-written block that names the references in `with`:
  the owner's issue or pull request, the head the last round reviewed (`diff.since_last_round`), the pull request's
  failing check runs with their links (`checks.failing`, read with `get_run_log`), a brief from the library,
  and with `owner.summary` the owner's rolling summary between marks, as data. Never the owner's transcript.
- **Its grant is capped by what its owner holds**, at all times: when the owner narrows, so do the sessions it manages. Each list is the intersection of the two, each level the lower, and a checkout it
  can't push to fits under any checkout, as does a pull request's own branch under an owner on a new branch when the pull
  request is the owner's own (one it or its engineer opened, or the one it is on), never one a maintainer names. A workflow that needs more than that waits for an approval above the owner
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
- **Reports overtaken by events.** An open report is withdrawn when its session's machine moves: the session is told which,
  and a card it raised ends. A session withdraws one of its own reports with `withdraw_report` (its id and why), and no one
  else's. A reporter idle at its prompt is woken, with its open reports listed, when a session it manages hands back, when
  one of its reports is answered, and when a fact a report named (`pr.checks`, say, written in its text) changes.
- **Waking an idle owner.** An owner idle at its prompt gets a hub message, fixed words and facts only, when a session it
  manages hands back, ends by itself or is stuck, and when a report sent to it arrives. One message carries what came
  together; a session that isn't at its prompt gets nothing, as the news comes with its next turn. A move that widens its
  grant relaunches it first, and the message follows the relaunch.
- **Stalls.** A machine with no exit that can still hold, nothing it manages running or waiting to start, no confirm or
  approval open and its owner idle is stalled. After 10 minutes like that the hub logs it, tells and wakes the session (and
  its own owner), and raises one card in Needs you, "stalled in <path>", with each exit's failing requires and the values
  that fail them. The machine panel shows the same. Any move ends the card. Pending checks, a fact the hub has no value
  for or a time fact count as a wait, not a stall.
- Tools that come with the role, not the grant: `start_managed` (a state with on-request entries), `answer_report` and
  `managed_status` (a state that manages), `return_result` and `report_up` (a managed session; `report_up` also for any
  session whose workflow moves).
- **What the owner is told.** Its first prompt, and its turn on each move into a state that manages, end with one line from
  the definition and the hub's records (never a transcript): each entry in force, whether it starts by itself, once its
  `when` holds, or on request, and the sessions already running under it by name; one that starts by itself is the hub's to
  start and hands back by itself. A fresh context's hand-off note has the same line. A session that starts later without
  being asked for (a `when` that came to hold, an approval, room under the cap) is told to its owner once, at its next turn.
- **`managed_status`** reads, for the owner's state: each entry in force, how it starts, its sessions under this
  conversation (name, state, idle, ended) and a note on what it waits for (an approval, the cap, a holder of its item, its
  `when` not judged yet or judged not to hold, a start that can't happen this round); and any other session still running
  under it (an `on_exit = "keep"` one). `start_managed` for an entry that starts by itself starts and judges nothing: it
  answers with the same (`by_itself`, its sessions, the note). An entry the state hasn't is refused with every entry and how
  each starts.
  At most 20 managed sessions run at once in all, not counting one of a staged workflow that is idle in a final state (an
  implementor that is merge-ready). A start that this holds back tells the owner once, and an automatic entry that didn't
  start in its round is tried again soon (after 5, 15 and 45 seconds), on the owner's next signals, and when a managed
  session ends. On a move, the sessions the state left stop before the ones it enters start, so a session about to stop
  doesn't count against the cap; an entry with `reuse = "resume"` in both states (the engineer, from `implement` to `fix`)
  resumes the session the state left.
- **A start that can't happen.** One that can't start for a reason that won't change by itself (its workflow works on an
  issue and the owner is on none, the workflow is gone, a fork's branch to push to) is one failed line in the machine log,
  one word to the owner and one card in Needs you that says why. It isn't tried again in that round, nor waited on: the
  owner stays where it is until it is moved by hand or a new round comes.
- **Naming the item.** An owner on no single item (a repository's maintainer, the Steward) names what a managed session
  works on with `start_managed`'s `item`: a repository alone for an action on a repository, `repo#N` (with or without
  `GlassineOS/`) for one on an issue or pull request. A maintainer names only items of its own repository; an owner on its
  own item names none. A wrong item is refused before the `when` is judged; the judge's question names the item, and its
  answer is kept per item. A start that needs an approval asks for that item: the card names it, an approval starts it for
  that item, and what it adds holds for that item only.
- **A start waiting for approval** stays up across the owner's moves while its entry is in force, and is withdrawn when the
  owner leaves the states where it is. Meanwhile `started.<entry>` holds, so work that waits for that session waits for
  the answer too.
- **The owner's pull request.** A pull request a managed session opens on its own branch is carried as its owner's, so the
  owner's `pr.*` facts and the sessions it starts next (a reviewer, a QA engineer) see it. A design session's pull request
  isn't: it only feeds the owner's `design.accepted`.
- **Waking for a `when`.** An auto entry's `when` is judged on the owner's turn ends; on entering a state with one, an owner
  idle at its prompt is woken with fixed words, so it gets a turn to judge.
- **Actions only for managed sessions.** An action with `managed_only = true` (the engineer, on an issue or a pull request, the QA audit, the design check,
  the workflow review) is on no menu and starts only under an owner. One with `per_repo = true` (the repository maintainer)
  runs once per repository at a time.

## The status line

`status = true` at the top of a workflow makes each move post one line to the session's pull request, or its issue while it
has none: `Workflow: now in <path> (<why>)`, where the reason is the exit's `when` for a judge's move, its `requires` for
one by facts or a counter, or "by hand", "rolled back", "moved back by the hub". hubd posts it as the session's persona's
GitHub App, and only so: a persona without an App, or whose App fails, posts nothing. It edits that one comment on later
moves while the comment is still the App's own on that item; otherwise it posts a new one, at most once a minute per
session. It is off in every shipped workflow.

## Facts and signals

Facts: `pr.open`, `pr.merged`, `pr.checks` (`pass`, `fail`, `pending`), `pr.review` (`approved`, `changes_requested`,
`none`), `pr.reviewed` (a review came since the newest head; `not pr.reviewed` means pushed since the review), `branch.pushed`, `issue.linked`, the counters `rounds.<state>`, `time.<state>` (seconds) and `tokens.<state>`, and
`managed.<entry>.<field>` for what a managed session returns, `started.<entry>` (a session of that entry, in force
there, started this round, or its start waits for an approval: so an exit can wait for it), `when.<entry>` (what the judge
said of the entry's `when` this round; unknown until it is judged, so `not when.qa` holds only when it was judged not to
hold, never because the session couldn't start), `report.answered` (the session's last report up has its answer),
`design.accepted` (a design session it manages has its pull request merged; unknown before one is open), and for a
Workflow author's drafts `draft.ok`, `draft.sensitive`, `draft.reviewed` (the newest draft went to a reviewer) and
`drafts.failed` (failed drafts and refused calls in a row in the current round of its state). An owner that carries its
managed session's pull request has that one's facts first, before any it opened itself. A pull request's checks and review count only since its newest
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

## Starts

A start is a button on an item's page: how a workflow begins on an issue, a pull request, a run, a repository, the project,
knowledge or notes. A workflow with no `[[start]]` is **managed only**: it runs under another session whose workflow starts it
(an engineer under an implementor), or resumes where one already ran. The list groups workflows by the kind of item they start
on, with the managed-only ones last.

```toml
[launch]                       # what every start of this file shares, unless a start sets it again
personas = ["implementor"]
result = "pr"

[[start]]
id = "implementor-pr"          # by default the workflow's name; ids are unique across the library
on = "pr"                      # issue, pr, run, repo, project, knowledge or notes
label = "Take this on"         # the button
summary = "One line: what the session does."
ceiling = "What it may do at most, in words: the MAY line under the button."
state = "review"               # where it starts; by default the workflow's `initial`
lead = true                    # the item's first button; one lead per kind of item across the library
when_held = "hide"             # beside, ask or hide (below)
models = ["sonnet", "opus"]    # what the brief may choose
efforts = ["medium", "high", "xhigh"]
prompt = """
Carry pull request #{number} of GlassineOS/{repo} to where the maintainer can merge it.
"""
```

A start takes `verb`, `result`, `plan`, `personas`, `when`, `needs` and the other `[launch]` fields too; one it doesn't set
comes from `[launch]`. Launch opened from a start is that start: its action is the start's id, its title the label. A start's
id is the action id the API, the records and the history use, so the ids of the old actions carry on unchanged.

The checks refuse a start without a label, one that names a state the workflow doesn't have or starts in a final one, two
starts with the same label on one kind of item, two leads for one kind of item (across the library too), a start id used
twice, an `ask_move` on a start that doesn't ask, and a start with `when_held = "beside"` whose first state, or any state
its session can move to, writes on the item (full access, a GitHub capability beyond reading, or a hub tool that writes):
what runs beside a holder only reads.

### Held items

A session **holds** its item while it isn't ended or final (a workflow with one state holds while it runs): an issue, a pull
request, a run or a repository it was started on, and for a pull request also the ones it or the sessions under it opened.
Only the topmost holds: an engineer under an implementor doesn't, its implementor does. A session started beside a holder
never holds. While the hub doesn't yet know which pull requests a session opened, the item is "unsure", never free: starts that
would hold wait.

While an item is held, its page names the holder first (its persona, state and next moves) and each start does what its
`when_held` says:

- **`beside`** runs anyway, next to the holder, read-only.
- **`ask`** goes to the holder, not to a new session: if the holder's state starts that start's workflow on request, it is
  a managed start under the holder, with the holder's caps and the approval card as if it had asked; else if the start
  names `ask_move` and the holder's state has an on-request exit there, it is a move request on the holder; else it is
  hidden, with why.
- **`hide`** isn't offered; the page says how many are hidden.

Two starts on the same free item at once: the first claims it before anything else waits, the second is refused and the
page shows the holder. Starts that hold nothing (singletons such as the Steward, and `beside`) claim nothing.

### What a session receives

A start's first prompt ends with the item's details, read from GitHub by hubd when the session starts and marked as data,
not instructions: kind, repository, number, title, state, labels and links. Each value is folded to one line and cut, and
characters that draw nothing are dropped, so text from anyone is quoted to the session, never followed. If GitHub doesn't
answer, the block says so. The editor's Starts section shows the prompt with this block, filled with placeholders.

Taking a pull request on with "Take this on" starts the implementor in `review`, with that pull request as its own: the hub
looks its state up, so `pr.open` is known though the feed may have seen nothing change. A fail asks you to confirm `fix`,
which adds `push`. With no issue, `fix` runs its engineer entry's `on_pr` workflow, `pr-engineer`: an engineer on the pull
request's own branch, whose token may push there, never merge. Its fix pushed and its checks passing, the implementor goes
back to `review` for a fresh reviewer. A fork's pull request can't be taken on, nor any start whose workflow pushes or works
on its branch: nobody here may push to a fork's branch. Its page says so beside the start, and a start is refused with the
same words; when GitHub can't say whether it is a fork's, the engineer's checkout refuses it.

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

The editor's Starts section lists the workflow's starts by kind of item, with those it inherits from the file; a start is
edited there (kind, label, summary, the state it starts in, lead, what it does when the item is held, models, efforts,
prompt) through hubd, like a move of exits, and the save dialog, the Workflow change card and `draft_workflow` list the starts
that change. Every workflow opens in the editor, one-state ones too.

The editor's Text view is the definition. Its outline and inspector read what hubd parsed; ↑ and ↓ on a state's exits write the
text again through hubd, which drops its comments.

Replay runs a text over a past session's machine log, without a model: exits decided by facts and counters are evaluated on the
facts the log kept, a judge's exit takes the verdict the judge gave then if the same question was asked in the same state, and
rounds are counted by the replay's own moves. A fact the log didn't keep, or a question the judge wasn't asked, is "can't tell".
Steps after the first difference are less certain.


## The default workflows

- **`implementor`** coordinates one issue: in `implement` an engineer (the `engineer` workflow, which writes the change and
  opens the pull request on its own branch) runs under it and hands back `done` or `blocked`; with the change done, checks
  passing and no design spike waiting (or waiting for your approval), `review` starts a code reviewer, `qa` a QA engineer
  (`qa-audit`) when the judge finds the change user-facing and, on request, a design check, waiting for both; it skips QA
  only when the judge found it isn't user-facing; a fail goes to `fix`, which resumes the same engineer, and three fix rounds
  end in `escalated`. Failing checks go to `fix` too, with no confirm: from `implement` once the engineer is done with its
  pull request open, and from `review` and `qa`; the engineer is handed the failing runs. `fix` goes on to `review` only
  with checks passing; pending checks are a wait. `merge-ready` asks first with `merge_pr`. The implementor holds a shell, a new branch and `push` in
  `implement` and `fix` so its engineer starts within its grant; it doesn't edit. When the work meets a design question no
  accepted board answers, a design spike (a full design session on GlassineOS/ui, in force in `implement` only) starts
  after your approval, raises a "Look at the design" card that opens its design view, and the work waits for its pull
  request to be merged.
- **`repo-maintainer`** runs once per repository (through a start, a resume or a past session's resume; one in its final
  state doesn't count), started by the Steward: it reads the repository's issues, pull requests and
  runs, starts implementors for ready issues (at most 3; each issue's first start asks you, as an implementor holds more
  than the maintainer) and reports stalls up. It ends at its token budget.
- **`workflow-change`** is the Workflow author's: it reads a workflow, drafts with `draft_workflow` (checked, diffed and
  replayed like a save, but never saved: when sessions ran on the workflow it is replayed over the named one or the
  newest, and a replay that can't run fails it), and asks to move on. A draft that grants a sensitive item goes to a code
  reviewer (`workflow-review`) first, and a draft it failed goes back only as a new one; three failed drafts in a row send
  it to ask you with `report_up`, and a token budget ends the run. On entering `propose`, the hub puts the newest passing
  draft in Needs you as a "Workflow change" card with its replay; only your approval saves it. A draft from a version that
  is no longer the newest isn't proposed: the author is moved back to drafting, told why. The states the hub acts on are
  named in its `[launch.drafting]` table (draft, review, reviewer, propose), which the library checks. The editor's "Ask for
  a change…" starts one with your request as its notes.
- **`project-steward`** can start repository maintainers (`start_managed`, with the repository as the item; two at once)
  and answers what they report up. The tree fits the cap: 2 maintainers, each with 3 implementors, each running at most
  two sessions at once.
