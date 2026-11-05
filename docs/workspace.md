# Leaving the old development tree

Status: design, for review. Nothing is built or prototyped. Costs quoted from the working sessions are from memory.

This says where everything in the old tree goes, under three rules:

- **Nothing on the device needs the hub or the host.** The hub shows; files and scripts do the work.
- **Only a login records the user's word.** An agent can read it and ask for it, never make it.
- **Private stays away from what can post in public,** and text that isn't established says so.

## Done first: transcripts are kept

Claude Code removed transcripts after about 30 days by default. `cleanupPeriodDays` is now 3650 for both logins on this
host, so nothing more ages out; what had already gone stays gone. What a session winds down with remains the main record,
and transcripts are the backstop for the cutover. Copying them waits for `art` and room on this disk.

## Artifacts

**Where:** `~/GlassineOS/artifacts/{dumps,bases,images,captures,bench,vendor}`, mode 0700 (Decision 1). It is
already ignored by the workspace, and outside every worktree. The build cache (`~/.cache/glassine`) stays for what can
be rebuilt: anything may delete it except a running build's folder, which holds a marker, and nothing may point into it.

**How:** one `manifest.jsonl` per folder, kept by `art` in the `workspace` repository. Finding things was the cost,
so an entry is what makes a file count: `id` (start of the sha256), `name`, `path`, `sha256`, `size`, `class` (ours,
vendor, user-data, derived), `what`, `made`, `by`, `from`, `keep` (always, until a date, user), `tombstone`.

- `art add`, `art find`, `art path NAME`, `art verify`. Tools and tests ask `art path`. `--in-place` indexes the old
  tree without moving it.
- `art rm` searches every checkout, worktree, build manifest and the old tree for the id, name and path, refuses on a
  hit, and leaves a tombstone.
- **Retention only the user overrides:** `keep: user` or referenced files go only with the person's word naming them (`art rm --retention-said`). The hub doesn't record retention decisions: a kind comes back when something reads it.
  The same on the device, whose root has little room.
- **A delta needs its parent:** `art rm` counts `parent_base` as a reference, and the base on the device is protected
  automatically, as the parent of the next delta.
- **Docker counts:** builder images, layers and volumes sit outside the manifests, so room-making and the report cover them.
- **`ws done` needs a fix:** it removes with `--force` and doesn't count ignored files. It should list them and refuse
  past a small size. The hub's removal has the same gap, and its discard skips the check.
- Tests with private inputs report "skipped: no private input", never a pass. Each run gets its own cache folder.

No hub tool reads this folder, and the app's container doesn't mount it. It and `notes/` are one copy on one disk, 93% full
today, and room gets made there before the migration. A later encrypted backup on another disk would take device backups
first, as they can't be recreated. Until then, a disk failure loses both folders.

## The device lock and state

**Where:** on the device, in plain files on the shared data partition, outside any deployment's overlay, since a lock has
to survive a reboot, a deployment switch and a rollback. `mkdir` remains the lock. The tool is `dev` in `workspace`, and each step also works by hand
over ssh:

```
lock.d/               mkdir's exit status decides. owner, purpose, since, expected_end, go, notice
queue.d/<time>-<who>  who waits, for what, on which conditions in words, until when, ready
overrides.d/<name>    a live bind or setting: owner, boot id, value, how to remove, survives reboot? removed: now or next
                      agreed restart
```

**A session runs:**

- `dev take --as NAME --purpose "..." --expect 30m --does reboot,suspend --go ID -- CMD`: exit status only, the command
  chained on success, with no print-then-proceed form. The lock is released when CMD ends, unless `--keep`. Without CMD,
  it's held until `dev release --as NAME`, so a session's later commands in new shells carry on under the same name. A name
  is a label, not proof, as the device has no way to check it. Between `mkdir` and `owner` readers say "held, owner not
  written yet".
- **Only the take that made `lock.d` releases it.** A `dev take` by the current holder joins rather than blocks, as `loop`
  does, and a join never releases or gives back: a failed check fails only that command. So `loop` under a take keeps the
  lock until it has restored, later commands under a held lock stay under it, and a hang test's own hangcheck doesn't free
  the lock mid-run. Tests cover all three.
- **`dev take` checks the device first:** renderer, fallback flag, hangchecks since the last release, binds with no
  override record, settings that differ from the seed with no override record. On a failure it gives the lock back and
  refuses, unless `--dirty "why"`. So a session that died mid-test can't leave a bad device for the next run to measure, as
  far as the check can see: an unrecorded live value is invisible, below.
