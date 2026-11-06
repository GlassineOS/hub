# SPDX-License-Identifier: GPL-2.0-or-later
"""hubd: the only part of the hub with rights on the host.

Listens on a Unix socket that is bind-mounted into the app's container. One request per
connection, as a line of JSON, answered by a line of JSON; a shell attach then turns the
connection into frames (see shells.py).

The socket alone gets the app gh within the policy. Shells need a session token, which
only comes from a login, so a process in the container can't open one by itself.
"""
from __future__ import annotations

import argparse
import asyncio
import faulthandler
import json
import logging
import os
import re
import signal
import sqlite3
import sys
import time
from pathlib import Path

from . import auth, decisions, devices, interactions, newwork, notes, results, usage
from . import feed as feedlib
from .agents import MAX_ALSO, MAX_NOTES, NOTES_TOOL, PLANNER_MODELS, RESULTS as RESULTS_WORDS, SCREENS, AgentError, Agents, Library, load_environment, screen_of, validate, with_also
from .apps import AppError, Apps, is_write
from .asks import GRANT_LIFE, MAX_INPUT, TOOL_PREFIX, AskError, Asks
from .ghpolicy import ORG, Refused, check, is_merge, merge_request
from .ghrun import Gh
from .shells import ShellError, Shells

log = logging.getLogger("hubd")
MAX_REQUEST = 1024 * 1024 * 8
REQUEST_TIMEOUT = 30
PAM_SERVICE = "glassine-hubd"


def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(base) / "glassine-hub"


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / "glassine-hub"


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME")
    return (Path(base) if base else Path.home() / ".local" / "state") / "glassine-hub"


TIDY_FIRST, TIDY_EVERY = 600, 6 * 3600  # seconds
PING_FIRST, PING_EVERY = 60, 30  # seconds: how often to look; the interval of a ping is its own setting
PUBLIC_KNOWN, PUBLIC_UNSURE = 600, 60  # seconds a repository's visibility is kept, when GitHub said and when it didn't
COPIES_EVERY = 1800  # seconds between refreshes of the repository copies
WORK_TOOL_OPS = {"work.offer": "plan_work", "work.suggest": "suggest_session", "work.submit": "submit_drafts", "work.handed": "new_work_drafts"}
STEWARD = "steward"
RESULT_TOOL_OPS = {"result.submit": "submit_result"}
NOTES_TOOL_OPS = {"notes_tool.find": "notes_find"}  # By a session's own token, only for an action about the notes (009 FR-006)
ITEM_OBJECTS = ("issue", "pr", "run")  # what a Launch's covered items can be (005 FR-011)
KIND_WORDS = {"issue": "an issue", "pr": "a pull request", "run": "a run", "repo": "a repository", "project": "the whole project",
              "knowledge": "a question", "notes": "the notes"}
_ITEM_REF_RE = re.compile(r"\.?[A-Za-z0-9_][A-Za-z0-9._-]{0,99}#[1-9][0-9]{0,9}")
REVIEW_EVENT = {"comment": "COMMENT", "request-changes": "REQUEST_CHANGES", "approve": "APPROVE"}
PLANNER_CHOOSES = ("effort", "brief", "docs_query", "docs", "steps")  # the model it suggests is planner_pick: you choose on its plan
PLANNER_GRACE = 10  # seconds, for its last tool call to get an answer
DECISION_TOOL_OPS = {"decision.check": "decision_check", "decision.use": "decision_check", "decision.request": "decision_request", "decision.end_go": "decision_end"}
# GitHub answered, and said no: the decision stands. Anything else that fails might have merged, so it's spent.
_GITHUB_REFUSED = re.compile(r"GraphQL:|not mergeable|merge conflict|status check|in draft|is a draft|rule violation", re.I)
_GITHUB_UNSURE = re.compile(r"something went wrong|timed? ?out|timeout", re.I)
_HEAD_MOVED = re.compile(r"head branch was modified", re.I)
_HEAD_RE = re.compile(r"[0-9a-f]{40}")
_VERSION_RE = re.compile(r"[0-9a-f]{16}")


def _edit_problem(name: str, tool_input) -> str | None:
    """Why an edit to an issue or comment isn't worth a card: what the tool would refuse anyway, said before it asks."""
    a = tool_input if isinstance(tool_input, dict) else {}
    text = lambda key: a.get(key) if isinstance(a.get(key), str) else None
    if name in ("edit_issue", "tick_item") and not (text("expected") and _VERSION_RE.fullmatch(text("expected"))):
        return "Name the version you read as expected: the `version` get_issue gave you, so this can't overwrite a change made since."
    if name == "edit_issue":
        if text("title") is None and text("body") is None:
            return "Give a title or a body to replace."
        if (text("body") is not None and not text("body").strip()) or (text("title") is not None and not text("title").strip()):
            return "A title or body can't be blanked. Edit what's wrong in it."
    if name == "edit_issue" and text("title"):
        try:  # the same check the gh command will meet: a title that looks like owner/repo, or a link outside the organization, fails it
            check(["issue", "edit", "1", "-R", f"{ORG}/hub", f"--title={text('title')}"])
        except Refused:
            return ("That title can't go through as written: one shaped like owner/repo (\"docs/search\") or starting with a link "
                    "outside the organization is refused. Reword it.")
    if name == "tick_item" and not (text("item") and text("item").strip()):
        return "Name the box by its text."
    if name == "tick_item" and "checked" in a and not isinstance(a["checked"], bool):
        return "checked is true to tick the box or false to untick it."
    if name == "edit_comment" and not (text("body") and text("body").strip()):
        return "A comment can't be blanked, and this tool never deletes one."
    return None


REPO_OPS = {"repos.request": "request_repository", "repos.files": "list_repo_files", "repos.read": "read_repo_file", "repos.map_overview": "map_overview",
            "repos.map_definition": "map_definition", "repos.map_usages": "map_usages", "repos.map_string": "map_string", "repos.search": "code_search"}
MAP_OPS = {"repos.map_overview": ("overview", None), "repos.map_definition": ("definition", "symbol"), "repos.map_usages": ("usages", "symbol"), "repos.map_string": ("string", "text")}
STARTED_OPS = {"started.list": "list_sessions", "started.running": "list_running_sessions", "started.summary": "session_summary", "started.spawn": "spawn_session",
               "started.message": "message_started_session", "started.message_any": "message_session"}


