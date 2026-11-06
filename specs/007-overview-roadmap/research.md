# Research: Overview and Roadmap (spec 007)

Decisions for the open technical questions in `plan.md`. Each one says what was chosen, why,
and what else was looked at. Paths and line numbers are on branch `001-hub-app` at `c81fe71`.
Nothing here was tried for real: these are readings of the code, and the PR that builds each
decision says what it tried (browser, real `claude`, real GitHub).

---

## R1. Device lock on Overview (FR-003)

- **Decision:** Overview's device card shows the lock line from `device.status`
  (`hubd/devices.py:185` `_lock_words`, read with a login as `/api/device` does today) and
  `decision.holding` (`hubd/server.py:171`) for "you hold it". It links the Go in force when the
  report names one. No structured `free`/`held` field is added: `devices.py:8-10` keeps reports in
  words on purpose, since anything on the socket can send one. `DeviceView` (`app.js:2426`) and the
  `device` nav entry go in the Header PR; the card lands in the same PR so the information never
  disappears.
- **Alternatives:** a structured lock field (against the module's forged-report rule).

## R2. Roadmap columns and progress (FR-009, FR-010)

- **Decision:** the four columns map from the project's Status options by name (Planned ← "Todo",
  "Planned", "Backlog"; In progress ← "In progress"; In review ← "In review"; Done ← "Done"),
  configured in `config/` with that default; an unknown option goes to Planned with a note. Progress
  per repository counts the GitHub sub-issues already rolled up (`_rollup_subs`,
  `app/hub/github.py:1104`) **plus** open and closed issues whose body has a "Part of
  hub#N" line, found in the work store (`WorkStore.with_bodies`, `app/hub/workstore.py:331`),
  counted once per issue. Filed drafts write "Part of" without a sub-issue link
  (`docs/orchestrator.md:94-95`), so without this they'd never count.
- **Rationale:** the hub's own filing writes Part-of lines, so counting only sub-issues undercounts the
  hub's own work.
- **Alternatives:** sub-issues only (misses filed drafts); making the filer create sub-issue links (a
  GraphQL mutation and a policy entry, and old issues still wouldn't count).