- **A release can name one expected state:** `dev release --as NAME --left cpu-renderer "why"`, a compositor left on its
  CPU renderer after a hang run, and that check passes. The list of names is short and fixed in `dev`, and starts with
  that one. Anything else needs `--dirty` from the next session. The named state stays until the device leaves it, and every
  stamp shows it.
- **Live settings:** a value set through the daemon's control FIFO lives only in its memory, so the check can't see it.
  The daemon gets a read-only status command. Until then `overrides.d` records the value, and the check says it can't
  confirm it. **The check never reads or globs the daemon's `/run` files**, as reading the FIFO blocks. `--does` comes from
  `repro.toml` when a reproducer runs, so a hang test can't start under a go that doesn't cover closing apps.
- `dev stamp` prints the state and any `--dirty` reason: base, boot image, sha256 and source commit of the running
  compositor and daemon, renderer, fallback flag, any named state, live settings (each marked `recorded, unconfirmed` until
  the daemon can be asked), open apps, GPU minimum clock, battery temperature, charging. `repro` and `bench` record it, since
  most runs use bound binaries, often from a branch, and a base id alone wouldn't be true. A `seen` claim names such a
  result, or says what it ran on.
- `dev wait --on "conditions" --until TIME` joins the queue, so conditions don't live in one session's head. Conditions
  are in words, so `dev` can't judge them: the waiter runs `dev ready --as NAME` when they're met, which adds `ready` to
  its entry. `dev take` refuses while an earlier entry is ready, unless `--ahead "why"`. For a session with no entry, every
  ready entry is earlier. One still waiting on its conditions blocks nobody, or `--ahead` would become routine. An entry
  leaves at its owner's take, at `dev wait --drop`, or at its `until` (a few hours at most, proposed), so a dead waiter
  doesn't block for long. `<time>` and `until` are in the device's clock, which `dev` reads from the device.
  `dev notice "rebooting soon"` replaces the message.
- `dev release --as NAME`, by the holder: the same checks, recorded; it releases anyway, and the next `take` stops on them.
  Whoever left an override removes it, or marks it for the next agreed restart when removing it would close your windows.
  Handing a bind to another session changes its owner. A reboot clears records of dead binds by boot id. An unrecorded bind goes to the user, who may choose a reboot, as binds drop.
- `dev break --why`: for a dead holder, only on the user's word. It keeps the old record.
- `dev status` reads it all from the device: no hub, no host state.

**Reporting:** `dev` sends a full snapshot as one JSON line to hubd's socket (`device.report`) at each of these, and at
`take` both before CMD and after: device name, lock, queue, base, deployment, boot image, renderer, overrides, free space,
bases on the device. It's the
whole state, so a lost report costs nothing, and a failed one never fails the command. hubd validates it, stamps the
host's time, and keeps the last per device in its state folder, so a restart loses nothing. The hub never asks the device, as that's device use and could spoil a
measurement. There's no Take button.

**The view** is in words with an age. The read tool `device_status` returns the same sentences and no bare free or held
field, and every answer ends "Only `mkdir` on the device decides":

| Situation | It says |
|---|---|
| Fresh report | "Held by NAME: purpose. Since 14:02, expects 14:30. Reported 3 min ago" |
| Expected end passed | The same, plus "overdue, as far as anyone reported" |
| Report older than 30 min (proposed) | "Out of date: last known state below. `dev status` asks the device" |
| Free at the last report | "Free when last reported, 40 min ago", never plain "free". A by-hand `mkdir` doesn't report |
| Never reported | "No report from this device yet. `dev status` asks the device" |
| Hub or host down | No view, nothing lost: `dev status`, or the files on the device |

Anything on the socket can send a report. A forged one can't take or free the lock, but it can mislead you and agents,
and `purpose` and `notice` are free text: capped, and marked as data for agents. The hub doesn't run tests, take the
lock, queue for anyone or send messages, and recovery never touches it.

## The user's decisions

**Where:** `hubd/decisions.py`, a file per decision in hubd's state folder, each move on disk before it acts, and behind the same
login check in `Hubd.request`. A Decisions page, and a Go button on the device view.

**A record:** `id`, `kind`, `words` (what you typed), `scope` (device, actions, session or any; or repo, PR, head, base), `ends` (a time, a number of runs), `state`, `why_ended`, `made`.

