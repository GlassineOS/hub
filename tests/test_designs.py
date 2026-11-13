# SPDX-License-Identifier: GPL-2.0-or-later
"""The design view's host side (011 FR-010 to FR-019), against a fake renderer (tests/fake_stream.py): no Docker."""
import asyncio
import json
import os
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from hubd import auth, designs as designs_module
from hubd.designs import FRAME_JSON, FRAME_PNG, PICTURE, DesignError, Designs, Full, Tools, input_command
from hubd.server import Hubd, serve
from hubd.shells import _HEADER, FRAME_EXIT, frame

FAKE = Path(__file__).with_name("fake_stream.py")
COMBINATIONS = {"contract": 1, "combinations": [
    {"voice": v, "scheme": s, "pen": p} for v in ("white", "editorial") for s in ("paper", "eink") for p in (1, 2)]}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def worktree(root: Path) -> Path:
    for project, files in (("hub", ["Main.dc.html", "history/Old.dc.html"]), ("shell", ["Panel.dc.html"])):
        for f in files:
            (root / "designs" / project / f).parent.mkdir(parents=True, exist_ok=True)
            (root / "designs" / project / f).write_text("<html></html>")
        (root / "designs" / project / "canvas.json").write_text("{}")
    (root / "designs" / "hub" / "ds").mkdir()
    (root / "designs" / "hub" / "ds" / "Copied.dc.html").write_text("")
    (root / "web").mkdir()
    (root / "web" / "combinations.json").write_text(json.dumps(COMBINATIONS))
    (root / "interleaf").mkdir()
    return root


class FakeAgents:
    """What Designs asks of Agents: which sessions there are, what they are, where their worktree is."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.records: dict[str, dict] = {}
        self.tokens: dict[str, str] = {}
        self.before_remove = None
        self.seeds = SimpleNamespace(auto=False)

    def add(self, name, action="design", repo="hub", ended=False):
        wt = worktree(self.tmp / "work" / name / "ui")
        self.records[name] = {"action": action, "repo": repo, "ended": ended, "worktree": wt}
        self.tokens[f"token-{name}"] = name
        return wt

    def is_session(self, name):
        return name in self.records

    def describe(self, name):
        r = self.records.get(name)
        return r and {"action": r["action"], "repo": r["repo"], "ended": r["ended"]}

    def _present(self, name):
        return [self.records[name]["worktree"]]

    async def session_state(self, name):
        return {"state": "Stopped" if self.records[name]["ended"] else "Working"}

    def scope(self, token):
        name = self.tokens.get(token)
        if name is None:
            return None
        return {"session": name, "tools": None, "design": self.records[name]["action"] == "design"}


def fake_docker(tmp: Path) -> tuple[str, Path]:
    """A docker that answers ps (by mounted volume), inspect (mounts) and rm -f from a JSON file of containers."""
    state = tmp / "docker.json"
    state.write_text(json.dumps({"containers": {}, "removed": []}))
    script = tmp / "docker"
    script.write_text(f"""#!{sys.executable}
import json, sys
path = {str(state)!r}
s = json.load(open(path))
a = sys.argv[1:]
if a[0] == "ps":
    volume = a[a.index("--filter") + 1].split("=", 1)[1]
    print("\\n".join(c for c, m in s["containers"].items() if volume in m))
elif a[0] == "inspect":
    print("\\n".join(s["containers"].get(a[-1], [])))
elif a[0] == "rm":
    for c in a[2:]:
        s["containers"].pop(c, None)
        s["removed"].append(c)
    json.dump(s, open(path, "w"))
