# The Steward

Status: design, being built in the order at the end. The screens are on the "Project Command
Center" design canvas, in the Steward section.

The Steward is a regular locked hub session for the project as a whole: an action file, a persona,
its own tool token. It helps with strategy and long-term planning, and it can do through the hub what
you would do in the UI. It reads freely. Everything that changes something asks you first, on the
same permission card as any other prompt.

## The session

- **Action:** `agents/actions/project-steward.toml`, with `object = "project"`, no checkout and no
  planner step. Today every action needs a repository and a number (`validate`, `defaults`, `_name`
  and `describe` in `hubd/agents.py`, and the action list), so this is the one change to session code.
- **One instance,** under the fixed tmux name `steward`. Starting it again opens the one there is.
- **Stopping and resuming:** as for every session. It keeps running if the browser, the app or `hubd`
  goes away, and Resume continues it by session ID after Claude exits or the host reboots.
- **Persona:** `agents/personas/steward.md`. It keeps the whole project in view, gives a recommendation
  with its reasons, says what it hasn't verified, and leaves decisions with you.
- **No shell:** no Bash, `gh` or git. It can read files only in its own directory, and acts only
  through hub tools. Shells stay out of the tool server.
- **All repositories:** its scope gets `all_repos`, which `list_issues`, `list_prs`, `list_runs` and
  `work_search` honor. Other agents see private repositories only by naming one.

## Writes ask first

Its action lists its write tools under `asks_first`. Those aren't on its allowed list, so under dontAsk
nothing runs them except a `PreToolUse` hook saying allow.

- **The hook asks hubd,** as for a question, and hubd puts up a card. Sessions counts it under Needs you, and the
  sidebar shows it. There's no second queue.
- **Allow is enforced in hubd.** It leaves a grant for that session, that tool and those exact arguments, for
  one call within two minutes. The tool server asks for it before the tool runs. So a hook that's missing or
  crashes means a refusal, and only a login can answer a card, whatever Claude Code does.
- **Its turn waits.** No answer in 10 minutes is a no, and it can ask again. Its questions wait for good.
- **Refused before it reaches you:** a merge with no `head`, a start that couldn't happen, whether it's the
  wrong action or item or 4 started sessions are still working, and a call too long to show on a card.
- **A merge has one route for each kind of session.** The Steward's calls are cards, so allowing its `merge_pr` card is the merge
  decision. A full session has no cards: it asks with `decision_request` (kind merge), you approve it on the Decisions page, and
  its `merge_pr` then goes through. Both end as the same merge decision in hubd, made by a login and checked against the head.
- **A merge names its head commit,** which `get_pr` shows, and fails if the pull request has moved on. A change of
  base between the card and the merge isn't caught.
- **Who it goes out as:** the Steward's App if there is one, and otherwise you.

## Questions

When it needs a decision, the Steward asks with `AskUserQuestion`. It's locked, so nothing prompts in its
terminal: a `PreToolUse` hook holds the question for the hub, which waits until you answer. It shows on
Sessions under Needs you and pinned in the sidebar. Esc in its terminal cancels it, and if hubd restarts the question is
refused, so the Steward has to ask again. A question asks
what you want, and a card asks whether it may.

## New work

The Plan new work window has four stages: configure, review the plan, the session, and its drafts. The planner runs
first, on the model you pick (Haiku unless you change it). It is the same `claude -p` run item actions use: read tools,
your text, and the default branch's file names. It searches the docs and earlier work, and writes the session's briefing.
Then the plan waits, for as long as you like and through a restart of hubd: you read it, choose the agent's model (the
planner suggests one), can change the briefing, and press Start. Only then does a locked session start on one
repository, with no item, ending in drafts. You watch it in the window, or send it to the background. If the planner
fails, nothing starts and the window says why. Six kinds, each an action with `object = "repo"`: issue, security audit, architecture audit,
roadmap item, docs gap sweep and dependency review. It opens from the Work list, an issue or pull
request, the Roadmap, a repository in Overview, and the Steward's sidebar.