| Kind | Scope | Ends |
|---|---|---|
| go | Named actions (reboot, suspend, load test) and a session | Must have an end: one run or a few hours (proposed) |
| merge | PR, head commit and base | Once used, or when the head moves |

**A go goes stale when the user is back.** "I've got the device" ends every recorded device go, and refuses any `dev
take --does` until you press "Done". It can't stop a running command. Detecting input on the device would be better,
comparing ages rather than clocks. The daemon may already track the last input for its pacing, unverified, so step 2
checks. A bench would use it too, as a touch mid-run spoils a measurement.

**An eye test is its own state:** `dev take --does eye-test` means you hold the device while a session holds the lock and
changes settings. "I've got the device" doesn't end it or refuse it.

**What a take needs.** A take that names actions has to bring a go. Asking the hub has a short limit (3 s, proposed), and
past it counts as down. "I've got the device" is one read of hubd that needs no token.

| Take | Hub up | Hub down |
|---|---|---|
| no `--does` | Runs, no question asked | Runs |
| `--does X` alone | Refused: name a go | Refused: name a go |
| `--does X --go ID` | Runs if the go is current, covers X and answers to this session, and you aren't holding the device | Refused: "unknown" |
| `--does X --go-said "..."` | Runs unless you're holding the device. The words aren't compared with X | Runs, with the words and X in the lock record |

The order is `mkdir`, then the device check, then the hub. A refusal gives the lock back, and only a take that gets through
all three spends a run. A join that names new actions goes through the same table, without the lock changing hands. So "a go
that doesn't cover closing apps" stops a recorded go, and `--go-said` only by the rule below.

**How an agent checks:** `dev take --go ID`, the read tool `decision_check(kind, action, target)` and `dev go ACTION`
send the session's own tool token. A go for a named session answers only to that token; a plain hub shell or a session
started by hand matches only `any`, which needs new code, as only `auth.check_agent` knows the general token today. Answers
are in words. Any session may end a go, as that only narrows. It can ask with
`decision_request(kind, scope, why)`, a card you can narrow before approving. No token op makes one current. Tests: a
token can't add or approve, a moved head fails, an ended go answers no.

**Without the hub:** `dev take --go-said "your words"`. A message you typed to a session, in its live conversation, is a
go for its next lock, until that release. Compaction or Resume ends it. A briefing, hook output or restored history
never counts, nor does **a quote through another session:** it asks you once, and you record it if it's right. The words
go in the lock record, a trail with no hub. Autonomy you grant for a whole run has to be recorded as a go, or compaction
ends it (Decision 2). This is a rule, not a control: nothing proves you said them, and with the
hub down the button can't reach it. Then tell the session, or take the lock yourself (Decision 2).

**Merges are enforced in hubd:** `pr merge` in `op: gh` needs a login token, from the page, or an agent token with a matching decision. It also needs `--match-head-commit`, and hubd compares
its value with the decision's head, so a decision for one head can't merge another. A click binds the head the page showed.
An answer kept from before this is refused a merge. The
decision records its outcome: a merge GitHub refuses, for red checks or a conflict, doesn't spend it, and one whose
outcome isn't known does, and says so. A retarget between check and merge isn't caught. "Approved"
means your decision, never a GitHub review, which a reviewer App can give. Tests go through `Hubd.request`, as `check()`
sees only the arguments: no token is refused, and a different head is refused.

**The limit:** full sessions run as your user, so one could write hubd's files or merge with its own `gh`. This stops
mistakes, relayed quotes and misled locked agents, not a session attacking its own user. Branch protection would be
stronger for merges, but the organization's Free plan doesn't offer it on private repositories.

## Memory

Claude Code keeps memory by start directory, so moving sessions orphans it. **The answer is one start directory,**
already the rule: full sessions start at `~/GlassineOS`, however many worktrees they use below it. Memory also sits under the
login's config folder, so that's one memory per login. The login hub sessions use (`agents.env`) owns it, and the sort goes
there. The other login's folder for this directory becomes a link to it, if Claude Code follows one (not verified, step 4).

- **Don't set `autoMemoryDirectory` in user settings.** Locked sessions run with `--setting-sources user`, so they would
  load private memory, and they can post in public. Their separate, empty memory is a protection. When starting or resuming
  a locked session, or running a planner or the drafter (in `_ask`), hubd reads the user settings of the login it will use,
  and refuses if the key is there. The same goes for what would widen their file reach: `additionalDirectories`, or an
  allow rule for the file tools.
