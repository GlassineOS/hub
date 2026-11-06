# Research: Knowledge (spec 008)

Decisions for the open technical questions in `plan.md`. Each one says what was chosen, why,
and what else was looked at. Paths and line numbers are on branch `001-hub-app` at `c81fe71`.
Nothing here was tried for real: these are readings of the code, and the PR that builds each
decision says what it tried (browser, real `claude`, real GitHub).

---

## R1. Knowledge domains and research reports

- **Decision:** Knowledge searches Docs (`app/hub/docsearch.py`) and Work items
  (`github.work_search`, `app/hub/github.py:276`) in parallel and shows Code as "planned" (FR-002;
  `hubd/codesearch.py` exists for agents but is out of scope for the page, spec "Out of scope").
  "Meaning / exact" maps to the semantic search vs the work store's word filter. Pins are page state
  until a research Launch takes them as `pins` (`PIN_KINDS`, `agents.py:140`; `docs` and `ref`
  kinds). Reports are `report` results (005 R2) with `kept: true`; Knowledge lists kept reports, newest
  first, 20 then more. Index states come from `docs.status` and `work.status`; "Run docs CI now" is
  `docs/reindex`, "Ingest now" is `work/sync`, both existing.
- **Rationale:** both indexes and both triggers exist; Knowledge is a view over them, not a new index.
- **Alternatives:** searching code from the page too (out of scope in the spec, and it widens what the page
  reveals about private repositories); one combined index (a change in `GlassineOS/search`, another repository).