""")
    script.chmod(0o755)
    return str(script), state


@pytest.fixture
def setup(tmp_path):
    agents = FakeAgents(tmp_path)
    ui = tmp_path / "ui-tools"
    (ui / "tools").mkdir(parents=True)
    clock = Clock()
    docker, docker_state = fake_docker(tmp_path)
    log = tmp_path / "commands.log"
    env = {"FAKE_STREAM_LOG": str(log)}
    made = []

    def command(tools, design, wt):
        made.append((tools, design, wt))
        return [sys.executable, str(FAKE), str(design)]

    d = Designs(agents, Tools(tmp_path / "cache", tmp_path / "ui.ref", root=ui), command=command, clock=clock, docker=docker, env=env)
    yield SimpleNamespace(agents=agents, designs=d, clock=clock, log=log, made=made, ui=ui, docker=docker_state, env=env, tmp=tmp_path)
    for name in list(d.views):
        view = d.views[name]
        if view.proc and view.proc.returncode is None:
            view.proc.kill()


def commands(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


async def until(check, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("timed out")


class Viewer:
    """The page's side of a design view, as the app relays it: frames on hubd's socket."""

    def __init__(self, reader, writer, reply):
        self.reader, self.writer, self.reply = reader, writer, reply
        self.views: list[dict] = []
        self.notes: list[str] = []
        self.pictures: list[tuple] = []
        self.ended = False
        self.task = asyncio.ensure_future(self._read()) if reply.get("ok") else None

    @classmethod
    async def open(cls, path, token, name):
        r, w = await asyncio.open_unix_connection(str(path), limit=64 * 1024 * 1024)
        w.write(json.dumps({"op": "design.attach", "token": token, "name": name}).encode() + b"\n")
        await w.drain()
        return cls(r, w, json.loads(await r.readline()))

    async def _read(self):
        try:
            while True:
                kind, length = _HEADER.unpack(await self.reader.readexactly(_HEADER.size))
                payload = await self.reader.readexactly(length)
                if kind == FRAME_JSON:
                    m = json.loads(payload)
                    (self.views if m["t"] == "view" else self.notes).append(m if m["t"] == "view" else m["text"])
                elif kind == FRAME_PNG:
                    seq, w, h = PICTURE.unpack(payload[:PICTURE.size])
                    self.pictures.append((seq, w, h, payload[PICTURE.size:]))
                elif kind == FRAME_EXIT:
                    break
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        self.ended = True

    @property
    def last(self) -> dict:
        return self.views[-1] if self.views else {}

    async def send(self, message: dict):
        self.writer.write(frame(FRAME_JSON, json.dumps(message).encode()))
        await self.writer.drain()

    async def close(self):
        self.writer.close()
        if self.task:
            await asyncio.wait_for(asyncio.gather(self.task, return_exceptions=True), 5)


class Served:
    def __init__(self, s):
        self.s = s
        self.sessions = auth.Sessions()
        self.login = self.sessions.create()
        self.hubd = Hubd(None, None, self.sessions, "agent-secret", agents=s.agents, designs=s.designs)
        self.path = s.tmp / "sock" / "hubd.sock"

    async def __aenter__(self):
        self.task = asyncio.ensure_future(serve(self.hubd, self.path))
        await until(self.path.exists)
        return self

    async def __aexit__(self, *a):
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)

    def viewer(self, name, token=None):
        return Viewer.open(self.path, self.login if token is None else token, name)


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 60))


# --- reaching a view ------------------------------------------------------------------------------------
def test_only_a_login_opens_a_view_and_only_of_a_design_session(setup):
    setup.agents.add("design-7")
    setup.agents.add("implement-3", action="issue-docs")

    async def go():
        async with Served(setup) as hub:
            denied = await hub.viewer("design-7", token="wrong")
            assert denied.reply == {"ok": False, "error": "login required", "denied": True}
            none = await hub.viewer("design-7", token="")
            assert none.reply["ok"] is False
            other = await hub.viewer("implement-3")
            assert other.reply["ok"] is False and "not a design session" in other.reply["error"]
            missing = await hub.viewer("nobody")
            assert missing.reply["ok"] is False
            assert not setup.made  # nothing started for any of them
    run(go())


def test_a_viewer_starts_the_renderer_from_the_pinned_tools_on_the_worktree(setup):
    wt = setup.agents.add("design-7")

    async def go():
        async with Served(setup) as hub:
            v = await hub.viewer("design-7")
            assert v.reply == {"ok": True}
            await until(lambda: v.pictures and v.last.get("status") == "running")
            # the tools are the pinned checkout's; the worktree is only data, and the renderer runs in it
            assert setup.made == [(setup.ui, wt / "designs" / "hub", wt)]
            seq, w, h, png = v.pictures[0]
            assert (w, h) == (200, 200) and png.startswith(b"\x89PNG") and len(png) > 64 * 1024  # over asyncio's line default
            assert v.last["project"] == "hub" and v.last["projects"] == ["hub", "shell"]
            assert v.last["boards"] == ["Main.dc.html", "history/Old.dc.html"]  # not ds/
            assert v.last["voices"] == ["white", "editorial"] and v.last["pens"] == [1, 2]
            assert v.last["viewers"] == 1 and v.last["follow"] is True
            await v.close()
    run(go())


def test_the_renderer_runs_without_network_and_from_the_worktree():
    cmd = designs_module.stream_command(Path("/c/ui/v1.2.0"), Path("/w/ui/designs/hub"), Path("/w/ui"))
    assert cmd == ["/c/ui/v1.2.0/tools/in-alpine", "/c/ui/v1.2.0/tools/boards", "stream", "/w/ui/designs/hub",
                   "--interleaf", "/w/ui/interleaf", "--web", "/w/ui/web"]
    d = Designs(None, Tools(Path("/c"), Path("/r")))
    assert d.env["BOARDS_NETWORK"] == "none"


def test_the_default_project_is_the_issue_repository_s_folder(setup):
    setup.agents.add("design-1", repo="shell")
    setup.agents.add("design-2", repo="boot")
    assert setup.designs._view("design-1").project == "shell"
    assert setup.designs._view("design-2").project == "hub"  # boot has none: the first


def test_every_viewer_gets_the_newest_picture_on_connect_and_both_can_click(setup):
    setup.agents.add("design-7")

    async def go():
        async with Served(setup) as hub:
            a = await hub.viewer("design-7")
            await until(lambda: a.pictures)
            await a.send({"t": "input", "input": {"op": "mouse", "type": "mousePressed", "x": 10, "y": 5, "button": "left", "clickCount": 1}})
            await until(lambda: len(a.pictures) >= 2)
            b = await hub.viewer("design-7")
            await until(lambda: b.pictures)
            assert b.pictures[0][0] == a.pictures[-1][0]  # the newest, at once, with no new frame needed
            await until(lambda: a.last.get("viewers") == 2)
            await b.send({"t": "input", "input": {"op": "key", "type": "keyDown", "key": "a", "text": "a", "keyCode": 65}})
            await until(lambda: len(commands(setup.log)) == 2)
            assert commands(setup.log) == [
                {"op": "mouse", "type": "mousePressed", "x": 10, "y": 5, "modifiers": 0, "button": "left", "clickCount": 1},
                {"op": "key", "type": "keyDown", "modifiers": 0, "key": "a", "text": "a", "keyCode": 65}]
            await until(lambda: len(b.pictures) >= 2 and len(a.pictures) >= 3)  # both see what either did
            await b.close()
            await until(lambda: a.last.get("viewers") == 1)
            await a.close()
    run(go())


def test_only_inputs_of_a_known_shape_reach_the_renderer():
    assert input_command({"op": "mouse", "type": "mouseMoved", "x": 1.5, "y": 2, "evil": "x"}) == {"op": "mouse", "type": "mouseMoved", "x": 1.5, "y": 2, "modifiers": 0}
    assert input_command({"op": "touch", "type": "touchStart", "points": [{"x": 1, "y": 2, "other": 1}]})["points"] == [{"x": 1, "y": 2, "id": 0}]
    for bad in ({"op": "open", "board": "x"}, {"op": "mouse", "type": "mouseMoved", "x": float("nan"), "y": 0},
                {"op": "mouse", "type": "drag", "x": 0, "y": 0}, {"op": "mouse", "type": "mouseMoved", "x": True, "y": 0},
                {"op": "key", "type": "keyDown", "text": "x" * 33}, {"op": "key", "type": "keyDown", "keyCode": 999},
                {"op": "wheel", "x": 0, "y": 0, "deltaY": 1e9}, {"op": "touch", "type": "touchStart", "points": [{}] * 11},
                {"op": "mouse", "type": "mousePressed", "x": 0, "y": 0, "button": "thumb"}, "mouse", None):
        with pytest.raises(DesignError):
            input_command(bad)


def test_a_viewer_s_bad_message_is_answered_and_the_view_goes_on(setup):
    setup.agents.add("design-7")

    async def go():
        async with Served(setup) as hub:
            v = await hub.viewer("design-7")
            await until(lambda: v.last.get("status") == "running")
            await v.send({"t": "input", "input": {"op": "frame"}})
            await v.send({"t": "open", "board": "../../../etc/passwd"})
            await v.send({"t": "nonsense"})
            await until(lambda: len(v.notes) >= 3)
            assert "mouse, wheel, touch or key" in v.notes[0] and "no board" in v.notes[1]
            await v.send({"t": "open", "board": "history/Old.dc.html", "voice": "editorial", "scheme": "eink", "pen": "2"})
            await until(lambda: (v.last.get("state") or {}).get("board") == "history/Old.dc.html")
            assert v.last["state"] == {"view": "board", "board": "history/Old.dc.html", "voice": "editorial", "scheme": "eink", "pen": 2,
                                       "page": None, "width": 320, "height": 240}
            assert commands(setup.log) == [{"op": "open", "board": "history/Old.dc.html", "voice": "editorial", "scheme": "eink", "pen": 2}]
            await v.close()
    run(go())


def test_the_renderer_s_state_is_read_as_untrusted(setup):
    setup.agents.add("design-7")
    setup.designs.env["FAKE_STREAM_STATE"] = json.dumps({"view": "<script>", "board": "../../secret.dc.html", "voice": "x\" onload=", "pen": "9",
                                                         "page": "a\x00b", "width": 99999, "url": "javascript:alert(1)"})

    async def go():
        async with Served(setup) as hub:
            v = await hub.viewer("design-7")
            await until(lambda: v.last.get("state"))
            assert v.last["state"] == {"view": "other", "board": None, "voice": None, "scheme": None, "pen": None, "page": "a b", "width": None, "height": 800}
            assert "javascript" not in json.dumps(v.views) and "url" not in v.last["state"]
            await v.close()
    run(go())


# --- the session's tools ---------------------------------------------------------------------------------
def test_the_tools_are_bound_to_the_caller_s_own_token(setup):
    setup.agents.add("design-7")
    setup.agents.add("design-8")
    setup.agents.add("implement-3", action="issue-docs")

    async def go():
        async with Served(setup) as hub:
            h = hub.hubd
            for token in (None, "", "nope", "agent-secret", "token-implement-3"):
                reply = await h.request({"op": "design.view", "agent_token": token})
                assert reply["ok"] is False and reply["refused"] is True, token
                reply = await h.request({"op": "design.open", "agent_token": token, "board": "Main.dc.html"})
                assert reply["ok"] is False and "only a design session" in reply["error"]
            # a name in the request is not how a session is chosen
            reply = await h.request({"op": "design.open", "agent_token": "token-design-8", "name": "design-7", "board": "Main.dc.html"})
            assert reply["ok"] and reply["shown"] is True
            assert "design-8" in setup.designs.views and "design-7" not in setup.designs.views
            await until(lambda: (setup.designs.views["design-8"].state or {}).get("board") == "Main.dc.html")
            view = await h.request({"op": "design.view", "agent_token": "token-design-8"})
            assert {k: view[k] for k in ("project", "showing", "board", "follow", "viewers", "renderer")} == \
                {"project": "hub", "showing": "board", "board": "Main.dc.html", "follow": True, "viewers": 0, "renderer": "running"}
            assert view["size"] == {"width": 320, "height": 240} and "url" not in view
    run(go())


def test_design_open_is_checked_against_the_folder_and_its_web_form(setup):
    setup.agents.add("design-7")

    async def go():
        d = setup.designs
        for args, words in (({"board": "Nope.dc.html"}, "no board"), ({"board": "ds/Copied.dc.html"}, "no board"),
                            ({"board": "Main.dc.html", "voice": "stationery"}, "voice is one of white, editorial"),
                            ({"board": "Main.dc.html", "scheme": "night"}, "scheme is one of"), ({"board": "Main.dc.html", "pen": 3}, "pen is one of 1, 2"),
                            ({"board": "Main.dc.html", "width": 5000}, "width is a whole number"),
                            ({"board": "Main.dc.html", "project": "../.."}, "no design folder"), ({"board": "Main.dc.html", "project": "shell"}, "no board")):
            with pytest.raises(DesignError, match=words):
                await d.session_open("design-7", args)
        assert not setup.made  # nothing started for a refused open
        reply = await d.session_open("design-7", {"board": "Panel.dc.html", "project": "shell", "voice": "white", "pen": 1, "width": 400, "height": 300})
        assert reply["shown"] and reply["project"] == "shell"
        # the reply says what the renderer shows once it has opened it, not the canvas it started on
        assert reply["showing"] == "board" and reply["board"] == "Panel.dc.html" and reply["size"] == {"width": 400, "height": 300}
        assert reply["message"] is None
        await until(lambda: commands(setup.log))
        assert commands(setup.log) == [{"op": "open", "board": "Panel.dc.html", "voice": "white", "pen": 1, "width": 400, "height": 300}]
        await d.stop("design-7")
    run(go())


# --- follow (FR-014) --------------------------------------------------------------------------------------
def test_follow_is_the_view_s_and_off_turns_opens_into_suggestions(setup):
    setup.agents.add("design-7")

    async def go():
        async with Served(setup) as hub:
            a = await hub.viewer("design-7")
            b = await hub.viewer("design-7")
            await until(lambda: a.last.get("status") == "running" and b.last.get("viewers") == 2)
            await setup.designs.session_open("design-7", {"board": "Main.dc.html"})
            await until(lambda: (b.last.get("state") or {}).get("board") == "Main.dc.html")
            await a.send({"t": "follow", "on": False})  # one viewer turns it off: for both
            await until(lambda: b.last.get("follow") is False)
            reply = await setup.designs.session_open("design-7", {"board": "history/Old.dc.html", "scheme": "eink"})
            assert reply["shown"] is False and reply["follow"] is False
            await until(lambda: b.last.get("suggestion"))
            assert a.last["suggestion"] == {"board": "history/Old.dc.html", "voice": None, "scheme": "eink", "pen": None, "width": None, "height": None, "project": "hub"}
            assert [c["board"] for c in commands(setup.log) if c["op"] == "open"] == ["Main.dc.html"]  # the view stayed
            await b.send({"t": "take"})  # "Show it"
            await until(lambda: (a.last.get("state") or {}).get("board") == "history/Old.dc.html")
            assert a.last["suggestion"] is None
            await b.send({"t": "follow", "on": True})
            await until(lambda: a.last.get("follow") is True)
            await setup.designs.session_open("design-7", {"board": "Main.dc.html"})
            await until(lambda: (a.last.get("state") or {}).get("board") == "Main.dc.html")
            await a.close()
            await b.close()
    run(go())


def test_switching_the_project_restarts_on_that_folder(setup):
    wt = setup.agents.add("design-7")

    async def go():
        async with Served(setup) as hub:
            v = await hub.viewer("design-7")
            await until(lambda: v.last.get("status") == "running")
            first = setup.designs.views["design-7"].proc
            await v.send({"t": "project", "name": "shell"})
            await until(lambda: v.last.get("project") == "shell" and v.last.get("status") == "running")
            assert first.returncode is not None and setup.made[-1][1] == wt / "designs" / "shell"
            assert v.last["boards"] == ["Panel.dc.html"]
            await v.send({"t": "project", "name": "../../etc"})
            await until(lambda: v.notes)
            assert "no design folder" in v.notes[-1]
            await v.close()
    run(go())


# --- lifecycle (FR-017) ------------------------------------------------------------------------------------
def test_a_tool_call_starts_it_too(setup):
    setup.agents.add("design-7")

    async def go():
        view = await setup.designs.session_look("design-7")
        assert view["renderer"] in ("starting", "running") and setup.made
        await setup.designs.stop("design-7")
    run(go())


def test_it_stops_after_ten_minutes_without_a_viewer_once_the_session_has_ended(setup):
    setup.agents.add("design-7")
    d, clock = setup.designs, setup.clock

    async def go():
        async with Served(setup) as hub:
            v = await hub.viewer("design-7")
            await until(lambda: v.last.get("status") == "running")
            clock.now += 3600
            await d.tick()
            assert d.views["design-7"].alive()  # a viewer is connected
            await v.close()
            await until(lambda: not d.views["design-7"].viewers)
            clock.now += 3600
            await d.tick()
            assert d.views["design-7"].alive()  # the session is still running: it stays
            setup.agents.records["design-7"]["ended"] = True
            await d.tick()
            assert not d.views["design-7"].alive()  # ended, and no one has watched for an hour
            # a viewer of the ended session: the view stays usable, and starts it again
            v = await hub.viewer("design-7")
            await until(lambda: v.last.get("ended") is True and v.last.get("status") == "running")
            await v.close()
            await until(lambda: not d.views["design-7"].viewers)
            clock.now += 599
            await d.tick()
            assert d.views["design-7"].alive()
            clock.now += 1
            await d.tick()
            assert not d.views["design-7"].alive() and d.views["design-7"].status == "stopped"
            assert commands(setup.log) == []  # it went by the end of its input, not a command
    run(go())


def test_at_most_three_run_and_the_fourth_names_them_with_a_way_to_stop_one(setup):
    for n in range(1, 5):
        setup.agents.add(f"design-{n}")
    d = setup.designs

    async def go():
        async with Served(setup) as hub:
            for n in range(1, 4):
                await d.start(f"design-{n}")
            with pytest.raises(Full) as e:
                await d.start("design-4")
            assert e.value.names == ["design-1", "design-2", "design-3"]
            reply = await hub.hubd.request({"op": "design.open", "agent_token": "token-design-4", "board": "Main.dc.html"})
            assert not reply["ok"] and "design-1, design-2, design-3" in reply["error"]
            v = await hub.viewer("design-4")
            await until(lambda: v.last.get("status") == "full")
            assert v.last["running"] == ["design-1", "design-2", "design-3"] and "stop one" in v.last["message"]
            await v.send({"t": "stop_other", "name": "design-2"})
            await until(lambda: v.last.get("status") == "running")
            assert d.running() == ["design-1", "design-3", "design-4"]
            assert d.views["design-2"].status == "stopped"
            await v.send({"t": "stop_other", "name": "design-9"})
            await until(lambda: v.notes)
            assert "isn't running" in v.notes[-1]
            await v.close()
            for n in d.running():
                await d.stop(n)
    run(go())


def test_leftover_containers_are_reaped_on_start_and_a_stop_removes_its_own(setup):
    other_wt = setup.tmp / "work" / "design-9" / "ui"
    wt = setup.agents.add("design-7")
    setup.docker.write_text(json.dumps({"removed": [], "containers": {
        "old": [str(setup.ui), str(other_wt)], "mine": [str(setup.ui), str(wt)], "someone-else": ["/srv/elsewhere/ui"]}}))

    async def go():
        d = setup.designs
        await d.start("design-7")
        await d.stop("design-7")
        assert json.loads(setup.docker.read_text())["removed"] == ["mine"]  # only the stopped one's
        await d.reap()
        state = json.loads(setup.docker.read_text())
        assert state["removed"] == ["mine", "old"] and list(state["containers"]) == ["someone-else"]  # never a container not mounting our tools
    run(go())


def test_hubd_reaps_when_it_starts(setup):
    setup.docker.write_text(json.dumps({"removed": [], "containers": {"old": [str(setup.ui)]}}))

    async def go():
        async with Served(setup):
            await until(lambda: json.loads(setup.docker.read_text())["removed"] == ["old"])
    run(go())


def test_a_crash_says_so_and_restarts_without_touching_the_session(setup):
    setup.agents.add("design-7")
    setup.designs.env["FAKE_STREAM_CRASH_ON"] = "wheel"

    async def go():
        async with Served(setup) as hub:
            v = await hub.viewer("design-7")
            await until(lambda: v.last.get("status") == "running")
            await v.send({"t": "input", "input": {"op": "wheel", "x": 1, "y": 1, "deltaY": 100}})
            await until(lambda: v.last.get("status") == "crashed")
            assert v.last["message"] == "The renderer stopped: chromium went away"
            assert setup.agents.records["design-7"]["ended"] is False
            await v.send({"t": "restart"})
            await until(lambda: v.last.get("status") == "running")
            assert len(setup.made) == 2
            await v.close()
    run(go())


def test_the_renderer_stops_before_the_worktree_goes(setup):
    setup.agents.add("design-7")

    async def go():
        async with Served(setup) as hub:
            v = await hub.viewer("design-7")
            await until(lambda: v.last.get("status") == "running")
            proc = setup.designs.views["design-7"].proc
            await setup.agents.before_remove("design-7")  # what Agents calls ahead of `git worktree remove`
            assert proc.returncode is not None and "design-7" not in setup.designs.views
            await until(lambda: v.ended)
            assert v.last["status"] == "gone" and "worktree was removed" in v.last["message"]
    run(go())


def test_agents_stop_the_view_before_removing_a_worktree(tmp_path):
    """The hook in hubd.agents: _remove and the cleanup both call it before git touches the worktree."""
    from hubd.agents import Agents
    import inspect
    source = inspect.getsource(Agents._remove)
    assert source.index("_before_remove") < source.index('"worktree", "remove"')
    source = inspect.getsource(Agents._remove_if_safe)
    assert source.index("_before_remove") < source.index('row["_argv"]')


# --- the tools checkout --------------------------------------------------------------------------------------
def test_the_tools_come_from_a_release_tag_fetched_into_the_cache(tmp_path):
    ref = tmp_path / "ui.ref"
    ref.write_text("main\n")
    with pytest.raises(DesignError, match="release tag"):
        Tools(tmp_path / "cache", ref).ref()
    ref.write_text("v1.2.0\n")
    calls = tmp_path / "git.log"
    git = tmp_path / "git"
    # a git that records its arguments and, on checkout, lays out the tools
    git.write_text(f"""#!/bin/sh
