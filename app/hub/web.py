# SPDX-License-Identifier: GPL-2.0-or-later
"""The web app: login, the JSON API behind the dashboard, and the terminal bridge."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from . import tools as tools_module
from .docsearch import DocSearch
from .github import BadRequest, GitHub
from .hubd_client import FRAME_DATA, FRAME_EXIT, FRAME_RESIZE, HEADER, Hubd, HubdError

log = logging.getLogger("hub.web")
COOKIE = "hub_session"
STATIC = Path(__file__).parent / "static"
CSP = ("default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


def _same_origin(headers) -> bool:
    origin = headers.get("origin")
    if not origin:
        return False
    return urlsplit(origin).netloc == headers.get("host")


class HostCheck:
    """Refuses other Host headers. Without this a rebound DNS name would count as same-origin."""

    def __init__(self, app, allowed: set[str]):
        self.app = app
        self.allowed = allowed

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            host = dict(scope["headers"]).get(b"host", b"").decode("latin-1").lower()
            if host not in self.allowed:
                if scope["type"] == "http":
                    await PlainTextResponse("unknown host", 421)(scope, receive, send)
                else:
                    await send({"type": "websocket.close", "code": 4403})
                return
        await self.app(scope, receive, send)


def build(hubd: Hubd, github: GitHub, docs: DocSearch, secure_cookie: bool, allowed_hosts: set[str]) -> Starlette:
    def page_error(e: Exception) -> JSONResponse:
        if isinstance(e, BadRequest):
            return JSONResponse({"error": str(e)}, 400)
        if isinstance(e, HubdError):
            status = 401 if e.denied else 403 if e.refused else 502
            return JSONResponse({"error": str(e), "refused": e.refused}, status)
        log.exception("request failed", exc_info=e)
        return JSONResponse({"error": "internal error"}, 500)

    def api(handler):
        """Login, same-origin for writes, JSON in and out, errors as JSON."""
        async def endpoint(request: Request) -> Response:
            token = request.cookies.get(COOKIE)
            try:
                if not token or not (await hubd.call(op="auth.check", token=token))["ok"]:
                    return JSONResponse({"error": "login required"}, 401)
            except HubdError:
                return JSONResponse({"error": "login required"}, 401)
            if request.method != "GET" and not _same_origin(request.headers):
                return JSONResponse({"error": "cross-origin request refused"}, 403)
            try:
                body = await request.json() if request.method in ("POST", "PUT") else {}
                if not isinstance(body, dict):
                    raise BadRequest("the body must be a JSON object")
                result = await handler(request, body, token)
            except (BadRequest, HubdError) as e:
                return page_error(e)
            except ValueError as e:
                return JSONResponse({"error": f"bad request: {e}"}, 400)
            except Exception as e:
                return page_error(e)
            if isinstance(result, Response):
                return result
            return JSONResponse(result)
        return endpoint

    def q(request: Request, *names: str) -> dict:
        return {n: request.query_params.get(n) or None for n in names}

    def p(request: Request, name: str) -> str:
        return request.path_params[name]

    # --- login -------------------------------------------------------------
    async def login(request: Request) -> Response:
        if not _same_origin(request.headers):
            return JSONResponse({"error": "cross-origin request refused"}, 403)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError
            reply = await hubd.call(op="auth.login", user=str(body.get("user", "")), password=str(body.get("password", "")))
        except ValueError:
            return JSONResponse({"error": "bad request"}, 400)
        except HubdError as e:
            return JSONResponse({"error": str(e)}, 401)
        response = JSONResponse({"user": reply["user"]})
        response.set_cookie(COOKIE, reply["token"], httponly=True, samesite="strict", secure=secure_cookie, path="/")
        return response

    async def logout(request: Request, _body, token) -> Response:
        await hubd.call(op="auth.logout", token=token)
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE, path="/")
        return response

    async def host_status(_request, _body, _token):
        reply = await hubd.call(op="ping")
        return {"user": reply["user"], "gh": reply["gh"], "tmux": reply["tmux"]}

    # --- overview and board --------------------------------------------------
    async def overview(request, _b, _t):
        return await github.overview(fresh=request.query_params.get("fresh") == "1")

    async def limits(_r, _b, _t):
        return await github.rate_limit()

    async def run_strips(_r, _b, _t):
        return await github.run_strips()

    async def project(_r, _b, _t):
        return await github.project()

    async def project_move(_r, b, _t):
        return await github.move_item(b.get("project"), b.get("item"), b.get("field"), b.get("option"))

    async def project_add(_r, b, _t):
        return await github.add_to_project(b.get("repo"), b.get("number"))

    async def workspace(_r, _b, token):
        return (await hubd.call(op="agent.workspace", token=token))["workspace"]

    # --- devices ----------------------------------------------------------------
    async def device(r, _b, token):
        reply = await hubd.call(op="device.status", token=token, device=r.query_params.get("device") or None)
        return {"devices": reply["devices"], "only": reply["only"]}

    async def repo_copies(_r, _b, token):
        return (await hubd.call(op="agent.repo_copies", token=token))["copies"]

    # --- the person's decisions ---------------------------------------------------
    async def decisions(_r, _b, token):
        reply = await hubd.call(op="decision.list", token=token)
        return {"decisions": reply["decisions"], "holding": reply["holding"]}

    async def decision_add(_r, b, token):
        return (await hubd.call(op="decision.add", token=token, kind=b.get("kind"), words=b.get("words"), scope=b.get("scope"), ends=b.get("ends")))["decision"]

    async def decision_move(r, b, token):
        move = p(r, "move")
        if move not in ("approve", "deny", "end"):
            raise BadRequest(f"can't {move} a decision")
        return (await hubd.call(op=f"decision.{move}", token=token, id=p(r, "id"), words=b.get("words"), scope=b.get("scope"), ends=b.get("ends"), why=b.get("why")))["decision"]

    async def device_holding(_r, b, token):
        if not isinstance(b.get("holding"), bool):
            raise BadRequest("holding is true or false")
        reply = await hubd.call(op="decision.have_device" if b["holding"] else "decision.done", token=token)
        return {"holding": reply["holding"], "ended": reply.get("ended", 0)}

    # --- the queue view: reads, and approving is decision_add on the page's own head ---------
    async def merge_queue(_r, _b, token):
        return github.merge_queue((await hubd.call(op="decision.list", token=token))["decisions"])

    # --- notes: the one query, by your login -------------------------------------
    async def notes_status(_r, _b, token):
        reply = await hubd.call(op="notes.status", token=token)
        return {"here": reply["here"], "says": reply["says"]}

    async def notes_find(_r, b, token):  # a POST, so what you look for stays out of addresses and logs
        reply = await hubd.call(op="notes.find", token=token, words=b.get("words"), limit=b.get("limit"))
        return {k: reply[k] for k in ("here", "says", "rows", "total", "warnings")}

    async def changes(r, _b, token):
        """The same feed, for you: all repositories, and no Steward's cursor moves."""
        return await github.changes_since(r.query_params.get("cursor"), int(r.query_params.get("limit") or 100), login=token)

    # --- the work store ---------------------------------------------------------
    async def work_status(_r, _b, _t):
        return github.work_status()

    async def work_sync(_r, _b, _t):
        return await github.work_sync_now()

    async def work_search(r, _b, _t):
        a = q(r, "kind", "repo", "state")
        return await github.work_search(r.query_params.get("q", ""), a["kind"], a["repo"], a["state"], int(r.query_params.get("k", 20)))

    # --- issues ----------------------------------------------------------------
    async def issues(r, _b, _t):
        a = q(r, "repo", "label", "assignee", "search")
        return await github.issues(a["repo"], r.query_params.get("state", "open"), a["label"], a["assignee"], a["search"])

    async def issue(r, _b, _t):
        # ?for=edit: the text and `version` an edit is made against, read from GitHub. The view asks GitHub nothing.
        if r.query_params.get("for") == "edit":
            return await github.agent_issue(p(r, "repo"), p(r, "n"))
        return await github.issue(p(r, "repo"), p(r, "n"))

    async def issue_create(r, b, _t):
        return await github.create_issue(p(r, "repo"), b.get("title"), b.get("body"), b.get("labels"), bool(b.get("roadmap")))

    async def issue_action(r, b, _t):
        repo, n, action = p(r, "repo"), p(r, "n"), p(r, "action")
        if action == "comment":
            return await github.comment_issue(repo, n, b.get("body"))
        if action == "close":
            return await github.close_issue(repo, n, b.get("reason", "completed"), b.get("comment"))
        if action == "reopen":
            return await github.reopen_issue(repo, n)
        if action == "labels":
            return await github.label_issue(repo, n, b.get("add"), b.get("remove"))
        if action == "edit":
            return await github.edit_issue(repo, n, b.get("expected"), b.get("title"), b.get("body"), b.get("reason"))
        if action == "tick":
            return await github.tick_item(repo, n, b.get("item"), b.get("expected"), b.get("checked", True))
        if action == "edit-comment":
            return await github.edit_comment(repo, n, b.get("comment_id"), b.get("body"))
        raise BadRequest(f"unknown action: {action}")

    # --- pull requests ---------------------------------------------------------
    async def prs(r, _b, _t):
        return await github.prs(r.query_params.get("repo") or None, r.query_params.get("state", "open"))

    async def pr(r, _b, _t):
        return await github.pr(p(r, "repo"), p(r, "n"))

    async def pr_diff(r, _b, _t):
        return PlainTextResponse(await github.pr_diff(p(r, "repo"), p(r, "n"), r.query_params.get("path")))

    async def pr_diff_summary(r, _b, _t):
        return PlainTextResponse(await github.pr_diff_summary(p(r, "repo"), p(r, "n"), r.query_params.get("path")))

    async def pr_threads(r, _b, _t):
        return await github.pr_threads(p(r, "repo"), p(r, "n"))

    async def pr_action(r, b, token):
        repo, n, action = p(r, "repo"), p(r, "n"), p(r, "action")
        if action == "comment":
            return await github.comment_pr(repo, n, b.get("body"))
        if action == "review":
            return await github.review_pr(repo, n, b.get("event"), b.get("body"))
        if action == "merge":
            return await github.merge_pr(repo, n, b.get("method", "squash"), bool(b.get("delete_branch")), b.get("head"), login=token)
        if action == "close":
            return await github.close_pr(repo, n, b.get("comment"))
        if action == "ready":
            return await github.ready_pr(repo, n)
        if action == "update-branch":
            return await github.update_pr_branch(repo, n)
        if action in ("resolve-thread", "reopen-thread"):
            return await github.resolve_thread(repo, n, b.get("thread"), action == "resolve-thread")
        if action == "reply-thread":
            return await github.reply_thread(repo, n, b.get("thread"), b.get("body"))
        raise BadRequest(f"unknown action: {action}")

    # --- actions ---------------------------------------------------------------
    async def runs(r, _b, _t):
        a = q(r, "repo", "status", "workflow", "branch")
        return await github.runs(a["repo"], a["status"], a["workflow"], a["branch"])

    async def run(r, _b, _t):
        return await github.run(p(r, "repo"), p(r, "id"))

    async def run_log(r, _b, _t):
        failed = r.query_params.get("all") != "1"
        return PlainTextResponse(await github.run_log(p(r, "repo"), p(r, "id"), failed))

    async def run_action(r, b, _t):
        repo, run_id, action = p(r, "repo"), p(r, "id"), p(r, "action")
        if action == "rerun":
            return await github.rerun(repo, run_id, b.get("failed_only", True))
        if action == "cancel":
            return await github.cancel_run(repo, run_id)
        raise BadRequest(f"unknown action: {action}")

    async def workflows(r, _b, _t):
        return await github.workflows(p(r, "repo"))

    async def dispatch(r, b, _t):
        return await github.dispatch(p(r, "repo"), p(r, "file"), b.get("ref", "main"), b.get("inputs"))

    # --- docs --------------------------------------------------------------------
    async def docs_search(r, _b, _t):
        return await docs.search(r.query_params.get("q", ""), int(r.query_params.get("k", 8)))

    async def docs_status(_r, _b, _t):
        return await docs.status()

    async def docs_reindex(_r, _b, _t):
        return await docs.reindex()

    # --- shells ------------------------------------------------------------------
    async def shells(_r, _b, token):
        return (await hubd.call(op="shell.list", token=token))["sessions"]

    async def shell_new(_r, b, token):
        return await hubd.call(op="shell.new", token=token, name=b.get("name"), cwd=b.get("cwd"), command=b.get("command"))

    async def shell_kill(r, _b, token):
        return await hubd.call(op="shell.kill", token=token, name=p(r, "name"), discard=r.query_params.get("discard") == "1", drop_ignored=r.query_params.get("drop_ignored") == "1")

    # --- agent sessions -----------------------------------------------------------
    # --- new work ---------------------------------------------------------------------
    async def new_work(_r, _b, token):
        reply = await hubd.call(op="work.list", token=token)
        reply.pop("ok", None)
        return reply

    async def new_work_start(_r, b, token):
        fields = {k: b.get(k) for k in ("id", "action", "repo", "notes", "describe", "paths", "why", "context", "pins", "model", "driver", "planner_model")}
        return await hubd.call(op="work.start", token=token, **fields)

    async def new_work_move(r, b, token):
        move = p(r, "move")
        if move == "file":
            return await github.file_drafts(token, p(r, "id"), b.get("indexes"))
        if move not in ("cancel", "dismiss", "discard", "hand", "bring_back", "approve", "plan"):
            raise BadRequest(f"can't {move} planned work")
        return await hubd.call(op=f"work.{move}", token=token, id=p(r, "id"), indexes=b.get("indexes"), model=b.get("model"), brief=b.get("brief"),
                                number=b.get("number"), also_numbers=b.get("also_numbers"), notes=b.get("notes"), planner_model=b.get("planner_model"))

    # --- what sessions ask ------------------------------------------------------------
    async def asks(_r, _b, token):
        reply = await hubd.call(op="ask.list", token=token)
        reply.pop("ok", None)
        return reply

    async def ask_answer(r, b, token):
        return (await hubd.call(op="ask.answer", token=token, id=p(r, "id"), verdict=b.get("verdict"), reason=b.get("reason"), answers=b.get("answers")))["ask"]

    async def agent_actions(r, _b, token):
        return (await hubd.call(op="agent.actions", token=token, object=r.query_params.get("object")))["actions"]

    async def agents_stopped(_r, _b, token):
        return (await hubd.call(op="agent.stopped", token=token))["sessions"]

    async def agent_step(r, b, token):
        op = p(r, "step")
        if op not in ("action", "defaults", "plan", "run", "start", "preview", "manifest", "resume", "draft", "state", "press", "interrupt", "context", "buttons", "steward", "past", "past_transcript", "past_search", "resume_past", "cleanup", "cleanup_remove"):
            raise BadRequest(f"unknown step: {op}")
        reply = await hubd.call(op=f"agent.{op}", token=token, **{k: b.get(k) for k in ("id", "words", "ids", "after_merge", "model", "planner_model", "action", "repo", "number", "config", "name", "notes", "pins", "kind", "object", "button", "screen", "selection", "thread") if k in b})
        reply.pop("ok", None)
        return reply

    async def attach(ws: WebSocket) -> None:
        # Browsers send cookies on cross-site WebSockets, so the origin check is essential.
        token = ws.cookies.get(COOKIE)
        if not _same_origin(ws.headers) or not token:
            await ws.close(4403)
            return
        try:
            reader, writer = await hubd.attach(token, ws.path_params["name"])
        except HubdError as e:
            await ws.accept()
            await ws.close(4401 if e.denied else 4404, str(e)[:100])
            return
        await ws.accept()

        async def from_host():
            while True:
                kind, length = HEADER.unpack(await reader.readexactly(HEADER.size))
                payload = await reader.readexactly(length)
                if kind == FRAME_DATA:
                    await ws.send_bytes(payload)
                elif kind == FRAME_EXIT:
                    return

        async def from_browser():
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    return
                if message.get("bytes") is not None:
                    writer.write(HEADER.pack(FRAME_DATA, len(message["bytes"])) + message["bytes"])
                elif message.get("text"):
                    size = json.dumps({"rows": int(json.loads(message["text"])["rows"]),
                                       "cols": int(json.loads(message["text"])["cols"])}).encode()
                    writer.write(HEADER.pack(FRAME_RESIZE, len(size)) + size)
                await writer.drain()

        tasks = [asyncio.create_task(from_host()), asyncio.create_task(from_browser())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            writer.close()
            try:
                await ws.close()
            except (RuntimeError, WebSocketDisconnect):
                pass

    routes = [
        Route("/api/login", login, methods=["POST"]),
        Route("/api/logout", api(logout), methods=["POST"]),
        Route("/api/host", api(host_status)),
        Route("/api/overview", api(overview)),
        Route("/api/limits", api(limits)),
        Route("/api/overview/runs", api(run_strips)),
        Route("/api/project", api(project)),
        Route("/api/project/move", api(project_move), methods=["POST"]),
        Route("/api/project/add", api(project_add), methods=["POST"]),
        Route("/api/issues", api(issues)),
        Route("/api/issues/{repo}", api(issue_create), methods=["POST"]),
        Route("/api/issues/{repo}/{n:int}", api(issue)),
        Route("/api/issues/{repo}/{n:int}/{action}", api(issue_action), methods=["POST"]),
        Route("/api/prs", api(prs)),
        Route("/api/prs/{repo}/{n:int}", api(pr)),
        Route("/api/prs/{repo}/{n:int}/diff", api(pr_diff)),
        Route("/api/prs/{repo}/{n:int}/diff-summary", api(pr_diff_summary)),
        Route("/api/prs/{repo}/{n:int}/threads", api(pr_threads)),
        Route("/api/prs/{repo}/{n:int}/{action}", api(pr_action), methods=["POST"]),
        Route("/api/runs", api(runs)),
        Route("/api/runs/{repo}/{id:int}", api(run)),
        Route("/api/runs/{repo}/{id:int}/log", api(run_log)),
        Route("/api/runs/{repo}/{id:int}/{action}", api(run_action), methods=["POST"]),
        Route("/api/workflows/{repo}", api(workflows)),
        Route("/api/workflows/{repo}/{file}/dispatch", api(dispatch), methods=["POST"]),
        Route("/api/workspace", api(workspace)),
        Route("/api/device", api(device)),
        Route("/api/device/holding", api(device_holding), methods=["POST"]),
        Route("/api/decisions", api(decisions)),
        Route("/api/decisions", api(decision_add), methods=["POST"]),
        Route("/api/decisions/{id}/{move}", api(decision_move), methods=["POST"]),
        Route("/api/queue", api(merge_queue)),
        Route("/api/notes", api(notes_status)),
        Route("/api/notes/find", api(notes_find), methods=["POST"]),
        Route("/api/repo-copies", api(repo_copies)),
        Route("/api/changes", api(changes)),
        Route("/api/work/status", api(work_status)),
        Route("/api/work/sync", api(work_sync), methods=["POST"]),
        Route("/api/work/search", api(work_search)),
        Route("/api/docs/search", api(docs_search)),
        Route("/api/docs/status", api(docs_status)),
        Route("/api/docs/reindex", api(docs_reindex), methods=["POST"]),
        Route("/api/agents/actions", api(agent_actions)),
        Route("/api/agents/stopped", api(agents_stopped)),
        Route("/api/new-work", api(new_work)),
        Route("/api/new-work", api(new_work_start), methods=["POST"]),
        Route("/api/new-work/{id}/{move}", api(new_work_move), methods=["POST"]),
        Route("/api/asks", api(asks)),
        Route("/api/asks/{id}/answer", api(ask_answer), methods=["POST"]),
        Route("/api/agents/{step}", api(agent_step), methods=["POST"]),
        Route("/api/shells", api(shells)),
        Route("/api/shells", api(shell_new), methods=["POST"]),
        Route("/api/shells/{name}", api(shell_kill), methods=["DELETE"]),
        WebSocketRoute("/api/shells/{name}/attach", attach),
        Mount("/", StaticFiles(directory=STATIC, html=True)),
    ]
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    return Starlette(routes=routes, middleware=[Middleware(HostCheck, allowed=allowed_hosts),
                                                Middleware(BaseHTTPMiddleware, dispatch=headers)])
