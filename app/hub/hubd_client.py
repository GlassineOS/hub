# SPDX-License-Identifier: GPL-2.0-or-later
"""The app's way to the host: requests to hubd over its Unix socket."""
from __future__ import annotations

import asyncio
import contextvars
import json
import re
import struct

FRAME_DATA, FRAME_RESIZE, FRAME_EXIT = 0, 1, 2
HEADER = struct.Struct(">BI")
LIMIT = 64 * 1024 * 1024
# The tool token of the agent this request is for: hubd takes who it is from that, not from the app.
CALLER = contextvars.ContextVar("hub_caller", default=None)
# Whether the session behind a tool call may list private repositories without naming one.
ALL_REPOS = contextvars.ContextVar("hub_all_repos", default=False)
# What the calling session may call, if it's held to a list: what it gets to see.
SEES = contextvars.ContextVar("hub_sees", default=None)


class HubdError(Exception):
    def __init__(self, message: str, refused: bool = False, denied: bool = False):
        super().__init__(message)
        self.refused = refused
        self.denied = denied


class GhError(HubdError):
    """gh ran and failed."""


class Hubd:
    def __init__(self, path: str):
        self.path = path

    async def call(self, **request) -> dict:
        try:
            reader, writer = await asyncio.open_unix_connection(self.path, limit=LIMIT)
        except OSError as e:
            raise HubdError(f"hubd is not reachable: {e}") from e
        try:
            writer.write(json.dumps(request).encode() + b"\n")
            await writer.drain()
            line = await reader.readline()
        finally:
            writer.close()
        if not line:
            raise HubdError("hubd closed the connection")
        reply = json.loads(line)
        if not reply.get("ok"):
            raise HubdError(reply.get("error", "failed"), reply.get("refused", False), reply.get("denied", False))
        return reply

    async def gh(self, *argv: str, stdin: str | None = None, timeout: int | None = None, login: str | None = None) -> str:
        # login: a page's own token, for what hubd holds to a login. Only merges so far.
        reply = await self.call(op="gh", argv=list(argv), stdin=stdin, timeout=timeout, agent_token=CALLER.get(), token=login)
        if reply["code"] != 0:
            raise GhError((reply["stderr"] or reply["stdout"]).strip() or f"gh exited with {reply['code']}")
        return reply["stdout"]

    async def gh_json(self, *argv: str, **kw):
        out = await self.gh(*argv, **kw)
        return json.loads(out) if out.strip() else None

    async def gh_conditional(self, path: str, etag: str | None = None) -> dict:
        """A read that costs nothing when unchanged: {"status": 304}, or the status, ETag and body."""
        argv = ["api", "--include", *(["-H", f"If-None-Match: {etag}"] if etag else []), path]
        reply = await self.call(op="gh", argv=argv)
        parts = re.split(r"\r?\n\r?\n", reply["stdout"], maxsplit=1)
        head, body = parts[0], parts[1] if len(parts) > 1 else ""
        try:
            status = int(head.split(None, 2)[1])
        except (IndexError, ValueError):
            raise GhError(reply["stderr"].strip() or "gh returned no status") from None
        if status == 304:  # gh exits non-zero on it
            return {"status": 304}
        if reply["code"] != 0:
            raise GhError(reply["stderr"].strip() or f"gh exited with {reply['code']}")
        found = re.search(r"^etag:\s*(.+?)\s*$", head, re.I | re.M)
        return {"status": status, "etag": found.group(1) if found else None, "body": json.loads(body)}

    async def graphql(self, name: str, **variables) -> dict:
        reply = await self.call(op="gh.graphql", agent_token=CALLER.get(), name=name, variables=variables)
        # gh exits non-zero on GraphQL errors, and the errors are in the body.
        try:
            body = json.loads(reply["stdout"])
        except ValueError:
            raise GhError(reply["stderr"].strip() or "gh returned no JSON") from None
        errors = body.get("errors")
        if errors:
            raise GhError("; ".join(e.get("message", "GraphQL error") for e in errors))
        if reply["code"] != 0:
            raise GhError(reply["stderr"].strip() or f"gh exited with {reply['code']}")
        return body["data"]

    async def attach(self, token: str, name: str) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await asyncio.open_unix_connection(self.path, limit=LIMIT)
        writer.write(json.dumps({"op": "shell.attach", "token": token, "name": name}).encode() + b"\n")
        await writer.drain()
        reply = json.loads(await reader.readline() or b"{}")
        if not reply.get("ok"):
            writer.close()
            raise HubdError(reply.get("error", "attach failed"), denied=reply.get("denied", False))
        return reader, writer
