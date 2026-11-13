# SPDX-License-Identifier: GPL-2.0-or-later
"""The status line (spec 012, FR-025): with `status = true` in its workflow, a session's moves post one line to its pull
request, or its issue while it has none: "Workflow: now in <path> (<why>)".

- **Who posts it**: hubd, as the session's persona's GitHub App, and only so. A persona without an App, or whose App can't
  give a token, posts nothing: nothing goes out as the person's own login without them pressing a button.
- **One comment per item**: the first move posts it, and each later move edits that comment (through the comment's node
  id and the `comment_edit` document) while the target is the same item. Before an edit, the comment is read back: it must
  be on that issue or pull request and written by the persona's App now. If not (deleted, another item, another App
  after the persona changed), the kept id is forgotten and a new comment is posted. Posts are at most one a THROTTLE per
  session; edits aren't held.
- **What it says** is the definition's own words: the path of states, and the exit's question for a judge's move or the
  facts it requires, "by hand", "rolled back" or "moved back by the hub". Never a judge's evidence, never a transcript.
- **Moves come in bursts**: they are posted one at a time per session, and only the newest line of a burst goes out.

Standard library only, as hubd is.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import time

from . import machine
from .apps import AppError
from .ghpolicy import ORG, Refused
from .instances import MachineError

log = logging.getLogger("hubd.statusline")

FILE = "status-line.json"   # the comment the session's status line is in: {kind, repo, number, id, persona}
THROTTLE = 60.0             # seconds between two new comments of one session
MAX_REASON = 160            # characters of the reason, so it stays one line
_COMMENT_AT = re.compile(r"#issuecomment-([0-9]{1,15})\s*$")


def line(d: machine.Definition, to: str, result: dict) -> str:
    path = " › ".join(reversed(machine.ancestors(d, to)))
    by = result.get("by")
    if result.get("who") == "hub":
        why = "moved back by the hub: the move didn't take effect"
    elif by == "rollback":
        why = "rolled back by hand"
    elif by == "hand":
        why = "moved by hand"
    else:
        why = " ".join(str(result.get("why") or "confirmed").split())
    if len(why) > MAX_REASON:
        why = why[:MAX_REASON - 1] + "…"
    return f"Workflow: now in {path} ({why})"


class StatusLines:
    def __init__(self, agents, gh, apps=None, throttle: float = THROTTLE, clock=time.monotonic, sleep=asyncio.sleep):
        self.agents = agents
        self.gh = gh
        self.apps = apps
        self.throttle = throttle
        self._clock = clock
        self._sleep = sleep
        self._newest: dict[str, str] = {}    # session -> the line still to go out
        self._posted: dict[str, float] = {}  # session -> when its last new comment went out
        self._tasks: dict[str, asyncio.Task] = {}
        agents.machines.on_move(self.on_move)

    def on_move(self, name: str, result: dict) -> None:
        if not result.get("moved"):
            return
        try:
            _record, inst = self.agents.machines.load(name)
            d = inst.definition()
        except (MachineError, OSError):
            return
        if not d.status or len(d.states) == 1:
            return
        self._newest[name] = line(d, inst.state, result)
        if name in self._tasks:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            log.warning("%s: no event loop to post its status line on", name)
            return
        self._tasks[name] = loop.create_task(self._run(name))

    async def _run(self, name: str) -> None:
        try:
            while name in self._newest:
                text = self._newest.pop(name)
                try:
                    await self.post(name, text)
                except Exception:  # noqa: BLE001: a status line is a courtesy; the move stands either way
                    log.exception("%s: its status line didn't go out", name)
        finally:
            self._tasks.pop(name, None)

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)

    # --- where and as whom -------------------------------------------------------------------
    def _record(self, name: str) -> dict:
        try:
            return json.loads((self.agents.sessions / name / "session.json").read_text())
        except (OSError, ValueError):
            return {}

    def target(self, name: str, record: dict) -> tuple[str, str, int] | None:
        """(issue or pr, repository, number): its pull request, the open one first, else the issue it is on."""
        from .agents import covers_of

        prs = sorted(self.agents.known_prs(name) or [], key=lambda p: p.get("state") not in ("OPEN", None))
        if prs:
            return "pr", prs[0]["repo"], prs[0]["number"]
        covers = covers_of(record.get("config") or {})
        if covers and record.get("object") in ("issue", "pr"):
            return record["object"], covers[0]["repo"], covers[0]["number"]
        return None

    async def post(self, name: str, text: str) -> dict | None:
        record = self._record(name)
        where = self.target(name, record)
        if where is None:
            log.info("%s: no pull request or issue to post its status line to", name)
            return None
        kind, repo, number = where
        persona = (record.get("config") or {}).get("persona")
        try:
            token = await self.apps.token(persona) if self.apps is not None and persona else None
        except AppError as e:  # never as the login instead
            log.warning("%s: its status line wasn't posted: %s", name, e)
            return None
        if not token:  # no App: nothing goes out as the login
            log.info("%s: no status line, its persona %s has no GitHub App", name, persona)
            return None
        author = self.apps.posts_as(persona) if hasattr(self.apps, "posts_as") else None
        kept = self._kept(name)
        if kept and (kept.get("kind"), kept.get("repo"), kept.get("number")) == (kind, repo, number):
            if await self._edit(repo, number, kept["id"], text, token, author):
                return {"edited": kept["id"]}
            self._forget(name)
        wait = self.throttle - (self._clock() - self._posted.get(name, -self.throttle))
        if wait > 0:
            await self._sleep(wait)
            if name in self._newest:  # a newer line came while it waited: that one goes instead
                return None
        reply = await self.gh.run([kind, "comment", str(number), "-R", f"{ORG}/{repo}", "--body-file", "-"], text, None, token)
        found = _COMMENT_AT.search(reply.get("stdout", "")) if reply.get("code") == 0 else None
        self._posted[name] = self._clock()
        if not found:
            log.warning("%s: its status line didn't go out: %s", name, (reply.get("stderr") or "")[:200])
            return None
        self._keep(name, {"kind": kind, "repo": repo, "number": number, "id": int(found.group(1)), "persona": persona})
        return {"posted": int(found.group(1))}

    async def _edit(self, repo: str, number: int, comment_id: int, text: str, token, author: str | None) -> bool:
        """The kept comment, edited, if it is still the one: on this item, and written by this App."""
        try:
            got = await self.gh.run(["api", f"repos/{ORG}/{repo}/issues/comments/{int(comment_id)}"])
            comment = json.loads(got["stdout"]) if got.get("code") == 0 else {}
            node = comment.get("node_id")
            on = str(comment.get("issue_url") or "").lower().endswith(f"/repos/{ORG}/{repo}/issues/{int(number)}".lower())
            via = comment.get("performed_via_github_app") or {}
            by = (comment.get("user") or {}).get("login")
            mine = author is not None and (by == author or (isinstance(via, dict) and via.get("slug") and f"{via['slug']}[bot]" == author))
            if not isinstance(node, str) or not on or not mine:
                log.info("the status line comment %s in %s isn't the App's own on #%s any more: posting a new one", comment_id, repo, number)
                return False
            done = await self.gh.graphql("comment_edit", {"commentId": node, "body": text}, token)
            return done.get("code") == 0 and "errors" not in json.loads(done.get("stdout") or "{}")
        except (Refused, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            log.info("the status line in %s couldn't be edited: %s", repo, e)
            return False

    def _kept(self, name: str) -> dict | None:
        try:
            kept = json.loads((self.agents.sessions / name / FILE).read_text())
        except (OSError, ValueError):
            return None
        return kept if isinstance(kept, dict) and isinstance(kept.get("id"), int) else None

    def _forget(self, name: str) -> None:
        (self.agents.sessions / name / FILE).unlink(missing_ok=True)

    def _keep(self, name: str, value: dict) -> None:
        path = self.agents.sessions / name / FILE
        scratch = path.with_name(f".{FILE}.{secrets.token_hex(4)}")
        try:
            fd = os.open(scratch, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(value, f)
            scratch.replace(path)
        except OSError:
            log.exception("%s: where its status line is couldn't be kept", name)


__all__ = ["StatusLines", "line", "FILE", "THROTTLE"]