echo "$@" >> {calls}
case "$*" in *checkout*) mkdir -p "$2/tools" && touch "$2/tools/boards" "$2/tools/in-alpine" ;; esac
""")
    git.chmod(0o755)
    tools = Tools(tmp_path / "cache", ref, git=str(git))

    async def go():
        root = await tools.ensure()
        assert root == tmp_path / "cache" / "ui" / "v1.2.0" and (root / "tools" / "boards").is_file()
        lines = calls.read_text().splitlines()
        assert any("fetch -q --depth 1 https://github.com/GlassineOS/ui refs/tags/v1.2.0" in line for line in lines)
        assert await tools.ensure() == root and len(calls.read_text().splitlines()) == len(lines)  # once
        assert tools.all_roots() == [root]
    run(go())


def test_the_frame_kinds_match_the_app_s():
    from app.hub import hubd_client
    assert (hubd_client.FRAME_JSON, hubd_client.FRAME_PNG) == (FRAME_JSON, FRAME_PNG)
    assert hubd_client.HEADER.format == _HEADER.format


def test_the_hub_pins_its_ui_release_in_one_place():
    root = Path(__file__).resolve().parents[1]
    source = (root / "hubd" / "server.py").read_text()
    assert '"app" / "ui.ref"' in source  # the same file app/fetch-ui.sh reads


# --- the real renderer (optional) ----------------------------------------------------------------------------
SMOKE = os.environ.get("HUB_DESIGN_SMOKE") == "1"


def _docker_up() -> bool:
    return shutil.which("docker") is not None and subprocess.run(["docker", "info"], capture_output=True).returncode == 0


@pytest.mark.skipif(not SMOKE or not _docker_up(), reason="HUB_DESIGN_SMOKE=1 with Docker running: fetches GlassineOS/ui at app/ui.ref and runs its renderer")
def test_the_real_renderer(tmp_path):
    """One real design view on GlassineOS/ui at the pinned release, in its network-less container. Prints the latencies it saw.
    HUB_DESIGN_SMOKE_CACHE keeps the fetched checkout between runs."""
    tools = Tools(Path(os.environ.get("HUB_DESIGN_SMOKE_CACHE") or tmp_path / "cache"), Path(__file__).resolve().parents[1] / "app" / "ui.ref")
    ui = asyncio.run(tools.ensure())
    agents = FakeAgents(tmp_path)
    wt = tmp_path / "work" / "design-1" / "ui"
    wt.parent.mkdir(parents=True)
    shutil.copytree(ui / "web", wt / "web")
    shutil.copytree(ui / "interleaf", wt / "interleaf")
    shutil.copytree(ui / "boards" / "samples", wt / "designs" / "samples")
    agents.records["design-1"] = {"action": "design", "repo": "samples", "ended": False, "worktree": wt}
    d = Designs(agents, tools)

    def ours() -> list[str]:
        return subprocess.run(["docker", "ps", "-q", "--filter", f"volume={ui}"], capture_output=True, text=True).stdout.split()

    async def go():
        sessions = auth.Sessions()
        hub = Hubd(None, None, sessions, "agent-secret", agents=agents, designs=d)
        path = tmp_path / "s" / "hubd.sock"
        task = asyncio.ensure_future(serve(hub, path))
        await until(path.exists)
        try:
            t0 = time.monotonic()
            v = await Viewer.open(path, sessions.create(), "design-1")
            await until(lambda: v.pictures, 240)
            first = time.monotonic() - t0
            # FR-018: the renderer's container has no network
            modes = [subprocess.run(["docker", "inspect", "--format", "{{.HostConfig.NetworkMode}}", c], capture_output=True, text=True).stdout.strip() for c in ours()]
            assert modes and set(modes) == {"none"}, modes
            await d.session_open("design-1", {"board": "Form.dc.html"})
            await until(lambda: (v.last.get("state") or {}).get("board") == "Form.dc.html" and v.pictures[-1][1:3] == (480, 420), 60)
            await asyncio.sleep(1)

            async def changed(since: bytes, timeout=10):
                start = time.monotonic()
                await until(lambda: v.pictures[-1][3] != since, timeout)
                return time.monotonic() - start
            base = v.pictures[-1][3]
            await v.send({"t": "input", "input": {"op": "mouse", "type": "mousePressed", "x": 120, "y": 72, "button": "left", "clickCount": 1}})
            await v.send({"t": "input", "input": {"op": "mouse", "type": "mouseReleased", "x": 120, "y": 72, "button": "left", "clickCount": 1}})
            click = await changed(base)  # the input takes focus: its outline
            await asyncio.sleep(0.5)
            base = v.pictures[-1][3]
            await v.send({"t": "input", "input": {"op": "key", "type": "keyDown", "key": "h", "code": "KeyH", "keyCode": 72, "text": "h"}})
            key = await changed(base)
            await v.send({"t": "input", "input": {"op": "key", "type": "keyUp", "key": "h", "code": "KeyH", "keyCode": 72}})
            await asyncio.sleep(0.5)
            board = wt / "designs" / "samples" / "Form.dc.html"
            base = v.pictures[-1][3]
            board.write_text(board.read_text().replace(">Name<", ">Your name<"))
            save = await changed(base)
            print(f"\nfirst picture {first:.1f} s, click to picture {click * 1000:.0f} ms, key to picture {key * 1000:.0f} ms, save to changed picture {save * 1000:.0f} ms")
            assert save < 2.0  # SC-002
            assert click < 0.5  # SC-003, here on the host
            await v.close()
            # a renderer whose client died (as when hubd is killed) is what reap() is for
            d.views["design-1"].proc.kill()
            await d.reap()
            assert ours() == [], "a renderer container was left running"
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            for name in d.running():
                await d.stop(name)
    asyncio.run(asyncio.wait_for(go(), 600))
