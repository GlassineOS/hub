# Contract: hubd socket, login gate and shared ops (internal)

One JSON line per request and reply on the unix socket (`hubd/server.py:1-12`). Owned, internal,
ships with the app. Every op below that acts for the person sits behind the login check at
`hubd/server.py:200-216`, which today covers ops starting `agent.`, `ask.`, `work.`, `decision.`,
`notes.` and the shell ops. **New prefixes `interaction.`, `result.` and `usage.` are added to that
tuple**, so a token can't reach them. Token ops (tool server) are listed separately.
Each spec lists its ops in its own `contracts/hubd-socket.md`.

## Login ops (the page)

| Op | Request | Reply | Notes |
|---|---|---|---|
| `usage.status` **new** | `{token}` | usage reading (data-model) | reads `status.json` files |
| `ping` | — | adds `socket` (the address the app shows) | |

Unchanged and reused: `ask.list`/`ask.answer`, `decision.*`, `work.plan|approve|dismiss|cancel|claim|filed|hand|discard|bring_back`,
`agent.press|interrupt|state|resume|resume_past|past_search|past_transcript|cleanup_remove|steward|buttons|draft|manifest`,
`device.status`, `decision.holding`, `notes.status|find`, `shell.new|kill|attach`.
