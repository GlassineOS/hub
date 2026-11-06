# Contract: web API routes for Knowledge (internal)

Owned, internal, unversioned: ships with the app (`app/hub/web.py`). Every route keeps the rules
in [001 `contracts/web-api.md`](../../001-app-frame/contracts/web-api.md). Shapes reference `../data-model.md` or the
spec named. "PR n" is this spec's PR in `../tasks.md`; "NNN/PR n" is another spec's.

## Knowledge

| Method, path | Body / query | Reply | PR |
|---|---|---|---|
| `GET /api/knowledge/search` | `?q=&mode=meaning\|exact&domains=docs,work&repos=&open=1&k=` | `{results: [{domain, kind, title, score, snippet, marks: [[start,end]], ref?, link, sessions?}], domains: [{id, state: "ready"\|"indexing"\|"planned"\|"failed", age}]}` | PR 1 |
| `GET /api/knowledge/indexes` | — | `[{id, state, age, action: "reindex"\|"sync"\|null}]` from `docs/status` and `work/status` | PR 1 |

"Run docs CI now" and "Ingest now" call today's `POST /api/docs/reindex` and `POST /api/work/sync`.
