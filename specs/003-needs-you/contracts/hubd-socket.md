# Contract: hubd socket ops for Needs you (internal)

One JSON line per request and reply on the unix socket. The login gate and its prefixes are in
[001 `contracts/hubd-socket.md`](../../001-app-frame/contracts/hubd-socket.md).

## Login ops (the page)

| Op | Request | Reply | Notes |
|---|---|---|---|
| `interaction.list` **new** | `{token, session?}` | `{items, counts, grants}` | projection, `research.md` R1 |
| `interaction.answer` **new** | `{token, id, verdict, where, …}` | `{item}` | dispatches by id prefix to `ask.answer`, `decision.approve\|deny\|end`, `work.dismiss`, `result.apply\|dismiss\|keep`; records `handled.by` = the login's user |
