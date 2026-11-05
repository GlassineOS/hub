# SPDX-License-Identifier: GPL-2.0-or-later
"""Runs the host's gh for the app, after the policy has said yes."""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from .ghpolicy import ORG, Refused, changes_query, check

GRAPHQL_DIR = Path(__file__).parent / "graphql"
MAX_OUTPUT = 32 * 1024 * 1024
MAX_TIMEOUT = 300
_ENV_KEEP = ("HOME", "PATH", "LANG", "USER", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
             "XDG_CACHE_HOME", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")


def _env(token: str | None = None) -> dict:
    # Not inherited wholesale: GH_HOST, GH_REPO or GH_TOKEN would change what the policy checked.
    env = {k: os.environ[k] for k in _ENV_KEEP if k in os.environ}
    env.update(GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1", GH_PAGER="cat", NO_COLOR="1",
               GH_SPINNER_DISABLED="1")
    if token:
        env["GH_TOKEN"] = token  # a persona's App. Never from the environment, see above
    return env


async def _collect(proc, stdin: str | None) -> tuple[bytes, bytes, bool]:
    """Reads gh's output up to the limit, and stops gh there rather than hold it all."""
    async def feed():
        if stdin is not None:
            proc.stdin.write(stdin.encode())
            try:
                await proc.stdin.drain()
            except ConnectionError:
                pass
            proc.stdin.close()

    async def errors():
        return await proc.stderr.read()

    feeding, reading = asyncio.create_task(feed()), asyncio.create_task(errors())
    out = bytearray()
    truncated = False
    try:
        while chunk := await proc.stdout.read(65536):
            out += chunk
            if len(out) > MAX_OUTPUT:
                truncated = True
                del out[MAX_OUTPUT:]
                proc.kill()
                break
        err = await reading
        await feeding
        await proc.wait()
    finally:
        feeding.cancel()
        reading.cancel()
    return bytes(out), err, truncated


class Gh:
    def __init__(self, program: str = "gh", workdir: str | None = None, concurrency: int = 8):
        self.program = program
        # An empty directory: gh must find no repository to default to.
        self.workdir = workdir or tempfile.mkdtemp(prefix="hubd-gh-")
        self._slots = asyncio.Semaphore(concurrency)
        self.documents = {p.stem: p.read_text() for p in sorted(GRAPHQL_DIR.glob("*.graphql"))}
        # GitHub refuses a fragment nobody uses, so only the documents that use these get them.
        fields = (GRAPHQL_DIR / "work_fields.fragment").read_text()
        for name, text in self.documents.items():
            if "...IssueFields" in text:
                self.documents[name] = text + "\n" + fields
        self._org_projects: set[str] = set()

    def available(self) -> bool:
        return shutil.which(self.program) is not None

    async def _exec(self, argv: list[str], stdin: str | None, timeout, token: str | None = None) -> dict:
        limit = min(int(timeout or 60), MAX_TIMEOUT)
        async with self._slots:
            try:
                proc = await asyncio.create_subprocess_exec(
                    self.program, *argv, cwd=self.workdir, env=_env(token),
                    stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError:
                return {"code": 127, "stdout": "", "stderr": "gh is not installed on the host"}
            try:
                out, err, truncated = await asyncio.wait_for(_collect(proc, stdin), limit)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                return {"code": 124, "stdout": "", "stderr": f"gh: timed out after {limit} s"}
        return {"code": proc.returncode, "stdout": out.decode(errors="replace"),
                "stderr": err[-65536:].decode(errors="replace"), "truncated": truncated}

    async def run(self, argv, stdin=None, timeout=None, token=None) -> dict:
        check(argv)
        return await self._exec(list(argv), stdin, timeout, token)

    def is_mutation(self, name) -> bool:
        document = self.documents.get(name) if isinstance(name, str) else None
        return bool(document) and document.lstrip().startswith("mutation")

    async def graphql(self, name, variables=None, token=None) -> dict:
        """Runs one of the documents in graphql/. The app can't send its own."""
        document = self.documents.get(name) if isinstance(name, str) else None
        if document is None:
            raise Refused(f"unknown GraphQL document: {name}")
        variables = dict(variables or {})
        # Search can name any owner, so the app never supplies this query.
        if "query" in variables:
            raise Refused("GraphQL: the search query is not the app's to choose")
        if name == "org_changes":
            variables["query"] = changes_query(variables.pop("scope", None), variables.pop("since", None))
        for key, value in variables.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(key)) or not isinstance(value, (str, int, bool, type(None))):
                raise Refused(f"bad GraphQL variable: {key}")
        variables["org"] = ORG
        # Node ids can name anything, so a project id must be one of the organization's.
        if "projectId" in variables and variables["projectId"] not in await self._projects(variables["projectId"]):
            raise Refused("that project is not in the organization")
        if "contentId" in variables and not await self._in_org(variables["contentId"]):
            raise Refused("that issue or pull request is not in the organization")
        if "threadId" in variables and not await self._in_org(variables["threadId"]):
            raise Refused("that review thread is not in the organization")
        return await self._document(document, variables, token)

    async def _document(self, document: str, variables: dict, token=None) -> dict:
        body = json.dumps({"query": document, "variables": variables})
        return await self._exec(["api", "graphql", "--input", "-"], body, 60, token)

    async def _in_org(self, node_id) -> bool:
        result = await self._document(self.documents["content_owner"], {"id": node_id})
        try:
            login = json.loads(result["stdout"])["data"]["node"]["repository"]["owner"]["login"]
        except (ValueError, KeyError, TypeError):
            return False
        return login == ORG

    async def _projects(self, wanted) -> set[str]:
        if wanted not in self._org_projects:
            result = await self._document(self.documents["org_projects"], {"org": ORG})
            try:
                nodes = json.loads(result["stdout"])["data"]["organization"]["projectsV2"]["nodes"]
            except (ValueError, KeyError, TypeError):
                return self._org_projects  # no answer: the id stays unknown, and refused
            self._org_projects = {n["id"] for n in nodes}
        return self._org_projects
