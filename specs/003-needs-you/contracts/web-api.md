# Contract: web API routes for Needs you (internal)

Owned, internal, unversioned: ships with the app (`app/hub/web.py`). Every route keeps the rules
in [001 `contracts/web-api.md`](../../001-app-frame/contracts/web-api.md). Shapes reference `../data-model.md` or the
spec named. "PR n" is this spec's PR in `../tasks.md`; "NNN/PR n" is another spec's.

## Interactions (Needs you)

| Method, path | Body / query | Reply | hubd op | PR |
|---|---|---|---|---|
| `GET /api/interactions` | `?session=` optional (FR-021) | `{items: [Interaction], counts: {pending, blocking, by_kind: {…}, longest_wait}, grants: [Interaction]}` | `interaction.list` (new) | PR 1 |
| `POST /api/interactions/{id}/answer` | `{verdict, reason?, answers?, words?, scope?, ends?, where}` | `{item: Interaction}` | `interaction.answer` (new, dispatches) | PR 1 |

`verdict` per kind: permission `allow|always|deny`; question `answer`; decision
`approve|deny|end`; suggestion `dismiss` (Launch… is a page action); result
`apply|dismiss|keep`. `GET /api/asks`, `/api/decisions`, `/api/new-work` stay for one release so a
page loaded before the deploy keeps working; the app stops using them in PR 1/7.
