# Contract: web API routes for Overview and Roadmap (internal)

Owned, internal, unversioned: ships with the app (`app/hub/web.py`). Every route keeps the rules
in [001 `contracts/web-api.md`](../../001-app-frame/contracts/web-api.md). Shapes reference `../data-model.md` or the
spec named. "PR n" is this spec's PR in `../tasks.md`; "NNN/PR n" is another spec's.

## Overview, Roadmap

| Method, path | Change | PR |
|---|---|---|
| `GET /api/overview` | rows add `attention` (sort key: failing runs, waiting sessions, open PRs, last activity) and `last_commit`, `last_activity` (FR-004, FR-007) | PR 1 |
| `GET /api/project` | items add `column` (one of the four, R2) and `progress: [{repo, done, total}]` from sub-issues ∪ "Part of" | PR 2 |
| `GET /api/device` | unchanged; read by the Overview card | 001/PR 2 |
