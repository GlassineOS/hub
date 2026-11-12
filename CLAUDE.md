# CLAUDE.md — GlassineOS/hub

The project dashboard, tool server and host shells (see `README.md`, threat model in
`SECURITY.md`). Every change: run `make check` and extend the tests for new behaviour.

- `hubd/` is the security boundary and runs on the host: standard library only. Anything
  that needs a credential or host rights goes there, never into the app.
- `hubd/ghpolicy.py` is an allowlist and fails closed. A new `gh` command or `gh api` path
  needs an entry in `tests/test_ghpolicy.py`'s allowed list, and the ways to abuse it in the
  refused list. New GraphQL goes in `hubd/graphql/`; never let the app send its own.
- `app/hub/github.py` is the one service behind the web API and the tool server: add a
  capability there, then expose it in both `web.py` and `tools.py`. Give tools that are hard
  to undo or visible to outsiders the `HARD` annotation. Shells stay out of the tool server.
- Text a user or agent supplies reaches `gh` through stdin or a validated argument, never
  as a flag it could choose. The UI shows state in words too: colour is never the only signal.
- Browser libraries are pinned in `app/fetch-vendor.sh` and not committed. The look is Interleaf's web
  form (GlassineOS/ui `web/`: tokens, component styles, fonts) at the release in `app/ui.ref`, fetched by
  `app/fetch-ui.sh` and served from the hub itself; `style.css` holds layout and only the colours the web
  form has no token for. Bump the version with a change to `app/ui.ref`.
- Commits carry an `Assisted-by:` or `Co-Authored-By:` trailer. Never add
  `Signed-off-by`. Run `.glassine/org/scripts/safety-scan.sh --staged` before committing.
- Specs: Spec Kit 1.1.0 with the org preset (`.specify/`, setup in
  `.glassine/org/SPECS.md`); features go in `specs/###-name/spec.md`, the only file committed: it
  names no part of the code, and plans, research and task lists stay local. The repository principles
  are the last section of `.specify/memory/constitution.md`.
- Organization guidance for coding agents (run `git submodule update --init` if the import
  below is missing):

@.glassine/org/AGENTS.md
