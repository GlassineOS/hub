# Contract: hubd socket ops for Work (internal)

One JSON line per request and reply on the unix socket. The login gate and its prefixes are in
[001 `contracts/hubd-socket.md`](../../001-app-frame/contracts/hubd-socket.md).

## Merge (unchanged, cited for FR-010)

`op: "gh"` with `pr merge` goes through `Hubd.merge` (`server.py:535-562`): a login merges the head
the page showed; a token merges only under a merge decision for that head
(`_merge_decision`, `server.py:564-580`); `--match-head-commit` is required by the policy
(`ghpolicy.py:203-204`). Full sessions' own `gh` in their shell is a guard, not a limit
(`SECURITY.md` "Guards, not limits").
