# SPDX-License-Identifier: GPL-2.0-or-later
"""Runs the two listeners: the dashboard, and the tool server for agents.

The tool server has its own port so it stays on loopback and plain HTTP when the
dashboard goes on the LAN with TLS: agents run on the host, next to it.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path

import uvicorn
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import tools, web
from .docsearch import DocSearch
from .github import GitHub
from .hubd_client import ALL_REPOS, CALLER, DESIGN, INSTANCE, SEES, SESSION
from .hubd_client import Hubd, HubdError
from .watchdog import Requests, Watchdog, stack_dump_on_signal
from .workstore import WorkStore
from .worksync import Embedder, WorkSync

log = logging.getLogger("hub")
CONFIG = Path(os.environ.get("HUB_CONFIG", Path(__file__).resolve().parents[2] / "config" / "repos.toml"))


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class AgentAuth:
    """A bearer token checked by hubd. A session's token only reaches the tools its action lists."""

    def __init__(self, app, hubd: Hubd):
        self.app = app
        self.hubd = hubd

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope, receive)
        header = request.headers.get("authorization", "")
        token = header[7:] if header.lower().startswith("bearer ") else None
        try:
            reply = await self.hubd.call(op="auth.check_agent", token=token) if token else {"ok": False}
        except HubdError:
            reply = {"ok": False}
        if not reply["ok"]:
            return await JSONResponse({"error": "unauthorized"}, 401)(scope, receive, send)
        CALLER.set(token)
        session = (reply.get("scope") or {}).get("session")
        SESSION.set(session if isinstance(session, str) else None)
        instance = (reply.get("scope") or {}).get("instance")
        INSTANCE.set(instance if isinstance(instance, str) and instance else None)
        ALL_REPOS.set((reply.get("scope") or {}).get("all_repos") is True)
        DESIGN.set((reply.get("scope") or {}).get("design") is True)
        tools = (reply.get("scope") or {}).get("tools")
        SEES.set(tools)
        if tools is None:
            return await self.app(scope, receive, send)
        body = await request.body()
        refused = _outside(body, tools) or await self._not_allowed(body, token, (reply.get("scope") or {}).get("asks_first") or [])
        if refused:
            return await refused(scope, receive, send)

        await self.app(scope, _replaying(body, receive), send)


    async def _not_allowed(self, body: bytes, token: str, asks_first: list[str]) -> JSONResponse | None:
        """Claude Code's hook is what asks. This is what makes a yes necessary, whatever Claude Code does.
        The body has been through _outside, so it's JSON and its messages are objects."""
        if not body or not asks_first:
            return None
        parsed = json.loads(body)
        for message in parsed if isinstance(parsed, list) else [parsed]:
            params = message.get("params")
            if message.get("method") == "tools/call" and isinstance(params, dict) and params.get("name") in asks_first:
                try:
                    reply = await self.hubd.call(op="ask.grant_use", agent_token=token, tool=params["name"], arguments=params.get("arguments") or {})
                except HubdError as e:
                    reply = {"error": str(e)}
                if not reply.get("ok"):
                    return JSONResponse({"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32601, "message": reply.get("error") or "not allowed"}})
        return None


def _replaying(body: bytes, receive):
    """Gives the app the body that's already been read, once, and after that the real connection.

    The app waits on receive() for the client to disconnect. Answering at once and for ever would
    keep it in a loop that never yields, and stop everything on the event loop.
    """
    sent = False

    async def replay():
        nonlocal sent
        if sent:
            return await receive()
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}
    return replay


def _outside(body: bytes, tools: list[str]) -> JSONResponse | None:
    """The answer to a call this token may not make, if the request holds one."""
    if not body:
        return None
    try:
        parsed = json.loads(body)
    except ValueError:
        return JSONResponse({"error": "not JSON"}, 400)  # can't tell what it calls, so it doesn't pass
    for message in parsed if isinstance(parsed, list) else [parsed]:
        if not isinstance(message, dict):
            return JSONResponse({"error": "not a JSON-RPC message"}, 400)
        if message.get("method") != "tools/call":
            continue
        params = message.get("params")
        name = params.get("name") if isinstance(params, dict) else None
        if name not in tools:
            return JSONResponse({"jsonrpc": "2.0", "id": message.get("id"), "error": {
                "code": -32601, "message": f"this session doesn't have the tool {name}"}})
    return None


def agent_app(hubd: Hubd, github: GitHub, docs: DocSearch, port: int):
    hosts = [f"127.0.0.1:{port}", f"localhost:{port}", "127.0.0.1:*", "localhost:*"]
    security = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts,
                                         allowed_origins=[f"http://{h}" for h in hosts])
    app = tools.build(github, docs).streamable_http_app(stateless_http=True, json_response=True,
                                                        transport_security=security)
    app.add_middleware(AgentAuth, hubd=hubd)
    return app