- **The old memory moves by sorting,** by each note's `type`. `feedback` and `user` go to the workspace's memory after a
  read, generalized, each with a pointer to the original. `project` and `reference` go to notes as `archive`. Device
  hazards ("never do this, it ends in a crash dump") stay in memory too, since they must reach a session that doesn't
  search.
- **The old folder stays writable while sessions work from it.** Each session's move sorts what changed since the last
  pass. It goes read-only when the last one has moved, and stays in the archive search.
- **Memory stops being the notebook.** It says how to work; notes say what's known.

## Notes

**What:** per topic, one current state replaced in place, open items, and a log of what was measured, tried and given
up. The shutdown routine shrinks to: update Current and Open. `notes add` works as things happen, since compaction loses
what waits. Work that others need is an issue in the repository it belongs to, written for that repository's readers,
with no note text.

**Where:** `~/GlassineOS/notes/<area>/<topic>.md`, mode 0700, under its own local git with no remote. The workspace's
ignore-everything rule already covers it, as it does `artifacts/`, and with nothing on GitHub the sync and the store can't
hold it. The Overview's list of main checkouts skips a repository with no remote, or `notes/` would show as permanently unclean. One shared checkout, with no issues or pull requests: `notes add` and `notes set` take a file lock around edit,
lint, scan and commit, so sessions can't race. That is where the scan bites: a flagged address or path refuses the
write, and a pre-commit hook covers hand edits. It catches patterns, not prose or decoded dump output, so what's private
stays in `artifacts/`, named by id.

```markdown
## Current
- c12 [seen: base=ID, art=NAME] Faults stop with the fix: 0 in the run named there.
- c14 [inferred: c12] The earlier hangs share that cause.
## Open
- [guess] Same fault in the other ring? Owner: kernel and GPU work.
## Log
### date
- c9 [guess] The preemption path. RETRACTED date by c12: gone with preemption still on.
- Tried X, stopped because Y.
```

**Provenance is required per claim:** `seen` (a base and a command or artifact behind it), `inferred` (from what),
`guess`, `user`, or `archive` (unreviewed, from the old tree). **Current or history** is where it sits. Nothing is
deleted; a retraction stays in place. `notes lint` lets into Current only `seen` with evidence, `user`, and `inferred`
resting on a Current claim. A `guess` or `archive` claim stays in Open or Log, and a retraction takes what rests on it
out with it.

**Search:** `notes find WORDS` in `workspace`, over a SQLite FTS index in a 0700 cache folder, built from the notes, the
old tree's docs and diaries, memory and transcripts, which never passed the scan. It works offline. Every row says
`current`, `history`, `retracted` or `archive, unreviewed` in words. Current ranks first, so a retracted theory can't
pass as a fact. The hub's Notes page is the same query through a hubd op that needs a login, and no token has one. Words
only at first.

**Processing the archive,** on the user's word, area by area, with a budget, by sessions the user starts:

1. **Into notes:** every claim enters the Log as `archive`, through the scan; flagged lines wait for you. One whose source
   shows the output or command itself says so, and is checked first in step 3, but it stays `archive`. A diary saying
   something happened is "tried and what happened", not proof.
2. **Contradictions are listed, not settled:** both stay, with an Open item.
3. **To Current:** only by being seen again, or from you. A guess can't rise by being repeated.
4. **To public docs:** only Current claims that are `seen` or `user`, written fresh as a pull request to `docs`, through
   the safety scan. The old tree's structure and names don't carry over.

## Build records