A full session has your rights, so only you start one. The Steward can suggest one with `suggest_session`: a card in
Needs you opens a start form over the page you're on, filled in, with its notes marked as its own. There you can change
what it covers, which issue is primary, the model and the notes, or go to the full form with a planner step. An issue
session can also cover other issues of the same repository, and one pull request closes them all.

The Steward can message a session through the hub. `message_started_session` goes straight to one it started that only
reads: no write tools and no shell. A message to one that's idle wakes it, so it counts against the limit of 4.
`message_session` reaches any other after you allow it on a card, including one it started that can write, because rights
allowed for one job aren't the Steward's to direct at another. Either way it arrives as
the session's next turn, labelled as not from you. Being a hub tool, it isn't tied to one model provider. Sessions can't
message the Steward: they read untrusted text, and it can read private repositories and ask for writes.

The Steward stays on top of what changes with `changes_since` and the hub's pings. The work sync records every change it sees to
an issue, a pull request or a run in hubd's feed, as facts (item, what changed, old and new state and head commit, time, who,
link), never text. Each running Steward has its own cursor in the feed, and `changes_since` returns what came after it, most
important first (a merge, a moved head, a failing check or run) with nothing left out. A ping to the Steward is only a count,
"12 changes since 15:02 UTC: 3 merged, 2 reviews", from the hub, at most once per interval (`HUBD_PING_SECONDS`, 300 by default)
and never when nothing it hasn't read has changed: it is sent only to a Steward at its prompt, never queued behind a turn. It never starts a stopped session. Waking an idle Steward is refused
while 4 sessions it started are working, as starting one is, but the Steward itself isn't one of the 4 (the person starts it): its pings
pause while those 4 work, and the next round asks again. What the Steward did itself is in the feed marked as its own and doesn't count toward a ping. Not built yet:
sessions changing state, decisions and device reports as feed rows.

- The session gets a detached checkout of the default branch that isn't in the workspace, the read tools,
  and `submit_drafts`. It has no shell and no write tool, and it reads across the organization.
- `submit_drafts` ends it: the drafts go on disk, and hubd ends the session a few seconds later. Nothing
  is lost, as its checkout was read-only. If it stops without handing in, the window says so, and resuming
  it from Sessions picks the run up again.
- Nothing is filed until you choose. Filing runs under your login, one issue at a time, parents first,
  so a failure leaves the rest to retry. A child's body starts with "Part of" its parent: GitHub's
  sub-issue link isn't made. A child waits until its parent is filed. Labels the repository doesn't have
  are dropped, and a failed board placement is noted on the draft. A draft left in filing, because the app
  went away, comes back after ten minutes with a note to check GitHub first.
- No draft starts out chosen. Each body is rendered, with every link and image address printed in full and
  HTML comments shown as text, and images get a warning. Public repositories are marked,
  and both filing buttons name every repository. Filing waits while a target's visibility isn't known.
- Send to the Steward marks drafts as handed and tells the Steward's next turn. It reads them with
  `new_work_drafts`, as data, and files through `create_issue`, which asks you. Handed drafts stay readable
  until their record is pruned; the hub doesn't know which of them the Steward has filed.
- Any session can suggest work with `plan_work`. A suggestion runs nothing and costs nothing: it waits in
  Needs you, and the Steward's in its sidebar too, with a reason. You can change everything before Start.
  Each session gets at most three waiting at once. Full sessions can suggest too. It can only fill in what
  the form shows for that kind. You start it, so it counts as yours, not the Steward's or the suggester's.
- What the Steward is told carries ids, counts and URLs, never a draft's text.

Records are in `state/newwork`. A restart fails a start that was under way, and a draft caught while filing
goes back with a note to check GitHub first. Not built: a milestone choice, private advisories for HIGH
findings, and the Monday briefing's use of these.

## Starting agents

- `spawn_session(action, repo, number)` asks first like any write, then goes through the same planner and
  action limits as a click in the UI.
