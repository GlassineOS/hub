# Research: Sessions (spec 004)

Decisions for the open technical questions in `plan.md`. Each one says what was chosen, why,
and what else was looked at. Paths and line numbers are on branch `001-hub-app` at `c81fe71`.
Nothing here was tried for real: these are readings of the code, and the PR that builds each
decision says what it tried (browser, real `claude`, real GitHub).

---

## R1. Session `covers[]`, `prs[]`, `view`, `origin`

- **Decision:**
  - `covers` is a new config field: a list of up to 6 `{repo, number}` items (the first is the
    primary). `validate` (`hubd/agents.py:248`) checks each like the current `repo`/`number` and
    keeps `repo`/`number` = the first item, so `_prompt`, `_name`, `_checkout` and every reader of
    `config["repo"]` keep working. `also_numbers` stays readable for old `session.json` files and is
    folded into `covers` by `describe()`; new starts write only `covers`. Items in other repositories
    get a read-only snapshot through the existing `request_repository` path when the action has file
    tools, and are listed in the prompt; the worktree is the first item's (005 FR-009). `MAX_ALSO` (5)
    stays the limit of extra items.
  - `prs` is **derived, not stored**: for a session with a branch, `_pr_of(repo, branch)`
    (`hubd/agents.py:1903`) per covered repository, cached in memory for 60 s. For `address`/`fix`
    on a PR, the PR is the covered item itself.
  - `view` (`embedded` | `background`) and `where` (the view it's embedded in) are written to the
    session folder as `view.json` by a new `agent.view` op. Today this is browser state
    (`phases` in `WorkLists`, `app.js:1031`), so "N sent to background" can't survive a reload.
  - `origin` is the Launch record id (005 R1) plus a copy of its `from` (view, item, by): a session
    started before this change has `origin = null` and shows "started before origins were kept".
  - `permission_mode` is read from the action (`hubd/agents.py:947`) and returned by `describe()`.
- **Rationale:** a closed `_FIELDS` set (`agents.py:98`) makes the addition explicit; deriving PRs
  avoids a second source of truth that drifts after a force-push or a closed PR.
- **Alternatives:** storing `prs` when a session opens one (needs a hook on `gh pr create` inside a
  full session's own shell, which the hub doesn't see); `covers` as "also_repos + numbers" (two
  parallel lists that can disagree).

## R2. Typed messages (FR-008)

- **Decision:** a new `agent.say` op (`name`, `text`, `where`), behind the login check at
  `hubd/server.py:200`, calling `Agents._send(name, text)` (`hubd/agents.py:1249`) with `by=None`.
  The web API adds `POST /api/agents/say`. `press` stays for preset buttons. `_send` already refuses
  control characters and text over 4000 characters and queues while a turn runs.
- **Fix needed for "never as a command-line argument":** `Shells.paste` passes the text as an
  argument to `tmux set-buffer -- text` (`hubd/shells.py:118`), so it is visible in the process
  list for the life of that tmux call. The PR switches it to `tmux load-buffer -b <buf> -` with the
  text on stdin. That also changes the path the Steward's buttons and session-to-session messages
  use, which is fine: same buffer, same paste.
- **Transcript:** the words arrive as a normal user turn, so Claude Code's transcript holds them as
  the person's; the Steward's `UserPromptSubmit` hook still adds the screen context
  (`agents.py:858`). History's transcript view labels user turns "You".
- **What changes in the docs:** `docs/orchestrator.md:146-156` ("Buttons", "Any session") and a
  `SECURITY.md` paragraph: a login could already type into any session through the terminal
  WebSocket (`app/hub/web.py:363-410`, `app.js:1328`), so the message field adds no reach; it adds a
  queue that waits for the turn to end. The test `test_the_page_says_only_a_button_and_an_item_to_a_session`
  (`tests/test_app.py:768`) asserts `/api/agents/send` is a 400 and must change in the same PR.
- **Alternatives:** sending keystrokes through the terminal socket (no queueing, could answer a
  question mid-turn); a `text` field on `press` (mixes the preset rule with free text).