async def run() -> int:
    socket_path = os.environ.get("HUB_HUBD_SOCKET", "/run/hubd/hubd.sock")
    bind = os.environ.get("HUB_BIND", "127.0.0.1")
    # In the container this is 0.0.0.0 and compose decides what's published. Outside, it's HUB_BIND.
    listen = os.environ.get("HUB_LISTEN") or bind
    port = int(os.environ.get("HUB_PORT", "9094"))
    agent_port = int(os.environ.get("HUB_AGENT_PORT", "9095"))
    cert, key = os.environ.get("HUB_TLS_CERT"), os.environ.get("HUB_TLS_KEY")
    tls = bool(cert and key)
    if not tls and not _is_loopback(bind):
        print(f"hub: refusing to serve {bind} without TLS: passwords and a host shell would cross the "
              "network in clear. Set HUB_TLS_CERT and HUB_TLS_KEY, or HUB_BIND=127.0.0.1.", file=sys.stderr)
        return 2
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"{bind}:{port}"}
    hosts.update(h.strip().lower() for h in os.environ.get("HUB_ALLOWED_HOSTS", "").split(",") if h.strip())
    hubd = Hubd(socket_path)
    cache = Path(os.environ["HUB_CACHE"]) if os.environ.get("HUB_CACHE") else None
    # In a directory of its own: the docs search manages what's in its cache by itself.
    store = None
    if cache:
        try:
            store = WorkStore(cache / "work" / "work.sqlite")
        except (sqlite3.Error, OSError):  # it's only a cache: everything still works by asking gh
            log.exception("no work store")
    github = GitHub(hubd, CONFIG, store=store)
    if store:
        embed = os.environ.get("HUB_WORK_EMBED", "on") != "off"
        github.sync = WorkSync(hubd, github, store, load_embedder=(lambda: Embedder(cache)) if embed else None)
    docs = DocSearch(github, cache=cache)
    pages = Requests(web.build(hubd, github, docs, secure_cookie=tls, allowed_hosts=hosts), "web")
    tools = Requests(agent_app(hubd, github, docs, agent_port), "tools")
    servers = [
        uvicorn.Server(uvicorn.Config(pages, host=listen, port=port,
                                      ssl_certfile=cert, ssl_keyfile=key, log_level="info", proxy_headers=False,
                                      ws_max_size=1024 * 1024)),
        uvicorn.Server(uvicorn.Config(tools, host=listen, port=agent_port,
                                      log_level="warning", proxy_headers=False)),
    ]
    for server in servers:
        server.install_signal_handlers = lambda: None
    web.redact_access_log()  # the Configs above have set up uvicorn's loggers by now
    watchdog = Watchdog([pages, tools])
    watchers = [asyncio.create_task(docs.watch()), watchdog.start()]
    if github.sync:
        watchers.append(asyncio.create_task(github.sync.watch()))
    try:
        await asyncio.gather(*(s.serve() for s in servers))
    finally:
        watchdog.stop()
        for watcher in watchers:
            watcher.cancel()
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    stack_dump_on_signal()
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
