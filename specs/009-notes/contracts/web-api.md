# Contract: web API routes for Notes (internal)

Owned, internal, unversioned: ships with the app (`app/hub/web.py`). Every route keeps the rules
in [001 `contracts/web-api.md`](../../001-app-frame/contracts/web-api.md). Shapes reference `../data-model.md` or the
spec named. "PR n" is this spec's PR in `../tasks.md`; "NNN/PR n" is another spec's.

## Notes

| Method, path | Body | Reply | hubd op | PR |
|---|---|---|---|---|
| `POST /api/notes/find` | unchanged (POST keeps words out of addresses) | rows add `topic`, `date` when the tool gives them | `notes.find` | PR 1 |
| `GET /api/notes/totals` | — | `{by_label: {…}, by_topic: {…}, source: "stats"\|"last-search"}` | `notes.totals` (new; R1) | PR 1 |
| `POST /api/notes/apply` | `{result, indexes}` | `{ops: [{state, command, said}]}` | `notes.apply` (new, login only) | PR 1 |