**Where:** `pins.toml`, the schema, generator and preflight in `builders`. Each build's manifest goes with the build in
`artifacts/` and onto the device. Only promoted bases' manifests are committed to `builders`, and the hub displays
those. (A change from the placement given: one per trial would be churn, and a trial's commits might not be pushed.) A
committed manifest carries a proof as its id, pass or fail, and base, and nothing else from the record.

**A manifest:** `id`, `parent_base`, `trial`, `unmerged`; `inputs` (kernel commit and patches, sway, Mesa, deploy
package, boot, seed version, each with its output's hash, and anything outside git by artifact and hash); `stale`
inputs; `proofs` per patch; preflight result and builder image digests; Alpine release and the full installed package list
with versions, since a base pulls from mirrors and the same pins can give a different base later. Promoted bases keep an
APK snapshot. Each output is keyed on commit, patches and builder digest, so a binary from an older builder counts as stale.

- **Pinned builds:** `build --pins FILE` exports each commit into its own folder under the build cache, so no edit can
  reach it and "no source edits during a build" goes away. Work and output folders are per build, with an output cache on
  the same key, as most bases change one input. A running build's marker holds a pid, so a crashed one's folder isn't kept
  forever. Loop nodes and docker tags are host-wide, so base builds take a host lock.
- **Trials** may pin an unmerged, even unpushed, commit. The manifest says `trial`, and a local ref `refs/builds/<id>` keeps its source from gc after a rebase.
  `art rm` of the build drops the ref. `promote --at COMMIT` names a commit on each input's main, and accepts a trial only if its git tree there matches the one
  in the manifest, as a merge changes the commit but not the tree. A branch that was behind main when squashed won't match. Otherwise it stays a trial, since a rebuild would be a base
  nobody tested. A platform-move branch can pin hand-changed kit inputs by artifact hash, so they aren't lost on merge.
- **Preflight,** before anything starts: binfmt, loop nodes, disk room, native rather than emulated docker tags, stale
  inputs, every pinned commit's blobs on disk (hub-made checkouts are partial clones), sources cached by checksum, a
  binary from another Alpine release, what else is building. A host restart fails in seconds, not at the end.
- **Without asking anyone:** `dev has COMMIT` and `dev next` compare the device's manifest with a commit and with
  `pins.toml` on main. The boot image is written separately, so it has its own record, read from the device, and a kernel
  question is answered from that. `dev next` warns before a deploy that won't fit, using on-device sizes of earlier bases,
  not the stream's. Removing bases on the device hasn't been run there, so nothing here relies on it yet. The hub shows the
  same for promoted bases, and the running base from the report.
- **Seeds:** a test runs migrations against kept old state. `dev live` lists what's on the device and in no image,
  including replayed packages.
- **Patch proof:** the test's source is a reproducer in `workspace`, so it can't go missing. What it showed is a result,
  so the record stays on this host: `artifacts/proofs/<id>.toml`, keyed on the bug or reproducer, as a patch can be dropped
  when upstream takes the fix, and the proof still matters. It lists the patch's `git patch-id` if there is one, and
  `ported_from` when a port changes it, shown as "the old proof doesn't carry over". It holds reproducer, build, result,
  count and duration, date, provenance, log by artifact, and whether it ran the installed package or a test build with a
  lever. The generator joins it into the local manifest, showing the base it was proved on beside this build's. A proof from another base says
  so; it isn't a `seen` here.

## Tools: in the workspace repository

No new repository. The tools sit in `workspace` beside `ws`, in a `tools/` folder added to its ignore exceptions. It's
private and already checked out at `~/GlassineOS`, where full sessions start. The hub lists and reviews it like the others,
but its main checkout is the workspace itself, not a folder inside it, so `main_checkout` and the Overview's list need a
case for it. Without that, a full session on it would clone a second copy inside the real checkout, and `_guard_branch`
would look for unpushed commits in the wrong place.
All of it runs with the hub down, and the tools find `artifacts/` and `notes/` from `~/GlassineOS`, so they work from a
worktree too.

**Code, not data.** A locked session can read a private repository by naming it, and can post, so this rule is what keeps
results from a post. The repository holds source, how to run and what counts as a pass. Results, measurements, dumps,
decoded output and vectors made from vendor files stay on this host, named by id. The scan is a pre-commit hook, but it
only catches patterns, so the tools write results to the right place themselves. Our own measured numbers may stay in a
comment or commit message where they justify a default, as may thresholds and pass criteria. Dump content, captures and
vectors from vendor files may not. A locked session on a `workspace`
pull request gets a worktree of the hub's bare review clone: no notes and no artifacts.

- **`dumps`:** `dumps add` stores a GPU fault with time, kernel, app and what ran, and the Mesa and render profile of the
  process that faulted, since a Flatpak app doesn't load the system's. `dumps show ID` is the one-line decode, with the
  flags and mount inside. Decoded output is large and regenerable, so it isn't kept, and the decoder is an artifact with
  its Mesa version. `dumps group` fingerprints on RBBM status, IB1 rem, ring and preempt state, and names no cause. IB2 rem
  splits one bug across dumps, and a shader hash is a candidate, as it's inferred. Dumps of one event are linked, since a
  second recovery can blame an innocent process. They hold GPU memory from your apps, so decoded output is private too.
- **RAM dumps** are their own kind: linked to the build for symbols, the kernel log always kept, the raw image until a
  date. Capturing one has to work before any long-press and with no hub, so that tool moves here too.
- **`repro/<name>/repro.toml`:** source, how to run, pass criterion, needs, `--does`. A reproducer made from a captured
  stream is private, so the source can be an artifact id. Results per base go to `artifacts/repro`, with the binary's hash
  and build base, and a mismatch warns. `repro gate BASE` lists what's missing or failed, including an explicit "no
  reproducer" row for old patches. It runs nothing.
- **`bench/`:** every result records the kit's commit. A result is a run of interleaved arms, each with its settings, and
  one invalid arm invalidates the comparison. A scroll run must prove motion from counters it reads (`motion_proved`), or
  it's stored as invalid and prints no number. An eye test is a result too: `user` provenance with binary, settings and
  content shown. Private inputs go by artifact id. GPU host tests record what else was running. Results go to
  `artifacts/bench`.
- **`loop`:** takes the lock, builds for arm64 (about 3 min, from memory), copies to a per-override folder on writable
  storage, with removal, binds over the live binary, records an override, tests, restores. Reboot is the rollback. Restoring
  stops the process first, never a lazy unmount under it, and reapplies lost live values. Each binary has its own recipe,
  and a protocol change swaps its set together. Restarting the compositor closes every app window, so it says so and needs
  a go. It uses the session's own environment, re-executes where it can, never kills the daemon by hand, and keeps the
  config file's inode and mode. These hazards are in the tool so they reach a session that doesn't search.

## Merging across repositories

- **A branch set** is the same branch name in each repository, as `ws new` makes. Each pull request says `Set: NAME, N
  of M` and what was tested: host, device on a base id, or nothing. One-line fixes need no more.
- **Pins make it atomic.** Components merge in order, and nothing ships until a `pins.toml` bump in `builders` merges:
  that one pull request is the set's merge. A trial pins the branch heads. A platform move keeps its pins on a
  `builders` branch while others keep merging.
- **Blockers** are issues labelled `blocks-merge`, saying why and who can clear it, linked from the pull request.
- **The queue view** is a page over the work store: sets, order, tested, your approval, GitHub's reviews apart,
  blockers. It doesn't merge, review or spawn anything. Approving records a merge decision.
- **Version mismatch:** one set of pins installs both sides, so a true mismatch comes from `loop`. First a protocol
  constant in each source, compared by `loop` and the preflight; a runtime check only if that isn't enough.

## Keeping private things private

`SECURITY.md` keeps agents from finding private text by accident, but a named private repository stays reachable: the sync
pulls every repository, and `work_search`, `get_issue`, the lists and kept answers serve it. So what must not reach a post
isn't on GitHub at all. Notes and artifacts stay on this host. Captures can hold paired device addresses, so they stay in
`artifacts/`.

| Who | Artifacts | Notes, archive search | Tools (`workspace`) |
|---|---|---|---|
| Locked session or planner (can post) | Out of reach: file tools stop at its folder and checkout, given the settings check under Memory and the symlink check below | No tool | Like any private repository |
| Steward (no shell, each write asks first) | No tool | No tool (future scope, Decision 4) | Like any private repository |
| Full session | Your rights: readable | Readable, as files | Readable, and it runs the tools |
| App container | Not mounted | Nothing, except the Notes query, with a login | Through hubd, as today |

- **Tools are by list:** `device_status` and `decision_check` aren't listed by any locked action, as `purpose` is free
  text. `SECURITY.md` gets a section with each step.
- **Full sessions are the limit,** as `SECURITY.md` says. One started on an outsider's issue can be misled with your
  rights. The hub can add deny rules on `artifacts/` and `notes/` and say so on the card; that's a hint, since a shell
  gets around it.
- **Pushes:** add to the safety scan's pre-push path: a blob whose hash is in a manifest is flagged, in private
  repositories too. It only catches exact copies.

## What this doesn't cover

- **Hiding a repository from the hub.** Nothing needs it while notes stay local and the tools hold no data. If private text
  ever has to live on GitHub, the sync, the kept answers, `op: gh` and checkouts would all need a check by repository, first.

Also not here: moving the old tree's tools into repositories (its own plan). Updates and deployments on the device. Device tests from
the hub, automated triage, CI for device kernels, a chat layer, dashboards. Backup software. Whether the old tree is
ever deleted.

**Not verified, each checked before the step that needs it:** branch protection on the plan (before relying on it for
merges); that the lock's storage survives a reboot, a deployment switch and a rollback (step 2); what per-build kernel folders
cost without a shared object cache, and with reused outputs, on one build (step 3); word search on transcripts, its quality and speed (step 4); whether `--resume`
crosses directories (sessions finish where they are anyway); input age on the device (only if detection is wanted); the device's clock, which orders the queue (step 2); what a reset does to the
lock and `overrides.d`, as the full level keeps only home (step 2); whether a link joins two logins' memory (step 4).

**Checked:** `ws` copes with a `tools/` folder and new ignored folders, in the tests of workspace#2 to #4 (open as of 2026-11-05).
Links out of a locked session's folders, once, with a real session on Claude Code 2.1.318, on 2026-11-05: Read refused a link to
a file, a path through a link to a folder, and one through a relative link; Grep with its path on a file link or a folder link
was refused, and Grep over the folder holding them found only the plain file; Glob on a folder link was refused. So the checkout
needs no check for links leaving the tree. Nothing notices if a Claude Code update changes this.

## Decisions

All decided. Each keeps its reasons, as later work may need to reopen one.

1. **`~/GlassineOS/artifacts/`, with those folders and manifests?** Decided: yes, on this disk, with room made before
   the migration. It's already ignored, outside every worktree, out of reach of locked sessions and the container.
   Vendor files and dumps never reach GitHub, even a private repository. No second disk is chosen, so a disk failure
   would still take the device backups.
2. **Goes and merge approvals in the hub, at one more click per go?** Decided: a click in the hub for merges and for
   autonomy over a whole run, with a named end, so compaction doesn't end it. For one use of the device, you just tell the
   session, and that holds for its next lock, so the device never depends on the hub. That go is a rule with a trail, not a
   control. A session's questions and prompts can show as cards in the hub as well as its terminal (hub#26). That
   answers the session, and isn't a go.
3. **`notes` on GitHub at all, even private?** Decided: no, local only, beside artifacts. Once text is on GitHub
   it's out, and the scan catches patterns, not a pasted dump or diary.
4. **May the Steward search notes?** Decided: future scope, not at first. Its public posts have one click between them and what it
   read, weaker than the rule at the top. When it's built: a scoped hubd op, a filter by source so no
   transcripts, diaries or old memory, its `asks_first` counted in the test, and a card line "this session can read
   notes".
5. **New repositories for this?** Decided: none. Tools go in `workspace`, and notes and artifacts are folders in it that
   it ignores. Tools can split out later if they outgrow it.
6. **Archive processing's budget and first area?** Decided: Sonnet, a token cap on each run, no overall budget. It starts
   with Bluetooth once the notes tool exists, to learn the cost before going on to the rest.
7. **A saver on the device for GPU hang dumps?** Decided: future scope, low priority; off by default if built. A devcoredump lasts about 5 minutes, and a
   hang can come from you tapping a link with no session testing. So `dumps add` after the fact misses it. A saver would
   write to persistent storage with a size cap, and work with host and hub down. New device code, and it takes space there.

## Build order

One pull request each.

1. **Artifacts.** `art` in `workspace`. Then `dumps` with the decoder. Then `ws done` and `CLAUDE.md`, and the
   hub's session removal, normal end and discard alike, since `_unsaved` doesn't count ignored files and discard skips it.
   The hub's case for the `workspace` checkout. Then room made on this disk, the old tree indexed in place,
   and the transcripts copied.
2. **Device and decisions.** `dev` in `workspace`. Then the hub: `device.report` and the view, then decisions, their tools
   and merge enforcement.
3. **Builds.** `builders`: pins, per-build folders, manifest, preflight. `workspace`: `dev has`, `next`, `live`, and proofs in `artifacts/`.
   The hub shows promoted manifests, by the `repos/GlassineOS/...` read `ghpolicy` already allows. The seed migration test.
4. **Notes.** `notes` with `add`, `set`, `lint`, `find`, and the first sort of memory. The hub's page, and the Overview skipping `notes/`. Then archive
   processing, area by area.
5. **Reproducers and the merge queue.** `repro`, `bench`, `loop`. The hub's queue view. Then repositories cut over one
   at a time, `linux` last, and the working sessions move when the user says, sorting their memory as they go.
