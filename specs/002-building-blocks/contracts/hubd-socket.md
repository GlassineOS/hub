# Contract: hubd socket ops for Building blocks (internal)

One JSON line per request and reply on the unix socket. The login gate and its prefixes are in
[001 `contracts/hubd-socket.md`](../../001-app-frame/contracts/hubd-socket.md).

## Login ops (the page)

| Op | Request | Reply | Notes |
|---|---|---|---|
| `agent.actions` | `{token, object?}` | actions add `verb`, `result`, `family`, `persona_name` | |