class Hubd:
    def __init__(self, gh: Gh, shells: Shells, sessions: auth.Sessions, agent_token: str,
                 authenticate=auth.pam_authenticate, pam_service: str = PAM_SERVICE, agents: Agents | None = None,
                 apps: Apps | None = None, work: newwork.NewWork | None = None, device_reports: devices.Devices | None = None,
                 decision_store: decisions.Decisions | None = None, notes_search: notes.Notes | None = None,
                 change_feed: feedlib.Feed | None = None, ping_seconds: float = feedlib.DEFAULT_PING,
                 usage_allowance: float | None = None, result_store: results.Results | None = None):
        self.results = result_store
        self.feed = change_feed
        self.socket_path: Path | None = None  # set by serve, for the header's "connected to" (001 FR-005)
        self.usage_allowance = usage_allowance  # HUBD_DAILY_USAGE_USD, for the usage meter when no rate limit is known
        self._visible: dict[str, tuple[bool, float]] = {}
        self.pings = feedlib.Pings(change_feed, agents, self.public_among, ping_seconds) if change_feed and agents else None
        self.asks = Asks()
        self.notes = notes_search
        self.devices = device_reports
        self.decisions = decision_store
        if decision_store and agents:
            decision_store.session_id_of = agents.session_id_of
        self.agents = agents
        self.work = work
        self._work_tasks: set[asyncio.Task] = set()  # or they could be collected mid-run
        self.apps = apps
        self.gh = gh
        self.shells = shells
        self.sessions = sessions
        self.agent_token = agent_token
        self.authenticate = authenticate
        self.pam_service = pam_service
        self._login = asyncio.Lock()

    async def login(self, req) -> dict:
        user, password = req.get("user"), req.get("password")
        if not isinstance(user, str) or not isinstance(password, str):
            return {"ok": False, "error": "user and password are required"}
        # One at a time, so the delay after a failure holds for parallel guesses too.
        async with self._login:
            wait = self.sessions.retry_after()
            if wait > 0:
                return {"ok": False, "error": "too many attempts", "retry_after": round(wait, 1)}
            good = user == self.sessions.own_user() and await asyncio.get_running_loop().run_in_executor(
                None, self.authenticate, user, password, self.pam_service)
            if not good:
                self.sessions.record_failure()
                log.warning("login failed for %r", user)
                return {"ok": False, "error": "login failed"}
        log.info("login: %s", user)
        return {"ok": True, "token": self.sessions.create(), "user": user}

    async def request(self, req: dict) -> dict:
        op = req.get("op")
        if op == "ping":
            return {"ok": True, "gh": self.gh.available(), "tmux": self.shells.available(),
                    "user": self.sessions.own_user(), "socket": str(self.socket_path) if self.socket_path else None}
        if op == "auth.login":
            return await self.login(req)
        if op == "auth.check":
            return {"ok": self.sessions.check(req.get("token")), "user": self.sessions.own_user()}
        if op == "auth.logout":
            self.sessions.revoke(req.get("token"))
            return {"ok": True}
        if op == "auth.check_agent":
            token = req.get("token")
            if isinstance(token, str) and auth.same(token, self.agent_token):
                return {"ok": True, "scope": {"session": None, "tools": None, "persona": None}}
            scope = self.agents.scope(token) if self.agents else None
            return {"ok": scope is not None, "scope": scope}
        if op in ("device.report", "device.status"):
            return self.device_request(op, req)
        if op == "decision.holding":  # "I've got the device": one read, with no token, so a take can ask it from anywhere
            return {"ok": True, **self.decisions.holding_view()} if self.decisions else {"ok": False, "error": "decisions aren't set up"}
        if op in DECISION_TOOL_OPS:
            return await self.decision_tool(op, req)
        if op == "feed.record":
            return self.feed_record(req)
        if op == "feed.changes":
            return await self.feed_changes(req)
        if op == "gh" and is_merge(req.get("argv")):
            reply = await self.merge(req)
            self._note_own(req, reply)
            return reply
        if op == "gh":
            token = await self._persona_token(req)
            reply = {"ok": True, **await self.gh.run(req.get("argv"), req.get("stdin"), req.get("timeout"), token)}
            self._note_own(req, reply)
            return reply
        if op == "gh.graphql":
            scope = self.agents.scope(req.get("agent_token")) if self.agents and self.apps and self.gh.is_mutation(req.get("name")) else None
            token = await self.apps.token(scope["persona"]) if scope else None
            return {"ok": True, **await self.gh.graphql(req.get("name"), req.get("variables"), token)}
        if op == "ask.grant_use":
            return self.grant_use(req)
        if op in WORK_TOOL_OPS:
            return await self.work_tool(op, req)
        if op in RESULT_TOOL_OPS:
            return self.result_tool(op, req)
        if op in NOTES_TOOL_OPS:
            return await self.notes_tool(req)
        if op in STARTED_OPS:
            return await self.started_request(op, req)
        if op in REPO_OPS:
            return await self.repo_request(op, req)
        if op in ("shell.list", "shell.new", "shell.kill") or op.startswith(("agent.", "ask.", "work.", "decision.", "notes.", "interaction.", "usage.", "result.")):
            if not self.sessions.check(req.get("token")):
                return {"ok": False, "error": "login required", "denied": True}
            if op.startswith("interaction."):
                return await self.interaction_request(op, req)
            if op.startswith("usage."):
                if op != "usage.status":
                    return {"ok": False, "error": f"unknown request: {op}"}
                return {"ok": True, **usage.status(self.agents.sessions if self.agents else None, self.usage_allowance)}
            if op == "ask.list":
                return {"ok": True, **self.asks.list()}
            if op == "ask.answer":
                return await self.ask_answer(req)
            if op.startswith("ask."):
                return {"ok": False, "error": f"unknown request: {op}"}
            if op.startswith("work."):
                return await self.work_request(op, req)
            if op.startswith("result."):
                return await self.result_request(op, req)
            if op.startswith("decision."):
                return await self.decision_request(op, req)
            if op.startswith("notes."):
                return await self.notes_request(op, req)
            if op.startswith("agent."):
                return await self.agent_request(op, req)
            if op == "shell.list":
                sessions = await self.shells.list()
                if self.agents:
                    await self.agents.refresh_prs([s["name"] for s in sessions])
                    for session in sessions:
                        session["agent"] = self.agents.describe(session["name"])
                    self._note_pr_results(sessions)
                return {"ok": True, "sessions": sessions}
            if op == "shell.new":
                # A stopped session keeps its name, or a plain shell could pass for it.
                if self.agents and self.agents.is_session(req.get("name")):
                    return {"ok": False, "error": f"a session named {req['name']} has stopped: resume or discard it first"}
                return {"ok": True, **await self.shells.new(req.get("name"), req.get("cwd"), req.get("command"))}
            try:
                await self.shells.kill(req.get("name"))
            except ShellError:
                # Its shell may already be gone, after a reboot say: what's left can still go.
                if not self.agents or any(s["name"] == req.get("name") for s in await self.shells.list()):
                    raise
            kept = await self.agents.forget(req.get("name"), discard=req.get("discard") is True, drop_ignored=req.get("drop_ignored") is True) if self.agents else None
            reply = {"ok": True, "kept": kept}
            if kept and req.get("discard") is True:
                reply["ignored"] = await self.agents.ignored_in(req.get("name"))
            return reply
        return {"ok": False, "error": f"unknown request: {op}"}

    # --- the change feed ---------------------------------------------------------------
    def feed_record(self, req: dict) -> dict:
        """From the work sync. Facts of a fixed shape; the feed refuses the rest."""
        if self.feed is None:
            return {"ok": False, "error": "the change feed isn't set up"}
        try:
            kept, refused = self.feed.record(req.get("events"))
        except feedlib.FeedError as e:
            return {"ok": False, "error": str(e)}
        except sqlite3.Error as e:
            log.exception("the change feed failed")
            return {"ok": False, "error": f"the change feed failed: {e}"}
        return {"ok": True, "kept": kept, "refused": refused}

    async def feed_changes(self, req: dict) -> dict:
        """A login sees all of it and moves no cursor. A session needs the tool on its list, and has its own cursor: what it
        may read is its own right to read private repositories, which decides the rows and the counts alike."""
        if self.feed is None:
            return {"ok": False, "error": "the change feed isn't set up"}
        if self.sessions.check(req.get("token")):
            session, all_repos = None, True
        else:
            scope = self._caller(req.get("agent_token"))
            if not self._lists(scope, "changes_since"):
                return {"ok": False, "refused": True, "denied": not req.get("agent_token"), "error": "this needs a login, or a session that has changes_since"}
            session, all_repos = scope["session"], scope.get("all_repos") is True
        limit = req.get("limit")
        try:
            cursor = feedlib.parse_cursor(req.get("cursor"))
            public = None if all_repos else await self.public_among(self.feed.repos())
            return {"ok": True, **self.feed.changes(session, cursor, limit if isinstance(limit, int) and not isinstance(limit, bool) else feedlib.DEFAULT_READ, public)}
        except feedlib.FeedError as e:
            return {"ok": False, "error": str(e)}
        except sqlite3.Error as e:
            log.exception("the change feed failed")
            return {"ok": False, "error": f"the change feed failed: {e}"}

    async def public_among(self, repos) -> set[str]:
        """The repositories GitHub says are public. One it can't say anything about is treated as private."""
        now = time.monotonic()
        found = set()
        for repo in sorted(repos):
            known = self._visible.get(repo)
            if known is None or known[1] < now:
                public = await self._is_public(repo)
                known = self._visible[repo] = (public, now + (PUBLIC_KNOWN if public is not None else PUBLIC_UNSURE))
            if known[0]:
                found.add(repo)
        return found

    async def _is_public(self, repo: str) -> bool | None:
        try:
            reply = await self.gh.run(["api", f"repos/{ORG}/{repo}"])
            return json.loads(reply["stdout"]).get("private") is False if reply["code"] == 0 else None
        except (Refused, ValueError, AttributeError, OSError):
            return None

    def _note_own(self, req: dict, reply: dict) -> None:
        """A session's write to an item, so that what changes in it soon after is marked as that session's own. Only once the
        write went through: one the policy refused, a card declined or gh failed changed nothing. This is bookkeeping, and
        whatever goes wrong in it mustn't turn a write that happened into an error."""
        try:
            if self.feed is None or not self.agents or not reply.get("ok") or reply.get("code") != 0 or not is_write(req.get("argv")):
                return
            scope = self.agents.scope(req.get("agent_token"))
            target = feedlib.target_of(req.get("argv"))
            if scope and scope.get("session") and target:
                self.feed.mark(scope["session"], *target)
        except Exception:
            log.exception("couldn't note a write")

    async def _persona_token(self, req: dict) -> str | None:
        """Who a write goes out as: the session behind the tool call says, by its own token."""
        if not self.agents or not self.apps or not is_write(req.get("argv")):
            return None
        scope = self.agents.scope(req.get("agent_token"))
        return await self.apps.token(scope["persona"]) if scope else None

    def grant_use(self, req: dict) -> dict:
        """For the tool server, before a tool this session has to ask about. Its own token says which session."""
        scope = self.agents.scope(req.get("agent_token")) if self.agents else None
        if not scope or req.get("tool") not in (scope.get("asks_first") or ()):
            return {"ok": False, "refused": True, "error": f"this session can't use {req.get('tool')}"}
        if not self.asks.use_grant(scope["session"], req["tool"], req.get("arguments")):
            return {"ok": False, "refused": True, "error": f"you weren't allowed to run {req['tool']} with these arguments"}
        return {"ok": True}

    async def _before_asking(self, scope: dict, tool, tool_input) -> str | None:
        """Why this isn't worth your time: said at once, and nothing comes up."""
        name = tool.removeprefix(TOOL_PREFIX) if isinstance(tool, str) else None
        if name not in (scope.get("asks_first") or ()):
            return None
        # A card has to show all of it, and this session has no terminal prompt to fall back on.
        if len(json.dumps(tool_input)) > MAX_INPUT:
            return f"That's over {MAX_INPUT} characters, too long to show on a card. Shorten it."
        if name == "merge_pr" and not (isinstance(tool_input, dict) and isinstance(tool_input.get("head"), str) and _HEAD_RE.fullmatch(tool_input["head"])):
            return "Name the head commit you checked, in full, as head, so the merge fails if it has moved."
        if name in ("edit_issue", "tick_item", "edit_comment") and (problem := _edit_problem(name, tool_input)):
            return problem
        if name == "message_session":
            arguments = tool_input if isinstance(tool_input, dict) else {}
            try:
                await self.agents.message_ready(scope["session"], arguments.get("name"), arguments.get("text"))
            except AgentError as e:
                return str(e)
            if self.agents.started_by(arguments["name"]) == scope["session"] and self.agents.reads_only(arguments["name"]):
                return "You started that session, and it only reads: use message_started_session, which doesn't ask."
        if name == "spawn_session":
            try:
                if self.agents.check_spawn(tool_input).get("access") == "full":
                    return "That's a full session, with the person's rights: only they can start it. Tell them which one."
                await self.agents.room_to_start()
            except AgentError as e:
                return str(e)
        return None

    async def started_request(self, op: str, req: dict) -> dict:
        """By a session's own token, if its list has the tool."""
        scope = self.agents.scope(req.get("agent_token")) if self.agents else None
        if not scope or STARTED_OPS[op] not in (scope.get("tools") or ()):
            return {"ok": False, "refused": True, "error": f"this session can't use {STARTED_OPS[op]}"}
        if op == "started.list":
            return {"ok": True, "sessions": await self.agents.started()}
        if op == "started.running":
            return {"ok": True, "sessions": await self.agents.running_sessions(scope["session"])}
        try:
            if op == "started.spawn":  # you allowed this call: the tool server checked before it got here
                return {"ok": True, **await self.agents.spawn(req.get("action"), req.get("repo"), req.get("number"), scope["session"])}
            if op == "started.message":  # no card: a session it started that only reads
                return {"ok": True, **await self.agents.message_from(scope["session"], req.get("name"), req.get("text"), True)}
            if op == "started.message_any":  # you allowed this call: the tool server checked before it got here
                return {"ok": True, **await self.agents.message_from(scope["session"], req.get("name"), req.get("text"), False)}
            return {"ok": True, **await self.agents.started_summary(req.get("name"))}
        except AgentError as e:
            return {"ok": False, "error": str(e)}

    # --- devices -----------------------------------------------------------------------
    def _caller(self, token) -> dict | None:
        """Whose tool token this is: a session's, or the general one a hub shell holds, which is no session."""
        if isinstance(token, str) and token and auth.same(token, self.agent_token):
            return {"session": None, "tools": None, "persona": None}
        return self.agents.scope(token) if self.agents else None

    def _lists(self, scope: dict | None, tool: str) -> bool:
        """Tools are by list. A session held to one, whatever it sends, has only what's on it."""
        return bool(scope) and (scope.get("tools") is None or tool in scope["tools"])

    def device_request(self, op: str, req: dict) -> dict:
        """A report needs no token, as anything on the socket could send one anyway, and it can only mislead.
        The view needs a login, or a token whose list has the tool."""
        if self.devices is None:
            return {"ok": False, "error": "device reports aren't set up"}
        try:
            if op == "device.report":
                self.devices.report(req.get("report"))
                return {"ok": True}
            if self.sessions.check(req.get("token")):
                return {"ok": True, **self.devices.status(req.get("device"))}
            if self._lists(self._caller(req.get("agent_token")), "device_status"):
                return {"ok": True, **self.devices.status(req.get("device"), for_agent=True)}
        except devices.DeviceError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": False, "refused": True, "denied": not req.get("agent_token"), "error": "this needs a login, or a session that has device_status"}

    # --- the person's decisions ---------------------------------------------------------
    async def _pr_now(self, repo: str, number: int) -> dict | None:
        """What GitHub says of a pull request right now, or None if it can't say."""
        reply = await self.gh.run(["pr", "view", str(number), "-R", f"{ORG}/{repo}", "--json", "state,headRefOid,baseRefName"])
        try:
            now = json.loads(reply["stdout"]) if reply["code"] == 0 else None
        except ValueError:
            now = None
        return now if isinstance(now, dict) else None

    async def _with_base(self, scope) -> dict:
        """A merge decision's base is the one GitHub says now, and its head has to be the head now."""
        if not isinstance(scope, dict) or not isinstance(scope.get("repo"), str) or not isinstance(scope.get("number"), int):
            raise decisions.DecisionError("a merge decision names a repository and a pull request's number")
        decisions.head_of(scope.get("head"))
        if not decisions._REPO_RE.fullmatch(scope["repo"]):
            raise decisions.DecisionError("a merge decision names a repository")
        now = await self._pr_now(scope["repo"], scope["number"])
        if now is None:
            raise decisions.DecisionError(f"GitHub can't say what {scope['repo']}#{scope['number']} is right now, so this can't bind its head and base. Try again")
        if now.get("state") != "OPEN":
            raise decisions.DecisionError(f"{scope['repo']}#{scope['number']} isn't open")
        if now.get("headRefOid") != scope["head"]:
            raise decisions.DecisionError(f"{scope['head'][:12]} isn't the head of {scope['repo']}#{scope['number']}: that's {str(now.get('headRefOid'))[:12]}")
        return {**scope, "base": now.get("baseRefName")}

    async def decision_tool(self, op: str, req: dict) -> dict:
        """By a session's own token, or the general one, which is no session and so matches only `any`. None of these
        makes a decision current. Tools are by list, so a locked session has none of them."""
        scope = self._caller(req.get("agent_token"))
        tool = DECISION_TOOL_OPS[op]
        if self.decisions is None:
            return {"ok": False, "error": "decisions aren't set up"}
        if not self._lists(scope, tool):
            return {"ok": False, "refused": True, "error": f"this session can't use {tool}"}
        session = scope["session"]
        try:
            if op == "decision.request":
                wanted = req.get("scope")
                if req.get("kind") == "merge":
                    wanted = await self._with_base(wanted)
                if isinstance(wanted, dict):  # whoever asks: not its to choose, and a shell has no session but `any`
                    wanted = {**wanted, "session": session or decisions.ANY}
                record = self.decisions.request(req.get("kind"), wanted, req.get("why"), session, req.get("ends"))
                return {"ok": True, "id": record["id"], "words": f"{record['id']} is waiting for the person, under Needs you in Sessions. It does nothing until they approve it."}
            if op == "decision.end_go":
                record = self.decisions.end_go(req.get("id"), req.get("why"), session or "a hub shell")
                return {"ok": True, "words": f"{record['id']} has ended."}
            return {"ok": True, **await self._decision_answer(op, req, session)}
        except decisions.DecisionError as e:
            return {"ok": False, "error": str(e)}

    async def _decision_answer(self, op: str, req: dict, session) -> dict:
        """Check, or check and spend a run. Answers in words, and a yes or no for a script."""
        kind, target = req.get("kind"), req.get("target")
        session_id = self.decisions.session_id_of(session) if session else None
        if kind == "go":
            answer, record = self.decisions.check_go(req.get("actions"), target, session, session_id, req.get("id"))
        elif kind == "merge":
            if op == "decision.use":
                raise decisions.DecisionError("a merge decision is spent by the merge, and nothing else")
            return await self._merge_check(target, session)
        else:
            raise decisions.DecisionError(f"a decision is one of {', '.join(decisions.KINDS)}")
        if op == "decision.use" and record is not None:
            return decisions.Decisions._yes(self.decisions.spend(record))  # its words count what's left now
        return answer

    async def _merge_check(self, target, session) -> dict:
        repo, number, head = decisions.merge_target(target)
        found = self.decisions.merges(repo, number, session)
        if not found:
            return decisions.Decisions._no(f"there's no current merge decision for {repo}#{number} that answers to this session")
        now = await self._pr_now(repo, number)
        answer = None
        for record in found:
            answer = self.decisions.merge_answer(record, now, head)
            if answer is None:
                return decisions.Decisions._yes(record)
        return answer

    async def decision_request(self, op: str, req: dict) -> dict:
        """Behind the login check: this is what records your word."""
        if self.decisions is None:
            return {"ok": False, "error": "decisions aren't set up"}
        try:
            if op == "decision.list":
                return {"ok": True, "decisions": self.decisions.list(), "holding": self.decisions.holding_view()}
            if op == "decision.add":
                scope = await self._with_base(req.get("scope")) if req.get("kind") == "merge" else req.get("scope")
                return {"ok": True, "decision": self.decisions.view(self.decisions.add(req.get("kind"), req.get("words"), scope, req.get("ends")))}
            if op == "decision.approve":
                record = self.decisions._get(req.get("id"))
                if record["kind"] == "merge" and self.decisions.current_state(record) == "requested":
                    now = await self._with_base(record["scope"])  # it may have moved while the card was up
                    if now["base"] != record["scope"].get("base"):
                        raise decisions.DecisionError(f"this card shows a merge into {record['scope'].get('base')}, and it now targets {now['base']}. Say no: the session can ask again")
                return {"ok": True, "decision": self.decisions.view(self.decisions.approve(req.get("id"), req.get("words"), req.get("scope"), req.get("ends")))}
            if op == "decision.deny":
                return {"ok": True, "decision": self.decisions.view(self.decisions.deny(req.get("id"), req.get("why")))}
            if op == "decision.end":
                return {"ok": True, "decision": self.decisions.view(self.decisions.end(req.get("id"), req.get("why")))}
            if op == "decision.have_device":
                return {"ok": True, "ended": self.decisions.have_device(), "holding": self.decisions.holding_view()}
            if op == "decision.done":
                self.decisions.done()
                return {"ok": True, "holding": self.decisions.holding_view()}
        except decisions.DecisionError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": False, "error": f"unknown request: {op}"}

    # --- notes -------------------------------------------------------------------------
    async def notes_request(self, op: str, req: dict) -> dict:
        """Behind the login check, with no token path: they never passed the scan, and a session can post."""
        if self.notes is None:
            return {"ok": False, "error": "notes aren't set up"}
        try:
            if op == "notes.status":
                return {"ok": True, **self.notes.status()}
            if op == "notes.find":
                return {"ok": True, **await self.notes.find(req.get("words"), req.get("limit"))}
            if op == "notes.totals":
                return {"ok": True, **await self.notes.totals()}
        except notes.NotesError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": False, "error": f"unknown request: {op}"}

    async def notes_tool(self, req: dict) -> dict:
        """notes_find by a session's own token: its list has the tool and its action, as it is now, is about the notes.
        The library lets only a locked action that reads and hands in list it, so the search has no way out but the result
        the person reads (SECURITY.md, Notes)."""
        scope = self.agents.scope(req.get("agent_token")) if self.agents else None
        agent = self.agents.describe(scope["session"]) if scope and scope.get("session") else None
        action = self.agents.library.actions.get(agent["action"]) if agent else None
        if self.notes is None or not scope or NOTES_TOOL not in (scope.get("tools") or ()) or not action \
                or action["object"] != "notes" or NOTES_TOOL not in action["hub_tools"]:
            return {"ok": False, "refused": True, "error": f"this session can't use {NOTES_TOOL}"}
        try:
            return {"ok": True, **await self.notes.find(req.get("words"), req.get("limit"))}
        except notes.NotesError as e:
            return {"ok": False, "error": str(e)}

    # --- merges ------------------------------------------------------------------------
    @staticmethod
    def _no_merge(words: str) -> dict:
        return {"ok": False, "refused": True, "error": words}

    async def merge(self, req: dict) -> dict:
        """Every `pr merge` comes here. A login, from the page, or a token with a decision for this head. check() only
        sees the arguments, so this is what knows who's asking."""
        argv = req.get("argv")
        check(argv)
        repo, number, head = merge_request(argv)
        record = None
        if self.sessions.check(req.get("token")):  # a click binds the head the page showed. A decision for it, whoever's, is used up by it
            found = self.decisions.merges(repo, number, None, everyone=True) if self.decisions else []
            record = next((r for r in found if r["scope"]["head"] == head), None)
        else:
            record = await self._merge_decision(req.get("agent_token"), repo, number, head)
            if isinstance(record, str):
                return self._no_merge(record)
        token = await self._persona_token(req)  # before the claim: an App that can't get a token merges nothing
        if record is not None:
            try:
                record = self.decisions.claim(record)
            except decisions.DecisionError as e:
                return self._no_merge(str(e))
        try:
            reply = await self.gh.run(argv, req.get("stdin"), req.get("timeout"), token)
            reply = await self._merge_outcome(record, reply, repo, number)
        except BaseException:
            if record is not None:  # so it can't stay `using`, where nobody can end it
                self.decisions.outcome_unknown(record, "the merge command didn't finish")
            raise
        return {"ok": True, **reply}

    async def _merge_decision(self, token, repo: str, number: int, head: str) -> dict | str:
        """The decision that lets this token merge this head, or why there's none."""
        scope = self._caller(token)
        if not self._lists(scope, "merge_pr"):
            return "A merge needs your login, on the page, or a session's token with a matching decision. This has neither."
        if self.decisions is None:
            return "Decisions aren't set up, so only a login can merge."
        session = scope["session"]
        found = self.decisions.merges(repo, number, session)
        if not found:
            # One way in per kind of session, and both end in the same merge decision, checked against the head here.
            how = ("Call merge_pr with this head, and the person's Allow on its card is the decision" if "merge_pr" in (scope.get("asks_first") or ())
                   else f"Ask with decision_request (kind merge, scope repo {repo}, number {number}, this head), the person approves it under Needs you in Sessions, and then call merge_pr")
            return f"There's no decision letting this session merge {repo}#{number}. {how}. A yes from before, or from another session, isn't one."
        now = await self._pr_now(repo, number)
        answer = None
        for record in found:
            answer = self.decisions.merge_answer(record, now, head)
            if answer is None:
                return record
        return answer["words"]

    async def _merge_outcome(self, record: dict | None, reply: dict, repo: str, number: int) -> dict:
        """What the decision records, if there was one. A merge GitHub refuses doesn't spend it, and one whose outcome isn't
        known does, and says so. One that went through is reported as that, even if gh then failed deleting the branch."""
        merged = reply["code"] == 0
        now = None
        if not merged:
            now = await self._pr_now(repo, number)
            merged = bool(now) and now.get("state") == "MERGED"
        if merged:
            if record is not None:
                self.decisions.merged(record)
            if self.decisions:
                self.decisions.pull_request_merged(repo, number)
            if reply["code"] != 0:
                log.warning("%s#%s merged, and gh then said: %s", repo, number, reply.get("stderr", "")[:200])
                return {**reply, "code": 0, "stderr": f"It merged, and gh then failed: {reply.get('stderr', '')}"}
            return reply
        if record is None:
            return reply
        said = f"{reply.get('stderr', '')}{reply.get('stdout', '')}"
        if _HEAD_MOVED.search(said):
            self.decisions.head_moved(record)
            return reply
        if _GITHUB_REFUSED.search(said) and not _GITHUB_UNSURE.search(said):
            self.decisions.not_merged(record)
            return {**reply, "stderr": f"{reply.get('stderr', '')}\nGitHub refused it, so decision {record['id']} still stands."}
        words = f"gh exited with {reply['code']}"
        self.decisions.outcome_unknown(record, words)
        return {**reply, "stderr": f"{reply.get('stderr', '')}\nWhether this merged isn't known ({words}), and decision {record['id']} is spent. Look at the pull request."}

    async def ask_answer(self, req: dict) -> dict:
        """A login, on a card. Allowing a `merge_pr` is your word on that head, so it's a merge decision too, and the
        tool call that follows can't merge without it. It lasts as long as the yes it came with."""
        ask = self.asks.waiting(req.get("id"))
        is_merge_card = bool(ask) and self.decisions and req.get("verdict") in ("allow", "always") and ask.tool == f"{TOOL_PREFIX}merge_pr" and not ask.too_long
        scope = None
        if is_merge_card:
            try:
                wanted = {k: ask.input.get(k) for k in ("repo", "number", "head")}
                if isinstance(wanted["repo"], str):  # the tool takes this form too, and its grant keeps the arguments as sent
                    wanted["repo"] = wanted["repo"].removeprefix(f"{ORG}/")
                scope = self.decisions.check_new("merge", {**await self._with_base(wanted), "session": ask.session})
            except decisions.DecisionError as e:  # the card stays up, to say no to
                return {"ok": False, "error": str(e)}
        answered = self.asks.answer(req.get("id"), req.get("verdict"), req.get("reason"), req.get("answers"))
        ask.handled = {"by": self.sessions.own_user(), "where": req.get("where"), "at": time.time()}
        answered["handled"] = ask.handled
        if scope:  # with nothing awaited since the answer, so this is on disk before the session hears
            self.decisions.add("merge", f"Allowed on {ask.session}'s card.", scope, {"hours": GRANT_LIFE / 3600})
        return {"ok": True, "ask": answered}

    # --- Needs you: one list over asks, decisions and new work ------------------------------
    def _interactions(self, session=None) -> dict:
        names = {a["session"] for a in self.asks.list()["open"]}
        records = self.decisions.list() if self.decisions else []
        work = self.work.list() if self.work else []
        handed = self.results.all() if self.results else []
        names |= {d.get("asked_by") for d in records} | {r.get("by") for r in work} | {r["session"] for r in handed}
        agents = {n: self.agents.describe(n) for n in names if self.agents and isinstance(n, str) and self.agents.is_session(n)}
        objects = {a["id"]: a["object"] for a in self.agents.library.actions.values()} if self.agents else {}
        return interactions.project(self.asks.list(), records, work, agents, objects, session, results=handed)

    def _interaction(self, item_id) -> dict | None:
        return next((r for r in [*self._interactions()["items"], *self._interactions()["grants"]] if r["id"] == item_id), None)

    async def interaction_request(self, op: str, req: dict) -> dict:
        """Behind the login check. A list, and answers that go to each source's own op: this adds no rule of its own."""
        if op == "interaction.list":
            session = req.get("session")
            if session is not None and not isinstance(session, str):
                return {"ok": False, "error": "a session is named by its name"}
            listed = self._interactions(session)
            return {"ok": True, **listed, "holding": self.decisions.holding_view() if self.decisions else None}
        if op != "interaction.answer":
            return {"ok": False, "error": f"unknown request: {op}"}
        item_id, verdict = req.get("id"), req.get("verdict")
        try:
            where = interactions.check_where(req.get("where"))
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        if not isinstance(item_id, str):
            return {"ok": False, "error": "no such interaction"}
        handled = {"by": self.sessions.own_user(), "where": where, "at": time.time()}
        if item_id.startswith("a:"):
            if verdict not in ("allow", "always", "deny", "answer"):
                return {"ok": False, "error": "a permission is allowed, always allowed or denied; a question is answered"}
            try:
                reply = await self.ask_answer({**req, "id": item_id[2:], "where": where})
            except AskError as e:
                return {"ok": False, "error": str(e)}
        elif item_id.startswith("d-"):
            if self.decisions is None:
                return {"ok": False, "error": "decisions aren't set up"}
            if verdict not in ("approve", "deny", "end"):  # no "always": a decision has its own end, and an eye test never stands for good
                return {"ok": False, "error": "a decision is approved, denied or ended"}
            reply = await self.decision_request(f"decision.{verdict}", {**req, "id": item_id, "why": req.get("why") or req.get("reason")})
            if reply["ok"]:
                self.decisions.mark_handled(item_id, handled)
        elif item_id.startswith("r-"):
            if verdict not in ("apply", "keep", "dismiss"):
                return {"ok": False, "error": "a result is applied, kept or set aside"}
            reply = await self.result_request(f"result.{verdict}", {**req, "id": item_id})
            if reply["ok"]:
                self.results.mark_handled(item_id, handled)
        elif item_id.startswith("w:"):
            if verdict != "dismiss":
                return {"ok": False, "error": "a suggestion is dismissed here; Launch… opens it"}
            reply = await self.work_request("work.dismiss", {"id": item_id[2:]})
            if reply["ok"]:
                self.work.move(reply["work"], reply["work"]["state"], handled=handled)
        else:
            return {"ok": False, "error": "no such interaction"}
        if not reply["ok"]:
            return reply
        return {"ok": True, "item": self._interaction(item_id)}

    # --- new work ----------------------------------------------------------------------
    async def repo_request(self, op: str, req: dict) -> dict:
        """By a session's own token, if its list has the tool. A full session has no list. The general token is a shell's, which has git."""
        scope = self.agents.scope(req.get("agent_token")) if self.agents else None
        if not scope or not (scope.get("tools") is None or REPO_OPS[op] in scope["tools"]):
            return {"ok": False, "refused": True, "error": f"this session can't use {REPO_OPS[op]}"}
        if op == "repos.request":
            return {"ok": True, **await self.agents.request_repository(scope["session"], req.get("repo"))}
        if op == "repos.files":
            return {"ok": True, **await self.agents.repo_files(req.get("repo"), req.get("path"), req.get("recursive"))}
        if op in MAP_OPS:
            # As for work_search: private repositories only when named, except for a session that reads the whole project. Here, by its token.
            tool, key = MAP_OPS[op]
            args = {key: req.get(key)} if key else {}
            return {"ok": True, **await self.agents.repo_map(tool, repo=req.get("repo"), everything=scope.get("all_repos") is True, **args)}
        if op == "repos.search":  # the same line as the map: by the session's token, so a request can't ask for more reach
            return {"ok": True, **await self.agents.code_search(req.get("query"), repo=req.get("repo"), path=req.get("path"), regex=req.get("regex", False),
                                                                 context=req.get("context", 1), everything=scope.get("all_repos") is True)}
        return {"ok": True, **await self.agents.repo_read(req.get("repo"), req.get("path"), req.get("start_line", 1), req.get("max_lines"))}

    def _launch_covers(self, action: dict, given, offered: dict | None) -> list[dict]:
        """A Launch's items, each with its kind (005 FR-009, FR-011): the action's object, or it says why it can't start there."""
        if given is None and offered and offered.get("covers"):  # a suggested session: its own items, which may cross repositories
            given = [dict(c) for c in offered["covers"]]
        elif given is None and offered and offered.get("number"):  # one suggested before covers were kept
            given = [{"kind": action["object"], "repo": offered["repo"], "number": n} for n in [offered["number"], *offered.get("also_numbers", ())]]
        if given is None:
            given = []
        if not isinstance(given, list) or len(given) > 1 + MAX_ALSO:
            raise AgentError(f"a Launch covers at most {1 + MAX_ALSO} items")
        covers = []
        for item in given:
            if not isinstance(item, dict) or set(item) != {"kind", "repo", "number"}:
                raise AgentError("each covered item is a kind, a repo and a number")
            ref = f"{item['repo']}#{item['number']}"
            if not isinstance(item["repo"], str) or not isinstance(item["number"], int) or isinstance(item["number"], bool) or not _ITEM_REF_RE.fullmatch(ref):
                raise AgentError(f"not an item: {ref}")
            if action["object"] not in ITEM_OBJECTS:
                raise AgentError(f"{action['title']} works on {KIND_WORDS[action['object']]}, not on an item like {ref}")
            if item["kind"] not in ITEM_OBJECTS:
                raise AgentError(f"{ref}: an item is an issue, a pull request or a run")
            if item["kind"] != action["object"]:  # 005 FR-011: implement on a run, triage on a pull request
                raise AgentError(f"{action['title']} works on {KIND_WORDS[action['object']]}, and {ref} is {KIND_WORDS[item['kind']]}, "
                                 "so it can't start there")
            covers.append({"kind": item["kind"], "repo": item["repo"], "number": item["number"]})
        if action["object"] in ITEM_OBJECTS and not covers:
            raise AgentError(f"{action['title']} works on {KIND_WORDS[action['object']]}: name it")
        return covers

    @staticmethod
    def _launch_from(given, offered: dict | None) -> dict | None:
        """Where Launch was opened (005 FR-001, FR-010): a claim of the page's, checked like an answer's where, shown as the origin."""
        if given is None:
            return (offered or {}).get("from") or ({"view": "Needs you", "ref": None} if offered else None)
        if not isinstance(given, dict) or set(given) - {"view", "ref"}:
            raise AgentError("from is a view and, if it was on one, an item")
        try:
            view = interactions.check_where(given.get("view"))
        except ValueError as e:
            raise AgentError(str(e)) from None
        ref = given.get("ref")
        if view is None or (ref is not None and not (isinstance(ref, str) and _ITEM_REF_RE.fullmatch(ref))):
            raise AgentError("from names the view, and an item as repo#number if any")
        return {"view": view, "ref": ref}

    def _work_fields(self, req: dict, offered: dict | None = None) -> dict:
        """The form, from you or from an agent's suggestion. The planner's request and the session's prompt come from these.
        Every Launch is one of these records (005 R1): new work on a repository, or work on items."""
        action = self.agents.library.action(req.get("action"))
        if action["object"] == "project":
            raise AgentError(f"{action['title']} isn't a kind of new work")
        covers = self._launch_covers(action, req.get("covers"), offered)
        fields = {"action": action["id"], "title": action["title"], "roadmap": action.get("roadmap") is True}
        if covers:
            first = covers[0]
            fields.update(repo=first["repo"], number=first["number"], covers=covers, repos=[],
                          also_numbers=[c["number"] for c in covers[1:] if c["repo"] == first["repo"]])
        else:
            repos = req.get("repos") or []
            if not isinstance(repos, list) or len(repos) > 1 + MAX_ALSO or len(set(map(str, repos))) != len(repos) or not all(
                    isinstance(r, str) and newwork._REPO_RE.fullmatch(r) and ".." not in r for r in repos):
                raise AgentError(f"repos is a list of at most {1 + MAX_ALSO} different repositories")
            fields.update(repo=req.get("repo") or (repos[0] if repos else None) or action.get("repo"), covers=[], repos=repos)
        for key, limit in (("notes", MAX_NOTES), ("describe", MAX_NOTES), ("paths", 500), ("why", newwork.MAX_WHY), ("context", 200)):
            value = req.get(key) or ""
            if not isinstance(value, str) or len(value) > limit:
                raise AgentError(f"{key} must be text of at most {limit} characters")
            fields[key] = value
        # Only what the form shows for this kind, or a suggestion could hide text in your notes.
        if action.get("asks_describe") is not True:
            fields["describe"] = ""
        if action.get("asks_paths") is not True:
            fields["paths"] = ""
        if offered and not req.get("why"):
            fields["why"] = offered.get("why") or ""
        if len(self._work_notes(fields)) > MAX_NOTES:
            raise AgentError(f"what to plan, the scope and the notes must fit in {MAX_NOTES} characters together")
        fields["pins"] = req.get("pins") or []
        fields["model"] = req.get("model") or action["models"][0]
        fields["driver"] = "steward" if req.get("driver") == "steward" else "you"
        fields["planner_model"] = req.get("planner_model") or None
        if fields["planner_model"] not in (None, *PLANNER_MODELS):
            raise AgentError(f"the planner runs on one of {', '.join(PLANNER_MODELS)}")
        fields["from"] = self._launch_from(req.get("from"), offered)
        fields["background"] = req.get("background") is True
        self._work_config(fields)  # says now if the repository or the items are no good
        return fields

    def _suggestion(self, req: dict) -> dict:
        """A full session you may start. It waits for you and starts nothing, so a suggestion's words reach a session only past your eyes."""
        if not (req.get("why") or "").strip():
            raise AgentError("say why, in a sentence: it's the first thing the person reads")
        action = self.agents.library.action(req.get("action"))
        if action.get("access") != "full" or action["object"] not in ("issue", "pr"):
            raise AgentError(f"{action['id']} isn't a full session on an issue or pull request: use spawn_session or plan_work")
        base = {**self.agents.defaults(action["id"], req.get("repo"), req.get("number")), "notes": req.get("notes") or ""}
        numbers = req.get("also_numbers") or []
        if not isinstance(numbers, list):
            raise AgentError("also_numbers must be a list")
        others = self._suggested_covers(req.get("covers"), base)
        if others:  # 005 contract: covers may cross repositories, and is then all that's sent: also_numbers comes from it
            first = {"repo": base["repo"], "number": base["number"]}
            items = [first, *(c for c in others if c["repo"] != first["repo"]), *({"repo": first["repo"], "number": n} for n in numbers)]
            items += [c for c in others if c not in items]
            config = {**{k: v for k, v in base.items() if k != "also_numbers"}, "covers": items}
        else:
            config = with_also(base, numbers)
        config = validate(self.agents.library, config)
        covers = [{"kind": action["object"], "repo": c["repo"], "number": c["number"]} for c in config["covers"]]
        return {"action": action["id"], "title": action["title"], "repo": config["repo"], "number": config["number"], "also_numbers": config["also_numbers"],
                "covers": covers, "why": req["why"].strip()[:300], "notes": config["notes"], "describe": "", "paths": "", "context": "", "pins": [],
                "model": config["model"], "roadmap": False, "driver": "steward"}

    @staticmethod
    def _suggested_covers(given, config: dict) -> list[dict]:
        """A suggestion's other items, as repo#N, at most five. The item it names is first anyway, so naming it again is no error."""
        if given is None:
            return []
        if not isinstance(given, list) or not all(isinstance(c, str) for c in given):
            raise AgentError("covers is a list of items as repo#N")
        others = []
        for ref in given:
            if not _ITEM_REF_RE.fullmatch(ref):
                raise AgentError(f"not an item: {ref[:120]} (write it as repo#N)")
            repo, number = ref.rsplit("#", 1)
            item = {"repo": repo, "number": int(number)}
            if item != {"repo": config["repo"], "number": config["number"]} and item not in others:
                others.append(item)
        if len(others) > MAX_ALSO:
            raise AgentError(f"a suggestion covers at most {1 + MAX_ALSO} items: this one and {MAX_ALSO} more")
        return others

    @staticmethod
    def _work_notes(fields: dict) -> str:
        notes = fields["notes"]
        if fields["describe"]:
            notes = f"What to plan:\n{fields['describe']}\n\n{notes}".strip()
        if fields["paths"]:
            notes = f"Scope: {fields['paths']}\n\n{notes}".strip()
        return notes

    def _work_config(self, fields: dict) -> dict:
        covers = fields.get("covers") or []
        config = self.agents.defaults(fields["action"], fields["repo"], fields.get("number") if covers else None)
        config = {**config, "model": fields["model"], "notes": self._work_notes(fields), "pins": fields["pins"]}
        if covers:
            config.pop("also_numbers", None)
            config["covers"] = [{"repo": c["repo"], "number": c["number"]} for c in covers]
        return validate(self.agents.library, config)

    def _tell_steward(self, record: dict, text: str) -> None:
        if record["by"] == STEWARD or record["driver"] == "steward":
            self.agents.tell(STEWARD, f"New work {record['id']} ({record['title']}, {record['repo']}): {text}")

    async def work_tool(self, op: str, req: dict) -> dict:
        """By a session's own token. A full session may suggest work; it doesn't plan or read drafts."""
        scope = self.agents.scope(req.get("agent_token")) if self.agents else None
        tool = WORK_TOOL_OPS[op]
        tools = scope.get("tools") if scope else ()
        allowed = self.work and scope and scope["session"] and (tool in (tools or ()) or (tools is None and op == "work.offer"))
        if not allowed:
            return {"ok": False, "refused": True, "error": f"this session can't use {tool}"}
        try:
            if op == "work.offer":
                if not (req.get("why") or "").strip():
                    raise AgentError("say why, in a sentence: it's the first thing the person reads")
                record = self.work.offer(scope["session"], self._work_fields({**req, "driver": "steward" if scope["session"] == STEWARD else "you"}))
                return {"ok": True, "id": record["id"]}
            if op == "work.suggest":
                record = self.work.offer(scope["session"], self._suggestion(req))
                return {"ok": True, "id": record["id"]}
            if op == "work.handed":
                return {"ok": True, "work": self.work.handed()}
            record = self.work.by_session(scope["session"], self.agents.session_id_of(scope["session"]))
            if record is None:
                return {"ok": False, "refused": True, "error": "this session isn't planning anything, or has handed in already"}
            self.work.move(record, "done", error=None, drafts=newwork.clean_drafts(req.get("drafts"), record["repo"]))
            self._tell_steward(record, f"the session handed in {len(record['drafts'])} drafts. They wait for the person.")
            self._keep(self._end_session(record["session"]))
            return {"ok": True, "handed_in": len(record["drafts"])}
        except (AgentError, newwork.WorkError) as e:
            return {"ok": False, "error": str(e)}

    def _keep(self, coroutine) -> None:
        task = asyncio.ensure_future(coroutine)
        self._work_tasks.add(task)
        task.add_done_callback(self._work_tasks.discard)

    async def _end_session(self, name: str, grace: float = PLANNER_GRACE) -> None:
        """Its work is in the record and its checkout was read-only, so nothing is lost by ending it.
        The wait lets the tool call that handed in get its answer first."""
        await asyncio.sleep(grace)
        try:
            await self.shells.kill(name)
        except ShellError:
            pass
        try:
            await self.agents.forget(name, discard=True)
        except AgentError as e:
            log.warning("leaving the planner %s: %s", name, e)

    async def _plan_work(self, record: dict, config: dict, planner_model=None) -> None:
        """The planner writes the spec. Nothing runs until you've read it and pressed Start."""
        try:
            planned = await self.agents.plan(config["action"], config["repo"], config.get("number"), config["notes"], config["pins"], planner_model=planner_model,
                                             also_numbers=config.get("also_numbers"), covers=config.get("covers") if record.get("v") == 2 else None)
        except (AgentError, ShellError, OSError) as e:
            if record["state"] == "planning":  # or you cancelled, and it stays set aside
                self.work.move(record, "failed", error=f"It didn't start: {e}")
            return
        if record["state"] != "planning":  # you cancelled while it was reading
            return
        chosen = {k: planned["config"][k] for k in PLANNER_CHOOSES if k in planned["config"]}
        self.work.move(record, "planned", spec={**config, **chosen}, planner_pick=planned["config"].get("model"),
                       planner_cost_usd=planned.get("planner_cost_usd"), plan={"steps": chosen.get("steps") or []})

    async def _start_planned(self, record: dict, config: dict) -> None:
        """You pressed Start on the plan, whoever suggested the work."""
        origin = {"launch": record["id"], "from": record.get("from"), "by": record.get("by")} if record.get("v") == 2 else None
        try:
            started = await self.agents.start(config, origin=origin)
        except Exception as e:  # whatever it was, the plan and your edits stay, to press Start again
            if not isinstance(e, (AgentError, ShellError, OSError)):
                log.exception("starting %s", record["id"])
            if record["state"] == "starting":
                self.work.move(record, "planned", error=f"It didn't start: {e}")
            return
        if record["state"] != "starting":  # you cancelled while it was starting
            await self._end_session(started["name"], 0)
            return
        self.work.forget_session(started["name"])  # an older run under that name, which it mustn't be taken for
        self._show(record, started["name"])
        hands_in = self.agents.library.actions.get(record.get("action"), {}).get("result") in results.HANDED_IN
        if record.get("number") and not hands_in:  # a session on an item that opens a pull request and hands in nothing
            self.work.move(record, "started", session=started["name"])
            self._tell_steward(record, f"the person started it as {started['name']}.")
            return
        self.work.move(record, "running", session=started["name"], session_id=self.agents.session_id_of(started["name"]))
        self._tell_steward(record, "the session started.")

    async def _work_rows(self) -> list[dict]:
        names = {s["name"] for s in await self.shells.list()}
        not_alive = ("Stopped", "Not started")  # Not started: a plain shell with that name, which isn't this session
        rows = self.work.list()
        # A run starting now may have this name already, and be what's alive under it.
        starting = {(r.get("action"), r["repo"]) for r in rows if r["state"] in ("planning", "starting")}
        for record in rows:
            same = record.get("session_id") in (None, self.agents.session_id_of(record["session"])) if record["session"] else False
            if record["state"] == "failed" and record["session"] in names and same and (record.get("action"), record["repo"]) not in starting:
                if (await self.agents.session_state(record["session"]))["state"] not in not_alive:  # resumed, or called failed too soon
                    self.work.move(record, "running", error=None)
                    self._tell_steward(record, "the session is running again.")
            elif record["state"] == "running" and (record.get("action"), record["repo"]) not in starting:
                gone = not same or record["session"] not in names or (await self.agents.session_state(record["session"]))["state"] in not_alive
                if gone:
                    what = "its result. Nothing was posted" if record.get("number") else "any drafts. Nothing was filed"
                    self.work.move(record, "failed", error=f"The session stopped without handing in {what}.")
                    self._tell_steward(record, "the session stopped without handing in.")
        return self.work.list()

    async def work_request(self, op: str, req: dict) -> dict:
        if self.agents is None or self.work is None:
            return {"ok": False, "error": "agent sessions aren't set up on this host"}
        try:
            if op == "work.list":
                templates = [{**{k: a.get(k) for k in ("id", "title", "summary", "ceiling", "models", "order", "repo")}, "persona": a["personas"][0],
                              "asks_paths": a.get("asks_paths") is True, "asks_describe": a.get("asks_describe") is True}
                             for a in self.agents.library.actions.values() if a["object"] == "repo"]
                return {"ok": True, "templates": sorted(templates, key=lambda t: t.get("order") or 99), "items": await self._work_rows()}
            if op == "work.start":
                offered = self.work.get(req["id"]) if req.get("id") else None
                if offered and offered["state"] not in ("offered", "planned"):  # planned: you went back, or asked for another plan
                    raise newwork.WorkError("that suggestion was already started or dismissed")
                fields = self._work_fields(req, offered)  # 005 FR-011: an item of the wrong kind is refused here, by name
                config = self._work_config(fields)
                if offered:
                    record = self.work.move(offered, "planning", **fields, v=2, error=None)
                else:
                    record = self.work.new({**fields, "by": "you"}, "planning")
                if self.agents.library.action(fields["action"]).get("plan", True) is False:  # nothing to plan: its plan is the defaults
                    self.work.move(record, "planned", spec=config, plan={"steps": []})
                else:
                    self._keep(self._plan_work(record, config, fields["planner_model"]))
                return {"ok": True, "work": record}
            record = self.work.get(req.get("id"))
            if op == "work.plan":  # a suggested session: its words reach a session only through a plan you've read
                if not record.get("number") or record["state"] not in ("offered", "planned", "failed"):
                    raise newwork.WorkError("that isn't a suggested session waiting to start")
                planner_model = req.get("planner_model") or None
                if planner_model not in (None, *PLANNER_MODELS):
                    raise AgentError(f"the planner runs on one of {', '.join(PLANNER_MODELS)}")
                config = validate(self.agents.library, with_also(
                    {**self.agents.defaults(record["action"], record["repo"], req.get("number") or record["number"]),
                     "model": record["model"], "notes": req.get("notes") or "", "pins": record["pins"]}, req.get("also_numbers") or []))
                self.work.move(record, "planning", number=config["number"], also_numbers=config["also_numbers"], notes=config["notes"],
                               planner_model=planner_model, error=None)
                self._keep(self._plan_work(record, config, planner_model))
                return {"ok": True, "work": record}
            if op == "work.approve":
                if record["state"] != "planned":
                    raise newwork.WorkError("there's no plan waiting to start")
                model = req.get("model") or record["model"]
                brief = record["spec"].get("brief", "") if req.get("brief") is None else req["brief"]
                config = validate(self.agents.library, {**record["spec"], "model": model, "brief": brief})
                self.work.move(record, "starting", model=model, spec=config, error=None)
                self._keep(self._start_planned(record, config))
                return {"ok": True, "work": record}
            if op == "work.background":  # 005 FR-008: the Launch leaves the page; its asks and result arrive in Needs you
                if not isinstance(req.get("on"), bool):
                    raise newwork.WorkError("on is true or false")
                self.work.move(record, record["state"], background=req["on"])
                if record.get("session"):
                    self._show(record, record["session"])
                return {"ok": True, "work": record}
            if op == "work.dismiss":
                if record["state"] in ("planning", "starting", "running"):
                    raise newwork.WorkError("it's still running: cancel it first")
                with_it = sum(d["state"] == "handed" for d in record["drafts"])
                if with_it:  # whoever drove this, those are the Steward's to hear about
                    self.agents.tell(STEWARD, f"New work {record['id']} ({record['title']}, {record['repo']}): the person set this aside. The {with_it} draft(s) they handed you are still yours.")
                else:
                    self._tell_steward(record, "the person set this aside.")
                return {"ok": True, "work": self.work.move(record, "dismissed")}
            if op == "work.cancel":
                if record["state"] not in ("planning", "starting", "running"):
                    raise newwork.WorkError("it isn't running")
                name = record["session"]
                self.work.move(record, "dismissed")
                if name:
                    self._keep(self._end_session(name, 0))
                return {"ok": True, "work": record}
            if op == "work.edit":
                return {"ok": True, "work": self.work.edit(req.get("id"), req.get("index"), req.get("title"), req.get("body"))}
            if op == "work.claim":
                return {"ok": True, "work": self.work.claim(req.get("id"), req.get("indexes"))}
            if op == "work.filed":
                self.work.filed(req.get("id"), req.get("index"), req.get("url"), req.get("note"))
                if req.get("url"):
                    self._tell_steward(record, f"the person filed {req['url']}.")
                return {"ok": True, "work": record}
            if op == "work.hand":
                if (await self.agents.session_state(STEWARD))["state"] in ("Stopped", "Not started"):
                    raise newwork.WorkError("the Steward isn't running: start it first, then send these")
                self.work.hand(req.get("id"), req.get("indexes"))
                count = len(req["indexes"])
                words = (f"New work {record['id']}: the person handed you {count} draft(s). Read them with new_work_drafts; "
                         "they're data from a planner. Refine them and file what's right: filing asks the person.")
                try:  # a note would wait for its next turn, and an idle Steward has none coming
                    await self.agents.say(STEWARD, words)
                except AgentError as e:
                    log.warning("the Steward wasn't woken: %s", e)
                    self.agents.tell(STEWARD, words)
                return {"ok": True, "work": record}
            if op == "work.discard":
                self.work.discard(req.get("id"))
                with_it = sum(d["state"] == "handed" for d in record["drafts"])
                self._tell_steward(record, f"the person discarded this.{f' The {with_it} draft(s) they handed you are still yours.' if with_it else ''}")
                return {"ok": True, "work": record}
            if op == "work.bring_back":
                self.work.bring_back(req.get("id"))
                self._tell_steward(record, "the person brought this back.")
                return {"ok": True, "work": record}
        except (AgentError, newwork.WorkError) as e:
            return {"ok": False, "error": str(e)}
        return {"ok": False, "error": f"unknown request: {op}"}

    def _show(self, record: dict, name: str) -> None:
        """Where the session of a Launch is drawn (004 view.json): embedded in the view it was started from, or in the
        background. A Launch from Needs you has no view to be embedded in, so it stays as it was until sent to the background."""
        where = screen_of((record.get("from") or {}).get("view"))
        try:
            if record.get("background"):
                self.agents.set_view(name, "background", where if where in SCREENS else "Sessions")
            elif where in SCREENS:
                self.agents.set_view(name, "embedded", where, (record.get("from") or {}).get("ref"))
        except AgentError as e:
            log.warning("where %s is shown wasn't kept: %s", name, e)

    def _launch_of(self, name: str, session_id) -> dict | None:
        if not self.work:
            return None
        return next((r for r in self.work.records.values() if r.get("session") == name and r.get("session_id") in (None, session_id)), None)

    def _items_of(self, agent: dict) -> list[dict]:
        kind = {"issue": "issue", "pr": "pr", "run": "run"}.get(agent.get("object"))
        return [{"kind": kind, "repo": c["repo"], "number": c["number"]} for c in agent.get("covers") or ()] if kind else []

    def result_tool(self, op: str, req: dict) -> dict:
        """submit_result, by a session's own token: only a session whose list has the tool, only its action's result type.
        A full session has no list, and its result is the pull request the hub finds, so it can't hand one in."""
        scope = self.agents.scope(req.get("agent_token")) if self.agents else None
        tool = RESULT_TOOL_OPS[op]
        if not self.results or not scope or not scope["session"] or tool not in (scope.get("tools") or ()):
            return {"ok": False, "refused": True, "error": f"this session can't use {tool}"}
        name = scope["session"]
        agent = self.agents.describe(name)
        action = self.agents.library.actions.get(agent["action"]) if agent else None
        if action is None or action["result"] != req.get("type"):
            what = RESULTS_WORDS.get(action["result"], action["result"]) if action else "nothing"
            return {"ok": False, "refused": True, "error": f"this session {what}: hand in that type, not {req.get('type')!r}"}
        session_id = self.agents.session_id_of(name)
        launch = self._launch_of(name, session_id)
        try:
            record = self.results.submit(req["type"], req.get("payload"), session=name, session_id=session_id, launch=launch and launch["id"],
                                         items=self._items_of(agent), action=action["id"], persona=scope.get("persona"))
        except results.ResultError as e:
            return {"ok": False, "error": str(e)}
        if launch:
            self.work.move(launch, "done" if launch["state"] in ("running", "started", "failed") else launch["state"], result=record["id"], error=None)
            self._tell_steward(launch, f"the session handed in its {record['type']} result. It waits for the person.")
        return {"ok": True, "id": record["id"]}

    def _note_pr_results(self, sessions: list[dict]) -> None:
        """005 FR-016: a session that ends in a pull request has it as its result. On an issue, once its branch has one; on a
        pull request, which it covers from the start, once Claude has ended there."""
        if not self.results:
            return
        for session in sessions:
            agent = session.get("agent")
            action = self.agents.library.actions.get(agent["action"]) if agent else None
            if not action or action["result"] != "pr" or not agent.get("prs") or (agent.get("object") == "pr" and not agent.get("ended")):
                continue
            session_id = self.agents.session_id_of(session["name"])
            launch = self._launch_of(session["name"], session_id)
            for pr in agent["prs"]:
                try:
                    self.results.note_pr(session=session["name"], session_id=session_id, launch=launch and launch["id"], items=self._items_of(agent),
                                         action=action["id"], persona=agent.get("persona"), repo=pr["repo"], number=pr["number"])
                except results.ResultError as e:
                    log.warning("no pr result for %s: %s", session["name"], e)

    async def result_request(self, op: str, req: dict) -> dict:
        """Behind the login check: the cards' results, and what a press does to them."""
        if self.results is None or self.agents is None:
            return {"ok": False, "error": "results aren't set up on this host"}
        try:
            if op == "result.list":
                kind, kept, session, after = req.get("type"), req.get("kept"), req.get("session"), req.get("after")
                if kind is not None and kind not in results.TYPES:
                    raise results.ResultError(f"a result is one of {', '.join(results.TYPES)}")
                if kept is not None and not isinstance(kept, bool):
                    raise results.ResultError("kept is true or false")
                if not all(v is None or isinstance(v, str) for v in (session, after)):
                    raise results.ResultError("session and after are names")
                return {"ok": True, "results": self.results.list(kind, kept, session, after)}
            record = self.results.get(req.get("id"))
            if op == "result.apply":
                return {"ok": True, "result": await self.apply_result(record, req.get("indexes"))}
            if op == "result.keep":
                return {"ok": True, "result": self.results.keep(record["id"], req.get("kept", True))}
            if op == "result.dismiss":
                self.results.dismiss(record["id"])
                self._settle_launch(record, "dismissed")
                return {"ok": True, "result": record}
        except (results.ResultError, AgentError, newwork.WorkError) as e:
            return {"ok": False, "error": str(e)}
        return {"ok": False, "error": f"unknown request: {op}"}

    def _settle_launch(self, record: dict, state: str) -> None:
        launch = self.work.records.get(record.get("launch")) if self.work and record.get("launch") else None
        if launch and launch["state"] == "done" and launch.get("result") == record["id"]:
            self.work.move(launch, state)

    async def apply_result(self, record: dict, indexes=None) -> dict:
        """A login's press. It writes only through the tools the producing action names for its result, as it is now, and as
        that persona's App when there is one, else as the person: so it can't do more than that session's action may."""
        action = self.agents.library.actions.get(record["action"]) or {}
        allowed = set(action.get("result_tools", ()))
        chosen = None
        if record["type"] == "labels":
            issues = record["payload"]["issues"]
            if indexes is None:
                indexes = list(range(len(issues)))
            if not isinstance(indexes, list) or not indexes or len(set(map(str, indexes))) != len(indexes) or not all(
                    isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(issues) for i in indexes):
                raise results.ResultError("choose at least one of its issues")
            chosen = [issues[i] for i in indexes]
            needed = {"label_issue"} if any(i["add"] or i["remove"] for i in chosen) else set()
            needed |= {"edit_issue"} if any(i["part_of"] for i in chosen) else set()
        elif record["type"] == "notes":
            ops = record["payload"]["ops"]
            open_ = [n for n, o in enumerate(ops) if o["state"] != "applied"]
            if indexes is None:
                indexes = open_
            if not isinstance(indexes, list) or not indexes or len(set(map(str, indexes))) != len(indexes) or not all(
                    isinstance(i, int) and not isinstance(i, bool) and i in open_ for i in indexes):
                raise results.ResultError("choose at least one operation that isn't applied yet")
            chosen = sorted(indexes)
            needed = {"notes_apply"}
        else:
            needed = set(results.APPLY_TOOLS.get(record["type"], ()))
        if needed - allowed:
            raise results.ResultError(f"{action.get('title') or record['action']} can't {'post a review' if record['type'] == 'comment' else 'write that'}: "
                                      f"its action doesn't name {', '.join(sorted(needed - allowed))} for its result")
        self.results.claim(record["id"])
        by = self.sessions.own_user()
        try:
            if record["type"] == "notes":  # the notes tool on this host: no App, no GitHub
                return self._settle_notes(record, chosen, await self._apply_notes(record, chosen), by)
            token = await self.apps.token(record["persona"]) if self.apps and record.get("persona") else None
            if record["type"] == "comment":
                note = await self._post_review(record, token)
            else:
                note = await self._set_labels(record, chosen, token)
        except (results.ResultError, AppError, Refused, OSError) as e:
            self.results.settle(record["id"], False, by, f"It didn't go out: {e}")
            raise results.ResultError(f"it didn't go out: {e}") from None
        self.results.settle(record["id"], True, by, note)
        self._settle_launch(record, "filed")
        return record

    async def _apply_notes(self, record: dict, chosen: list[int]) -> list[dict]:
        """009 FR-006: by a login only, the ops hubd cleaned when they were handed in, rebuilt from their fields."""
        if self.notes is None:
            raise results.ResultError("notes aren't set up on this host")
        try:
            ops = [notes.clean_op({k: v for k, v in record["payload"]["ops"][i].items() if k not in ("command", "state", "said")}) for i in chosen]
            return await self.notes.apply(ops)
        except (notes.NotesError, notes.OpError) as e:
            raise results.ResultError(str(e)) from None

    def _settle_notes(self, record: dict, chosen: list[int], done: list[dict], by) -> dict:
        for i, outcome in zip(chosen, done):
            record["payload"]["ops"][i].update(outcome)
        ops = record["payload"]["ops"]
        failed = next((o for o in ops if o["state"] == "failed"), None)
        if all(o["state"] == "applied" for o in ops):
            self.results.settle(record["id"], True, by, f"Applied {len(ops)} note operation{'s' if len(ops) != 1 else ''}.")
            self._settle_launch(record, "filed")
        else:
            left = sum(o["state"] != "applied" for o in ops)
            self.results.settle(record["id"], False, by, f"{'The notes tool refused one: ' + failed['said'] if failed else ''}"
                                f"{' ' if failed else ''}{left} still to apply.".strip())
        return record

    async def _post_review(self, record: dict, token) -> str:
        """005 FR-017: one review with its inline notes, by the named document, its text on stdin."""
        item = next((i for i in record["items"] if i["kind"] == "pr"), None)
        if item is None:
            raise results.ResultError("this result names no pull request to review")
        found = await self.gh.graphql("content_id", {"repo": item["repo"], "number": item["number"]})
        try:
            node = json.loads(found["stdout"])["data"]["repository"]["issueOrPullRequest"]["id"]
        except (ValueError, KeyError, TypeError):
            raise results.ResultError(f"GitHub didn't give {item['repo']}#{item['number']}: {found.get('stderr', '')[-300:]}") from None
        payload = record["payload"]
        reply = await self.gh.graphql("pr_review_add", {"pullRequestId": node, "body": payload["summary"], "event": REVIEW_EVENT[payload["event"]],
                                                        "threads": [dict(n) for n in payload["notes"]]}, token)
        try:
            answer = json.loads(reply["stdout"])
        except ValueError:
            answer = {}
        if reply.get("code") or answer.get("errors") or not answer.get("data"):
            words = "; ".join(e.get("message", "") for e in answer.get("errors") or ()) or reply.get("stderr", "")[-300:]
            raise results.ResultError(f"GitHub refused the review: {words}")
        url = ((answer["data"].get("addPullRequestReview") or {}).get("pullRequestReview") or {}).get("url")
        return f"Posted {url or 'the review'}."

    async def _set_labels(self, record: dict, chosen: list[dict], token) -> str:
        """005 FR-018: label_issue's own command per issue; a Part of line as edit_issue would add it, to an issue of the
        organization's own. One after another, each said, so a failure halfway says what went out."""
        done = []
        for issue in chosen:
            repo, number = issue["ref"].split("#")
            if issue["add"] or issue["remove"]:
                argv = ["issue", "edit", number, "-R", f"{ORG}/{repo}"]
                for label in issue["add"]:
                    argv += ["--add-label", label]
                for label in issue["remove"]:
                    argv += ["--remove-label", label]
                reply = await self.gh.run(argv, None, None, token)
                if reply["code"]:
                    raise results.ResultError(f"{issue['ref']}: {reply['stderr'].strip()[-300:]}" + (f" (done: {', '.join(done)})" if done else ""))
                done.append(f"labels on {issue['ref']}")
            if issue["part_of"]:
                done.append(await self._add_part_of(issue, repo, number, token))
        return "Applied: " + "; ".join(done) + "."

    async def _add_part_of(self, issue: dict, repo: str, number: str, token) -> str:
        row = await self.gh.run(["api", f"repos/{ORG}/{repo}/issues/{number}"])
        try:
            data = json.loads(row["stdout"])
        except ValueError:
            data = None
        if row["code"] or not isinstance(data, dict):
            raise results.ResultError(f"{issue['ref']}: GitHub didn't give the issue: {row['stderr'].strip()[-300:]}")
        if data.get("pull_request") or data.get("author_association") not in ("OWNER", "MEMBER"):
            return f"no Part of line on {issue['ref']}: it isn't an issue the organization wrote"
        line = f"Part of {ORG}/{issue['part_of']}"
        body = data.get("body") or ""
        if line in body.splitlines():
            return f"Part of was already on {issue['ref']}"
        reply = await self.gh.run(["issue", "edit", number, "-R", f"{ORG}/{repo}", "--body-file", "-"], f"{body.rstrip()}\n\n{line}\n".lstrip(), None, token)
        if reply["code"]:
            raise results.ResultError(f"{issue['ref']}: {reply['stderr'].strip()[-300:]}")
        return f"{line} on {issue['ref']}"

    async def ask_wait(self, req: dict, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """A session's hook, until the prompt is answered or goes. Its own token says which session it is.
        This holds the prompt; only ask.answer, with a login, settles it."""
        scope = self.agents.scope(req.get("agent_token")) if self.agents else None
        if not scope:
            await _reply(writer, {"ok": False, "refused": True, "error": "not a session's token"})
            return
        name = scope["session"]
        if req["op"] == "ask.moved":
            self.asks.moved_on(name, req.get("how"), req.get("tool"), req.get("input"))
            await _reply(writer, {"ok": True})
            return
        refused = await self._before_asking(scope, req.get("tool"), req.get("input"))
        if refused:
            await _reply(writer, {"ok": True, "output": {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": refused}}})
            return
        agent, wait = self.agents.asker(name, req.get("tool"))
        ask = self.asks.add(name, req.get("how"), req.get("tool"), req.get("input"), req.get("suggestions"), agent, wait)
        self.agents.mark_asking(name, True)
        gone = asyncio.ensure_future(reader.read(1))  # it sends nothing more, so this is the connection ending
        prompt_up = True  # unless we learn otherwise, as when hubd itself is stopping
        try:
            await asyncio.wait({gone, ask.future}, timeout=wait, return_when=asyncio.FIRST_COMPLETED)
            if ask.future.done():
                prompt_up = False
                await _reply(writer, {"ok": True, "output": ask.future.result()})
            elif gone.done():
                prompt_up = False
                ended = (await self.agents.session_state(name))["state"] == "Stopped"
                self.asks.close(ask, "stopped" if ended else "terminal")
            else:
                self.asks.close(ask, "timeout")
                await _reply(writer, {"ok": True, "output": None})
        finally:
            gone.cancel()
            self.asks.close(ask, "stopped")
            if not self.asks.has_open(name):
                self.agents.mark_asking(name, False, prompt_up)

    async def agent_request(self, op: str, req: dict) -> dict:
        if self.agents is None:
            return {"ok": False, "error": "agent sessions are not set up"}
        if op == "agent.repo_copies":
            return {"ok": True, "copies": self.agents.repo_copies()}
        if op == "agent.workspace":
            return {"ok": True, "workspace": await self.agents.workspace_status()}
        if op == "agent.stopped":
            return {"ok": True, "sessions": await self.agents.stopped()}
        if op == "agent.resume":
            return {"ok": True, **await self.agents.resume(req.get("name"))}
        if op == "agent.past":
            return {"ok": True, "sessions": await self.agents.past(req.get("persona"), req.get("repo"), req.get("outcome"))}
        if op == "agent.worktrees":
            return {"ok": True, "worktrees": self.agents.worktrees(req.get("repo"))}
        if op == "agent.past_transcript":
            return {"ok": True, **await self.agents.past_transcript(req.get("id"))}
        if op == "agent.past_search":
            return {"ok": True, **await self.agents.past_search(req.get("words"))}
        if op == "agent.resume_past":
            return {"ok": True, **await self.agents.resume_past(req.get("id"))}
        if op == "agent.cleanup":
            return {"ok": True, "rows": await self.agents.cleanup_scan(), "settings": self.agents.cleanup_settings(req.get("after_merge"))}
        if op == "agent.steward":
            return {"ok": True, **self.agents.steward_settings(req.get("model"))}
        if op == "agent.cleanup_remove":
            return {"ok": True, **await self.agents.cleanup_remove(req.get("ids"))}
        if op == "agent.actions":
            return {"ok": True, "actions": self.agents.actions(req.get("object"))}
        if op == "agent.action":
            return {"ok": True, "action": self.agents.action(req.get("action"))}
        if op == "agent.preview":
            return {"ok": True, **self.agents.preview(req.get("config"))}
        if op == "agent.manifest":
            return {"ok": True, "manifest": self.agents.manifest(req.get("name"))}
        if op == "agent.defaults":
            return {"ok": True, "config": self.agents.defaults(req.get("action"), req.get("repo"), req.get("number"))}
        if op == "agent.plan":
            return {"ok": True, **await self.agents.plan(req.get("action"), req.get("repo"), req.get("number"), req.get("notes"), req.get("pins"), planner_model=req.get("planner_model"))}
        if op == "agent.start":
            return {"ok": True, **await self.agents.start(req.get("config"))}
        if op == "agent.state":
            return {"ok": True, **await self.agents.session_state(req.get("name"))}
        if op == "agent.press":
            return {"ok": True, **await self.agents.press(req.get("name"), req.get("button"), req.get("kind"), req.get("selection"))}
        if op == "agent.interrupt":
            return {"ok": True, **await self.agents.interrupt(req.get("name"))}
        if op == "agent.say":
            # The maintainer's own words, typed in a SessionView (004 FR-008): only a login reaches here, the
            # text goes to tmux on stdin, and the session gets it as a plain user turn, the person's.
            try:
                interactions.check_where(req.get("where"))
            except ValueError as e:
                return {"ok": False, "error": str(e)}
            if not isinstance(req.get("text"), str):
                return {"ok": False, "error": "a message is text"}
            return {"ok": True, **await self.agents.say(req.get("name"), req["text"])}
        if op == "agent.view":
            return {"ok": True, **self.agents.set_view(req.get("name"), req.get("mode"), req.get("where"), req.get("ref"))}
        if op == "agent.context":
            return {"ok": True, **self.agents.set_context(req.get("name"), req.get("screen"), req.get("kind"), req.get("selection"))}
        if op == "agent.buttons":
            return {"ok": True, "buttons": self.agents.library.buttons()}
        if op == "agent.draft":
            return {"ok": True, **await self.agents.draft(req.get("kind"), req.get("object"), req.get("repo"), req.get("number"), req.get("thread"))}
        if op == "agent.run":
            return {"ok": True, **await self.agents.run(req.get("action"), req.get("repo"), req.get("number"), req.get("notes"), req.get("pins"))}
        return {"ok": False, "error": f"unknown request: {op}"}

    async def connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), REQUEST_TIMEOUT)
            if not line:
                return
            try:
                req = json.loads(line)
                if not isinstance(req, dict):
                    raise ValueError
            except ValueError:
                await _reply(writer, {"ok": False, "error": "not a JSON object"})
                return
            if req.get("op") == "shell.attach":
                if not self.sessions.check(req.get("token")):
                    await _reply(writer, {"ok": False, "error": "login required", "denied": True})
                    return
                if not any(s["name"] == req.get("name") for s in await self.shells.list()):
                    await _reply(writer, {"ok": False, "error": "no such session"})
                    return
                await _reply(writer, {"ok": True})
                await self.shells.attach(req.get("name"), reader, writer)
                return
            if req.get("op") in ("ask.wait", "ask.moved"):
                try:
                    await self.ask_wait(req, reader, writer)
                except AskError as e:
                    await _reply(writer, {"ok": False, "error": str(e)})
                return
            try:
                reply = await self.request(req)
            except Refused as e:
                log.warning("refused: %s", e)
                reply = {"ok": False, "refused": True, "error": str(e)}
            except (ShellError, AgentError, AppError, AskError) as e:
                reply = {"ok": False, "error": str(e)}
            await _reply(writer, reply)
        except (ConnectionError, asyncio.IncompleteReadError, TimeoutError):
            pass
        except Exception:
            log.exception("request failed")
            try:
                await _reply(writer, {"ok": False, "error": "internal error"})
            except ConnectionError:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass


async def _reply(writer: asyncio.StreamWriter, reply: dict) -> None:
    writer.write(json.dumps(reply).encode() + b"\n")
    await writer.drain()


async def _tidy(hubd: Hubd) -> None:
    """What may go on its own. Well after a start, so a restart doesn't hit GitHub or the disk at once."""
    await asyncio.sleep(TIDY_FIRST)
    while hubd.agents:
        try:
            await hubd.agents.cleanup_after_merge()
        except Exception:  # whatever it was, the next round may go better
            log.exception("cleanup didn't run")
        await asyncio.sleep(TIDY_EVERY)


async def _ping(hubd: Hubd) -> None:
    """The Stewards' pings: a count, when something they haven't read has changed, at most once an interval each."""
    await asyncio.sleep(PING_FIRST)
    while hubd.pings:
        try:
            await hubd.pings.round()
        except Exception:  # a fault in the feed mustn't stop the hub; the next round may go better
            log.exception("pings didn't run")
        await asyncio.sleep(PING_EVERY)


async def _keep_copies(hubd: Hubd) -> None:
    """The hub's copies of the organization's repositories. Failures are written down for the page, and the last good copy stands."""
    if not hubd.agents:
        return
    hubd.agents.seeds.auto = True
    await asyncio.sleep(TIDY_FIRST)
    while True:
        await hubd.agents.seeds.round()
        hubd.agents.maps.kick()  # also what's still unmapped when no copy moved
        await asyncio.sleep(COPIES_EVERY)


async def serve(hubd: Hubd, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    if path.exists():
        path.unlink()
    hubd.socket_path = path
    previous = os.umask(0o177)
    try:
        server = await asyncio.start_unix_server(hubd.connection, path=str(path), limit=MAX_REQUEST)
    finally:
        os.umask(previous)
    log.info("listening on %s", path)
    tidying = asyncio.ensure_future(_tidy(hubd))
    copying = asyncio.ensure_future(_keep_copies(hubd))
    pinging = asyncio.ensure_future(_ping(hubd))
    try:
        async with server:
            await server.serve_forever()
    finally:
        tidying.cancel()
        copying.cancel()
        pinging.cancel()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="hubd", description="The GlassineOS hub's host daemon.")
    p.add_argument("--socket", type=Path, default=runtime_dir() / "hubd.sock")
    p.add_argument("--pam-service", default=os.environ.get("HUBD_PAM_SERVICE", PAM_SERVICE))
    p.add_argument("--agent-url", default=os.environ.get("HUBD_AGENT_URL", "http://127.0.0.1:9095/mcp"),
                   help="the tool server's address, passed to hub shells")
    p.add_argument("--cwd", default=os.environ.get("HUBD_SHELL_CWD"), help="where new shells start")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    # systemctl --user kill -s USR1 glassine-hubd: the stacks, in its journal.
    faulthandler.enable(all_threads=True)
    faulthandler.register(signal.SIGUSR1, all_threads=True)
    if os.getuid() == 0:
        print("hubd: run this as your own user, not root", file=sys.stderr)
        return 1
    if not Path("/etc/pam.d", a.pam_service).exists():
        log.warning("no /etc/pam.d/%s: logins will fail until deploy/glassine-hubd.pam is installed", a.pam_service)
    agent_token = auth.load_agent_token(config_dir() / "agent-token")

    async def run():
        # agents.env says which Claude Code and which login: a service doesn't get your shell's setup.
        keep = load_environment(config_dir() / "agents.env")
        claude = keep.pop("HUBD_CLAUDE", os.environ.get("HUBD_CLAUDE", "claude"))
        workspace = keep.pop("HUBD_WORKSPACE", os.environ.get("HUBD_WORKSPACE"))
        ping_setting = keep.pop("HUBD_PING_SECONDS", os.environ.get("HUBD_PING_SECONDS"))
        allowance = usage.allowance_of(keep.pop("HUBD_DAILY_USAGE_USD", os.environ.get("HUBD_DAILY_USAGE_USD")))
        # From before agents.env, until install.sh has moved it there.
        if "CLAUDE_CONFIG_DIR" in os.environ:
            keep.setdefault("CLAUDE_CONFIG_DIR", os.environ["CLAUDE_CONFIG_DIR"])
        shells = Shells(env={**keep, "GLASSINE_HUB_MCP_URL": a.agent_url, "GLASSINE_HUB_MCP_TOKEN": agent_token},
                        default_cwd=a.cwd)
        gh = Gh()
        apps = Apps(config_dir() / "apps.toml")
        agents = Agents(Library(Path(__file__).resolve().parents[1] / "agents"), shells, state_dir(), gh=gh, apps=apps,
                        claude=claude, mcp_url=a.agent_url, socket=a.socket,
                        agent_token=agent_token, environment=keep,
                        workspace=Path(workspace or Path.home() / "GlassineOS").expanduser().resolve())
        try:
            change_feed = feedlib.Feed(state_dir() / "feed.sqlite")
        except (sqlite3.Error, OSError):  # the hub works without it: no pings, and the tool says so
            log.exception("no change feed")
            change_feed = None
        hubd = Hubd(gh, shells, auth.Sessions(), agent_token, pam_service=a.pam_service, agents=agents, apps=apps,
                    change_feed=change_feed, ping_seconds=feedlib.ping_interval(ping_setting), usage_allowance=allowance,
                    work=newwork.NewWork(state_dir() / "newwork"), result_store=results.Results(state_dir() / "results"), device_reports=devices.Devices(state_dir() / "devices"),
                    decision_store=decisions.Decisions(state_dir() / "decisions"), notes_search=notes.Notes(agents.workspace))
        await serve(hubd, a.socket)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
