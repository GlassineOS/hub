# Contract: hubd socket ops for Notes (internal)

One JSON line per request and reply on the unix socket. The login gate and its prefixes are in
[001 `contracts/hubd-socket.md`](../../001-app-frame/contracts/hubd-socket.md).

## Login ops (the page)

| Op | Request | Reply | Notes |
|---|---|---|---|
| `notes.totals` **new** | `{token}` | `{by_label, by_topic, source}` | `notes stats --json` when the tool has it, else from the last search |
| `notes.apply` **new** | `{token, result, indexes}` | `{ops}` | closed op list → `notes add`/`notes set …`; words after `--`; same env and `-I` as `find` (`hubd/notes.py:107-131`) |
