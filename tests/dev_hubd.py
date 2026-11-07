# SPDX-License-Identifier: GPL-2.0-or-later
"""A hubd for trying the app without a real login: the password is DEV_PASSWORD.

Never use this as the real daemon. It listens on the socket you name, gh and tmux are
the real ones (or the ones on PATH). The tool server URL is DEV_MCP_URL (default port 19095).
"""
import asyncio
import os
import sys
from pathlib import Path

from hubd import auth
from hubd.decisions import Decisions
from hubd.devices import Devices
from hubd.agents import Agents, Library
from hubd.ghrun import Gh
from hubd.newwork import NewWork
from hubd.results import Results
from hubd.server import Hubd, serve
from hubd.shells import Shells


DEFAULT_MCP_URL = "http://127.0.0.1:19095/mcp"


def build(socket, env=os.environ):
    """The dev Hubd for this environment. DEV_MCP_URL names the tool server (parallel runs differ)."""
    password = env["DEV_PASSWORD"]
    token = "dev-agent-token"
    gh, shells = Gh(), Shells(env={"GLASSINE_HUB_MCP_TOKEN": token})
    # Agent sessions need DEV_STATE, and DEV_CLAUDE if a planner run shouldn't reach the real claude.
    agents = None
    if "DEV_STATE" in env:
        agents = Agents(Library(Path(__file__).resolve().parents[1] / "agents"), shells, Path(env["DEV_STATE"]),
                        gh=gh, claude=env.get("DEV_CLAUDE", "false"), mcp_url=env.get("DEV_MCP_URL", DEFAULT_MCP_URL),
                        agent_token=token, environment={}, socket=Path(socket),
                        workspace=Path(env["DEV_WORKSPACE"]) if "DEV_WORKSPACE" in env else None)
    return Hubd(gh, shells, auth.Sessions(), token, authenticate=lambda _u, p, _s: p == password, agents=agents,
                work=NewWork(Path(env["DEV_STATE"]) / "newwork") if agents else None,
                result_store=Results(Path(env["DEV_STATE"]) / "results") if agents else None,
                device_reports=Devices(Path(env["DEV_STATE"]) / "devices") if agents else None,
                decision_store=Decisions(Path(env["DEV_STATE"]) / "decisions") if agents else None)


async def main():
    await serve(build(sys.argv[1]), Path(sys.argv[1]))


if __name__ == "__main__":
    asyncio.run(main())
