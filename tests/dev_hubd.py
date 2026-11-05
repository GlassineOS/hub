# SPDX-License-Identifier: GPL-2.0-or-later
"""A hubd for trying the app without a real login: the password is DEV_PASSWORD.

Never use this as the real daemon. It listens on the socket you name, gh and tmux are
the real ones (or the ones on PATH).
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
from hubd.server import Hubd, serve
from hubd.shells import Shells


async def main():
    password = os.environ["DEV_PASSWORD"]
    token = "dev-agent-token"
    gh, shells = Gh(), Shells(env={"GLASSINE_HUB_MCP_TOKEN": token})
    # Agent sessions need DEV_STATE, and DEV_CLAUDE if a planner run shouldn't reach the real claude.
    agents = None
    if "DEV_STATE" in os.environ:
        agents = Agents(Library(Path(__file__).resolve().parents[1] / "agents"), shells, Path(os.environ["DEV_STATE"]),
                        gh=gh, claude=os.environ.get("DEV_CLAUDE", "false"), mcp_url="http://127.0.0.1:19095/mcp",
                        agent_token=token, environment={}, socket=Path(sys.argv[1]),
                        workspace=Path(os.environ["DEV_WORKSPACE"]) if "DEV_WORKSPACE" in os.environ else None)
    hubd = Hubd(gh, shells, auth.Sessions(), token, authenticate=lambda _u, p, _s: p == password, agents=agents,
                work=NewWork(Path(os.environ["DEV_STATE"]) / "newwork") if agents else None,
                device_reports=Devices(Path(os.environ["DEV_STATE"]) / "devices") if agents else None,
                decision_store=Decisions(Path(os.environ["DEV_STATE"]) / "decisions") if agents else None)
    await serve(hubd, Path(sys.argv[1]))


asyncio.run(main())