- **Locked actions only.** hubd refuses `access = "full"` from a token, whatever else allows it, since a
  full session has your rights and a misleading issue could shape its brief.
- **Full actions** are refused before they reach you, and the Steward tells you which to start. This includes
  `issue-docs`.
- **What Allow covers:** a started agent's writes don't ask again, because it is held to its
  own action's limits. Allowing a review allows what that review posts.
- Started agents have no ability to start others. At most 4 run at once.
- `list_running_sessions` names every session running, whoever started it, with its state and what it works on, but
  not what it has said. That's how the Steward finds who to write to with `message_session`.
- `list_sessions` gives their state in words. `session_summary(name)` reads the end of a child's
  transcript. A transcript can hold outsiders' text, like everything else the
  Steward reads, and the cards are what contain that: a message with no card reaches only a session that can't write.

## Memory

- **Plans and work:** the roadmap and issues on GitHub.
- **Journal and weekly plans:** `journal.md` and `plans/<week>.md` in its own directory under
  `~/.local/state/glassine-hub/sessions`, the one place it can write files. It reads them at the start
  of a session, so a new conversation can pick up from them.
- **Decisions:** the project's decisions belong in the public docs. The Steward suggests a draft you
  start, and they arrive as a pull request you review.

## The sidebar

One sidebar on every screen, and the only form of the Steward: open at 440 px with no tabs, or collapsed to a
rail with the count of what's waiting. Moving between screens doesn't
restart anything, since it is one tmux session.

- **Sees:** the current screen and selection, shown as chips, and passed with each question by the
  `UserPromptSubmit` hook.
- **Buttons:** preset messages that change with the screen, in `agents/personas/steward-buttons.toml`.
  The hub pastes one into the session with tmux `paste-buffer`, only when its turn has ended according
  to the Stop hook and its prompt is empty, and queues it otherwise, in memory. Only people press them, and the Steward never
  sends into a child. Interrupt sends Esc, never Ctrl-C, and drops what was queued. `Stop` doesn't fire
  for an interrupted turn, so the panel's Esc marks the session idle itself. Esc typed in the terminal
  leaves it showing Working until its next turn, and the page says what to do.
- **Any session:** state, press and interrupt take a session's name, not only the Steward's, so other
  screens can use them. Questions a session asks aren't in the page yet: you answer in its terminal.
- **State in words:** Working, Waiting, Idle, Stopped.

## Monday briefing

A scheduled `claude -p` run with read tools reads the board and journal, and leaves a briefing at the
top of the sidebar. A systemd user timer starts it through hubd. It changes nothing. It costs a
run each week, so it's off until you turn it on.

## Identity

A `glassine-steward` App, with contents, actions, issues and pull requests write, and organization
projects write, is in `deploy/create-app.py`. GraphQL mutations go out as the calling session's App,
like other writes, so what you allow goes out as this App. A merge needs Contents write, and rerunning,
cancelling and dispatching workflows need Actions write. An App made before this needs both added by hand,
or those calls fail with a 403 after you allow them. It has no Workflows permission, so GitHub may refuse a
merge that changes `.github/workflows`: merge that one yourself. Without an App, its writes go out as you.

## Security

This belongs in `SECURITY.md` when it's built. The Steward reads outsiders' text, sees private
material and can reach every tool. What contains that: only people can allow a write, full sessions can't be
started from a token, and it has no shell. A write can still be wrong in a way you allow, so a card shows the
call itself.

## Build order

One pull request each.

1. Diagnostics for the app's event loop, and the fix for a missing onnxruntime taking the app down, since everything runs through the app.
2. The session with read tools, and `all_repos`. Opened from Overview, shown under Sessions.
3. Writes that ask first, enforced in hubd. Tests: a token can't approve, a yes runs once, a moved head fails.
4. `spawn_session`, `list_sessions`, `session_summary`, and tests for concurrent starts. A paragraph in `SECURITY.md`.
5. The sidebar on every screen, buttons, context chips, and the App.
6. Journal and the Monday briefing.
