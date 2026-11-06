# Contract: hubd socket ops for Steward (internal)

One JSON line per request and reply on the unix socket. The login gate and its prefixes are in
[001 `contracts/hubd-socket.md`](../../001-app-frame/contracts/hubd-socket.md).

## Login ops (the page)

| Op | Request | Reply | Notes |
|---|---|---|---|
| `agent.context` | `{token, name, screen, kind?, selection?, repos?}` | `{}` | `SCREENS` becomes `Overview, Roadmap, Work, Knowledge, Notes, Sessions, Queue` (drops `Docs`, `Device`, `Decisions`); adds `repos` (≤ 3 named, else a count) for SEES chips (FR-004) |
