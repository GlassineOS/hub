# SPDX-License-Identifier: GPL-2.0-or-later
"""Design views: the live picture of a design session's boards (spec 011 FR-010 to FR-019).

One renderer per design session: GlassineOS/ui's `tools/boards stream`, run through its `tools/in-alpine` in a container
without network. The tools come from a checkout of GlassineOS/ui at the release in `app/ui.ref`, kept in hubd's cache,
never from the session's worktree: the worktree is only data (the design folder, its Interleaf and its web form).

The renderer speaks JSON lines (README "Boards" in GlassineOS/ui). Everything it says is read as untrusted: a board's
code drives the page, and so the address and the state the renderer reports. Only commands of a known shape reach it.

A viewer is a framed connection (the same header as a shell attach): FRAME_JSON carries a JSON object either way,
FRAME_PNG a picture, 12 bytes of seq, width and height (big endian) and the PNG.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import os
import re
import shutil
import struct
import tempfile
import time
from pathlib import Path

from .shells import _HEADER, FRAME_EXIT, frame

log = logging.getLogger("hubd.designs")

UI_REPO = "https://github.com/GlassineOS/ui"
REF_RE = re.compile(r"v\d+\.\d+\.\d+")
FRAME_JSON, FRAME_PNG = 3, 4
PICTURE = struct.Struct(">III")
DESIGN_ACTION = "design"
IDLE_STOP = 600  # seconds without a viewer, once the session has ended (FR-017)
MAX_RUNNING = 3
TICK = 30  # seconds between looks at idle views
LINE_LIMIT = 64 * 1024 * 1024  # one frame is one line of base64 PNG
MAX_PNG = 32 * 1024 * 1024
MAX_IN = 16 * 1024  # a viewer's message
MAX_SIDE = 4096
STOP_WAIT = 5.0
NOTE_LEN = 200
KEPT_STDERR = 20

MOUSE = ("mousePressed", "mouseReleased", "mouseMoved")
TOUCH = ("touchStart", "touchMove", "touchEnd", "touchCancel")
KEY = ("keyDown", "keyUp", "rawKeyDown", "char")
BUTTONS = ("none", "left", "middle", "right", "back", "forward")
VIEWS = ("canvas", "board", "view", "other")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class DesignError(Exception):
    pass


def _text(value, limit: int = NOTE_LEN) -> str:
    """Words from the renderer or a board, made safe to show as text: one line, no control characters, short."""
    return _CONTROL.sub(" ", str(value))[:limit]


def _number(value, low: float, high: float, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise DesignError(f"{what} is a number from {low:g} to {high:g}")
    return value


def _integer(value, low: int, high: int, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise DesignError(f"{what} is a whole number from {low} to {high}")
    return value


def _modifiers(c: dict) -> int:
    return _integer(c.get("modifiers", 0), 0, 15, "modifiers")


def input_command(c) -> dict:
    """A viewer's pointer, wheel, touch or key, rebuilt with only the fields the renderer knows, each checked."""
    if not isinstance(c, dict):
        raise DesignError("an input is an object")
    op = c.get("op")
    xy = lambda v, what: _number(v, -MAX_SIDE, 2 * MAX_SIDE, what)  # noqa: E731 (a drag may leave the picture)
    if op == "mouse":
        if c.get("type") not in MOUSE:
            raise DesignError(f"a mouse type is one of {', '.join(MOUSE)}")
        out = {"op": "mouse", "type": c["type"], "x": xy(c.get("x"), "x"), "y": xy(c.get("y"), "y"), "modifiers": _modifiers(c)}
        if "button" in c:
            if c["button"] not in BUTTONS:
                raise DesignError(f"a button is one of {', '.join(BUTTONS)}")
            out["button"] = c["button"]
        if "buttons" in c:
            out["buttons"] = _integer(c["buttons"], 0, 31, "buttons")
        if "clickCount" in c:
            out["clickCount"] = _integer(c["clickCount"], 0, 3, "clickCount")
        return out
    if op == "wheel":
        return {"op": "wheel", "x": xy(c.get("x"), "x"), "y": xy(c.get("y"), "y"),
                "deltaX": _number(c.get("deltaX", 0), -10000, 10000, "deltaX"), "deltaY": _number(c.get("deltaY", 0), -10000, 10000, "deltaY"),
                "modifiers": _modifiers(c)}
    if op == "touch":
        if c.get("type") not in TOUCH:
            raise DesignError(f"a touch type is one of {', '.join(TOUCH)}")
        points = c.get("points", [])
        if not isinstance(points, list) or len(points) > 10 or not all(isinstance(p, dict) for p in points):
            raise DesignError("points is a list of up to 10 {x, y, id}")
        return {"op": "touch", "type": c["type"], "modifiers": _modifiers(c),
                "points": [{"x": xy(p.get("x"), "x"), "y": xy(p.get("y"), "y"), "id": _integer(p.get("id", i), 0, 1000, "id")}
                           for i, p in enumerate(points)]}
    if op == "key":
        if c.get("type") not in KEY:
            raise DesignError(f"a key type is one of {', '.join(KEY)}")
        out = {"op": "key", "type": c["type"], "modifiers": _modifiers(c)}
        for k in ("key", "code", "text"):
            if k in c:
                if not isinstance(c[k], str) or len(c[k]) > 32:
                    raise DesignError(f"{k} is text of up to 32 characters")
                out[k] = c[k]
        if "keyCode" in c:
            out["keyCode"] = _integer(c["keyCode"], 0, 255, "keyCode")
        return out
    raise DesignError("an input is a mouse, wheel, touch or key")


# --- what a worktree holds ------------------------------------------------------------------------
def _inside(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def projects(worktree: Path) -> list[str]:
    """The design folders: designs/<project>, not hidden, not a symbolic link."""
    base = worktree / "designs"
    if base.is_symlink() or not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if not p.name.startswith(".") and not p.is_symlink() and p.is_dir())


def boards(design: Path) -> list[str]:
    """The boards of a design folder, as the renderer lists them: every *.dc.html below it, but in hidden folders, ds/ and
    node_modules/. Symbolic links aren't followed."""
    found = []
    for root, folders, files in os.walk(design):
        folders[:] = sorted(f for f in folders if not f.startswith(".") and f not in ("ds", "node_modules") and not (Path(root) / f).is_symlink())
        for name in files:
            path = Path(root) / name
            if name.endswith(".dc.html") and not name.startswith(".") and not path.is_symlink():
                found.append(path.relative_to(design).as_posix())
    return sorted(found)


def combinations(worktree: Path) -> dict:
    """The voices, schemes and pens of the worktree's web form, which is what the renderer serves to its boards."""
    path = worktree / "web" / "combinations.json"
    empty = {"voices": [], "schemes": [], "pens": []}
    if path.is_symlink() or not _inside(path, worktree):
        return empty
    try:
        rows = json.loads(path.read_text()).get("combinations")
    except (OSError, ValueError, AttributeError):
        return empty
    seen = {"voices": [], "schemes": [], "pens": []}
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, dict):
            continue
        for key, field in (("voices", "voice"), ("schemes", "scheme"), ("pens", "pen")):
            value = row.get(field)
            if isinstance(value, (str, int)) and not isinstance(value, bool) and value not in seen[key] and len(str(value)) <= 40:
                seen[key].append(value)
    return seen


def _pen(value, pens: list):
    """A pen as the web form names it: the state reads it from an address, so "2" is 2."""
    if isinstance(value, str) and value.isdigit() and int(value) in pens:
        return int(value)
    return value if value in pens else None


def clean_state(raw: dict, known_boards: list[str], choices: dict) -> dict:
    """The renderer's state, which a board steers: only known values pass, the address never does."""
    view = raw.get("view") if raw.get("view") in VIEWS else "other"
    board = raw.get("board") if isinstance(raw.get("board"), str) and raw.get("board") in known_boards else None
    out = {"view": view, "board": board,
           "voice": raw.get("voice") if raw.get("voice") in choices["voices"] else None,
           "scheme": raw.get("scheme") if raw.get("scheme") in choices["schemes"] else None,
           "pen": _pen(raw.get("pen"), choices["pens"]),
           "page": _text(raw["page"], 100) if isinstance(raw.get("page"), str) else None}
    for k in ("width", "height"):
        v = raw.get(k)
        out[k] = v if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= MAX_SIDE else None
    return out


def open_command(args: dict, known_boards: list[str], choices: dict) -> dict:
    """An open of one board, from a viewer or the session, checked against the design folder and its web form."""
    board = args.get("board")
    if not isinstance(board, str) or board not in known_boards:
        raise DesignError(f"no board {_text(board, 120)!r} in this design folder" + (f": it has {', '.join(known_boards[:30])}" if known_boards else ""))
    out = {"op": "open", "board": board}
    for key, field in (("voices", "voice"), ("schemes", "scheme"), ("pens", "pen")):
        value = args.get(field)
        if value is None:
            continue
        if field == "pen":
            value = _pen(value, choices["pens"])
        if value not in choices[key]:
            raise DesignError(f"{field} is one of {', '.join(map(str, choices[key]))}")
        out[field] = value
    for k in ("width", "height"):
        if args.get(k) is not None:
            out[k] = _integer(args[k], 1, MAX_SIDE, k)
    return out


# --- the tools: GlassineOS/ui at a pinned release ------------------------------------------------------
class Tools:
    """A checkout of GlassineOS/ui at the tag in app/ui.ref, in hubd's cache, fetched as app/fetch-ui.sh fetches it."""

    def __init__(self, cache: Path, ref_file: Path, git: str = "git", root: Path | None = None):
        self.cache = cache
        self.ref_file = ref_file
        self.git = git
        self.fixed = root  # a checkout to use as it is, for tests
        self._lock = asyncio.Lock()

    def ref(self) -> str:
        ref = self.ref_file.read_text().strip()
        if not REF_RE.fullmatch(ref):
            raise DesignError(f"app/ui.ref must name a release tag (vX.Y.Z), not {ref!r}")
        return ref

    def all_roots(self) -> list[Path]:
        """Every checkout the hub may have run containers from, so leftovers of any release can be found."""
        if self.fixed:
            return [self.fixed]
        base = self.cache / "ui"
        return sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []

    async def ensure(self) -> Path:
        if self.fixed:
            return self.fixed
        ref = self.ref()
        root = self.cache / "ui" / ref
        async with self._lock:
            if (root / "tools" / "boards").is_file():
                return root
            root.parent.mkdir(parents=True, exist_ok=True)
            tmp = Path(tempfile.mkdtemp(prefix=f".{ref}-", dir=root.parent))
            env = {**os.environ, "GIT_HTTP_LOW_SPEED_LIMIT": "1000", "GIT_HTTP_LOW_SPEED_TIME": "30", "GIT_TERMINAL_PROMPT": "0"}
            try:
                for args in (("init", "-q", str(tmp)), ("-C", str(tmp), "fetch", "-q", "--depth", "1", UI_REPO, f"refs/tags/{ref}"),
                             ("-C", str(tmp), "-c", "advice.detachedHead=false", "checkout", "-q", "FETCH_HEAD")):
                    proc = await asyncio.create_subprocess_exec(self.git, *args, env=env, stdin=asyncio.subprocess.DEVNULL,
                                                                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
                    try:
                        _, err = await asyncio.wait_for(proc.communicate(), 300)
                    except TimeoutError:
                        proc.kill()
                        raise DesignError(f"fetching GlassineOS/ui {ref} took too long") from None
                    if proc.returncode != 0:
                        raise DesignError(f"can't fetch GlassineOS/ui {ref}: {_text(err.decode(errors='replace').strip())}")
                if not (tmp / "tools" / "boards").is_file() or not (tmp / "tools" / "in-alpine").is_file():
                    raise DesignError(f"GlassineOS/ui {ref} has no tools/boards stream")
                tmp.rename(root)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            return root


def stream_command(tools: Path, design: Path, worktree: Path) -> list[str]:
    """The renderer, from the pinned tools, on the worktree's design folder, Interleaf and web form."""
    return [str(tools / "tools" / "in-alpine"), str(tools / "tools" / "boards"), "stream", str(design),
            "--interleaf", str(worktree / "interleaf"), "--web", str(worktree / "web")]


# --- one viewer -------------------------------------------------------------------------------------
class Viewer:
    """A connection to the page: JSON in order, and of the pictures only the newest one not yet sent."""

    def __init__(self, writer: asyncio.StreamWriter):
        self.writer = writer
        self.messages: list[bytes] = []
        self.picture: bytes | None = None
        self.ready = asyncio.Event()
        self.closed = asyncio.Event()  # set when the view itself has closed: the connection ends

    def send(self, message: dict) -> None:
        if len(self.messages) < 200:
            self.messages.append(json.dumps(message).encode())
        self.ready.set()

    def show(self, payload: bytes) -> None:
        self.picture = payload  # a slow page skips pictures, never messages
        self.ready.set()

    async def pump(self) -> None:
        while True:
            await self.ready.wait()
            self.ready.clear()
            while self.messages:
                self.writer.write(frame(FRAME_JSON, self.messages.pop(0)))
            if self.picture is not None:
                payload, self.picture = self.picture, None
                self.writer.write(frame(FRAME_PNG, payload))
            await self.writer.drain()


OPEN_SETTLE = 5.0  # seconds a session's open waits for the renderer to report the board; a first start takes ~4 s
SETTLE_POLL = 0.05


# --- one design view ---------------------------------------------------------------------------------
class View:
    def __init__(self, name: str, worktree: Path, project: str, now: float):
        self.name = name
        self.worktree = worktree
        self.project = project
        self.proc: asyncio.subprocess.Process | None = None
        self.status = "stopped"  # starting, running, crashed, stopped, gone
        self.message = ""
        self.picture: bytes | None = None  # the newest FRAME_PNG payload
        self.state: dict = {}
        self.follow = True
        self.suggestion: dict | None = None
        self.viewers: set[Viewer] = set()
        self.alone_since = now
        self.tasks: list[asyncio.Task] = []
        self.stderr: list[str] = []
        self.stopping = False
        self.write_lock = asyncio.Lock()

    @property
    def design(self) -> Path:
        return self.worktree / "designs" / self.project

    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None


class Designs:
    def __init__(self, agents, tools: Tools, command=stream_command, clock=time.monotonic, docker: str = "docker",
                 env: dict | None = None, idle_stop: float = IDLE_STOP, max_running: int = MAX_RUNNING):
        self.agents = agents
        self.tools = tools
        self.command = command
        self.clock = clock
        self.docker = docker
        self.env = {**os.environ, "BOARDS_NETWORK": "none", **(env or {})}  # FR-018: in a container without network
        self.idle_stop = idle_stop
        self.max_running = max_running
        self.views: dict[str, View] = {}
        self._starting = asyncio.Lock()
        if agents is not None:
            agents.before_remove = self.forget

    # --- which sessions have one --------------------------------------------------------------
    def worktree(self, name) -> Path | None:
        """The ui worktree of a design session, or None if it isn't one or its worktree is gone."""
        if self.agents is None or not isinstance(name, str) or not self.agents.is_session(name):
            return None
        agent = self.agents.describe(name)
        if not agent or agent.get("action") != DESIGN_ACTION:
            return None
        present = self.agents._present(name)
        if not present or not present[0].is_dir():
            return None
        return present[0]

    def is_design(self, name) -> bool:
        return self.worktree(name) is not None

    def _default_project(self, name: str, worktree: Path) -> str | None:
        """The folder named after the issue's repository, if there is one, else the first."""
        found = projects(worktree)
        repo = ((self.agents.describe(name) or {}).get("repo") or "").lstrip(".").lower()
        return repo if repo in found else (found[0] if found else None)

    def _view(self, name: str) -> View:
        view = self.views.get(name)
        if view is None:
            worktree = self.worktree(name)
            if worktree is None:
                raise DesignError(f"{name} is not a design session, or its worktree is gone")
            project = self._default_project(name, worktree)
            if project is None:
                raise DesignError("its worktree has no design folder under designs/")
            view = self.views[name] = View(name, worktree, project, self.clock())
        return view

    def running(self) -> list[str]:
        return sorted(n for n, v in self.views.items() if v.alive())

    # --- what viewers and the session see ------------------------------------------------------
    def summary(self, view: View) -> dict:
        found = boards(view.design) if view.design.is_dir() else []
        return {"t": "view", "name": view.name, "status": view.status, "message": view.message, "project": view.project,
                "projects": projects(view.worktree), "boards": found, **combinations(view.worktree),
                "follow": view.follow, "suggestion": view.suggestion, "viewers": len(view.viewers),
                "state": view.state, "ended": self._ended(view.name), "running": self.running()}

    def _ended(self, name: str) -> bool:
        agent = self.agents.describe(name) if self.agents else None
        return not agent or bool(agent.get("ended"))

    async def _ended_now(self, name: str) -> bool:
        """Claude has ended or its terminal is gone, as the session view says it."""
        try:
            return (await self.agents.session_state(name))["state"] == "Stopped"
        except Exception:  # can't tell: keep it
            return False

    def _tell(self, view: View, message: dict | None = None) -> None:
        message = message or self.summary(view)
        for viewer in list(view.viewers):
            viewer.send(message)

    def _note(self, view: View, words: str) -> None:
        self._tell(view, {"t": "note", "text": _text(words)})

    # --- the renderer -----------------------------------------------------------------------
    async def start(self, name: str, project: str | None = None) -> View:
        async with self._starting:
            view = self._view(name)
            if project is not None and project != view.project:
                if project not in projects(view.worktree):
                    raise DesignError(f"no design folder {_text(project, 60)!r}: there are {', '.join(projects(view.worktree))}")
                await self._halt(view)
                view.project, view.state, view.picture = project, {}, None
            if view.alive():
                return view
            others = [n for n in self.running() if n != name]
            if len(others) >= self.max_running:
                full = Full(others)
                view.status, view.message = "full", str(full)
                self._tell(view)
                raise full
            view.status, view.message, view.stderr, view.stopping = "starting", "", [], False
            self._tell(view)
            try:
                tools = await self.tools.ensure()
                if not view.design.is_dir() or view.design.is_symlink() or not _inside(view.design, view.worktree):
                    raise DesignError(f"designs/{view.project} isn't a folder of the worktree")
                view.proc = await asyncio.create_subprocess_exec(
                    *self.command(tools, view.design, view.worktree), cwd=str(view.worktree), env=self.env, limit=LINE_LIMIT,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)
            except (DesignError, OSError) as e:
                view.status, view.message = "crashed", f"The renderer couldn't start: {_text(e)}"
                self._tell(view)
                raise DesignError(view.message) from e
            view.tasks = [asyncio.ensure_future(self._read(view, view.proc)), asyncio.ensure_future(self._errors(view, view.proc))]
            return view

    async def _send(self, view: View, command: dict) -> None:
        if not view.alive() or view.proc.stdin is None:
            raise DesignError("the renderer isn't running")
        async with view.write_lock:
            try:
                view.proc.stdin.write(json.dumps(command).encode() + b"\n")
                await view.proc.stdin.drain()
            except (ConnectionError, RuntimeError) as e:
                raise DesignError("the renderer isn't running") from e

    async def _errors(self, view: View, proc) -> None:
        while line := await proc.stderr.readline():
            view.stderr = (view.stderr + [_text(line.decode(errors="replace").strip())])[-KEPT_STDERR:]

    async def _read(self, view: View, proc) -> None:
        try:
            while True:
                try:
                    line = await proc.stdout.readline()
                except ValueError:  # longer than LINE_LIMIT: not a frame we'd show
                    continue
                if not line:
                    break
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict):
                    self._event(view, event)
            await proc.wait()
        finally:
            if view.proc is proc and not view.stopping:
                last = next((line for line in reversed(view.stderr) if line), "")
                view.status, view.message = "crashed", "The renderer stopped" + (f": {last}" if last else ".")
                self._tell(view)

    def _event(self, view: View, event: dict) -> None:
        kind = event.get("ev")
        if kind == "ready":
            view.status, view.message = "running", ""
            self._tell(view)
        elif kind == "frame":
            try:
                png = base64.b64decode(event.get("png") or "", validate=True)
                width, height, seq = (_integer(event.get(k), 0, 2**31, k) for k in ("width", "height", "seq"))
            except (ValueError, TypeError, DesignError):
                return
            if not png.startswith(b"\x89PNG\r\n\x1a\n") or len(png) > MAX_PNG:
                return
            view.picture = PICTURE.pack(seq, width, height) + png
            for viewer in list(view.viewers):
                viewer.show(view.picture)
        elif kind == "state":
            state = clean_state(event, boards(view.design) if view.design.is_dir() else [], combinations(view.worktree))
            if state != view.state:
                view.state = state
                self._tell(view)
        elif kind == "crashed":
            view.status, view.message = "crashed", "The renderer stopped: the page is gone."
            self._tell(view)
        elif kind == "error":
            self._note(view, f"The renderer couldn't do that: {_text(event.get('message', ''))}")
        elif kind == "blocked":
            self._note(view, f"A board asked for {_text(event.get('url', ''), 120)} and was refused.")

    async def _halt(self, view: View) -> None:
        """Ends the renderer: the end of its input first, as its protocol says, then the process, then its container."""
        proc = view.proc
        view.stopping = True
        if proc is not None and proc.returncode is None:
            try:
                proc.stdin.close()
            except (OSError, RuntimeError):
                pass
            try:
                await asyncio.wait_for(proc.wait(), STOP_WAIT)
            except TimeoutError:
                for sig in ("terminate", "kill"):
                    try:
                        getattr(proc, sig)()
                        await asyncio.wait_for(proc.wait(), STOP_WAIT)
                        break
                    except ProcessLookupError:
                        break
                    except TimeoutError:
                        continue
        for task in view.tasks:
            task.cancel()
        await asyncio.gather(*view.tasks, return_exceptions=True)
        view.tasks = []
        if proc is not None:
            await self._remove_containers(view.worktree)
        view.proc = None

    async def _docker(self, *args: str) -> tuple[int, str]:
        try:
            proc = await asyncio.create_subprocess_exec(self.docker, *args, stdin=asyncio.subprocess.DEVNULL,
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        except OSError:
            return 127, ""
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), 30)
        except TimeoutError:
            proc.kill()
            return 124, ""
        return proc.returncode, out.decode(errors="replace")

    async def _ours(self) -> dict[str, list[str]]:
        """The hub's renderer containers, by id, with their mount sources: any container mounting a tools checkout."""
        found: dict[str, list[str]] = {}
        for root in self.tools.all_roots():
            code, out = await self._docker("ps", "-q", "--no-trunc", "--filter", f"volume={root}")
            for cid in out.split() if code == 0 else ():
                code, mounts = await self._docker("inspect", "--format", "{{range .Mounts}}{{.Source}}\n{{end}}", cid)
                found[cid] = mounts.split() if code == 0 else []
        return found

    async def _remove_containers(self, worktree: Path | None) -> None:
        """A renderer's container, if the end of its client didn't take it away; with no worktree, all of the hub's."""
        ours = await self._ours()
        doomed = [cid for cid, mounts in ours.items() if worktree is None or str(worktree) in mounts]
        if doomed:
            await self._docker("rm", "-f", *doomed)

    async def reap(self) -> None:
        """On hubd's start: renderers of an earlier hubd have no client any more."""
        await self._remove_containers(None)

    async def stop(self, name: str) -> None:
        view = self.views.get(name)
        if view is None:
            return
        await self._halt(view)
        view.status, view.message = "stopped", ""
        self._tell(view)

    async def forget(self, name: str) -> None:
        """Before a session's worktree is removed: the renderer goes first, and the view says why it closes."""
        view = self.views.pop(name, None)
        if view is None:
            return
        await self._halt(view)
        view.status, view.message = "gone", "The session's worktree was removed, so the design view has closed."
        self._tell(view)
        for viewer in list(view.viewers):
            viewer.closed.set()

    async def tick(self) -> None:
        """Stops a renderer whose session has ended and that no one has watched for idle_stop seconds (FR-017)."""
        now = self.clock()
        for name, view in list(self.views.items()):
            if self.worktree(name) is None:
                await self.forget(name)
            elif view.alive() and not view.viewers and now - view.alone_since >= self.idle_stop and await self._ended_now(name):
                log.info("stopping the design view of %s: ended, and no viewer for %d s", name, self.idle_stop)
                await self.stop(name)

    # --- the session's tools (FR-014, FR-015) -------------------------------------------------------
    async def session_open(self, name: str, args: dict) -> dict:
        view = self._view(name)
        project = args.get("project")
        if project is not None and (not isinstance(project, str) or project not in projects(view.worktree)):
            raise DesignError(f"no design folder {_text(project, 60)!r}: there are {', '.join(projects(view.worktree))}")
        target = view.worktree / "designs" / (project or view.project)
        command = open_command(args, boards(target), combinations(view.worktree))
        wanted = {**{k: command.get(k) for k in ("board", "voice", "scheme", "pen", "width", "height")}, "project": project or view.project}
        if not view.follow:
            view.suggestion = wanted
            self._tell(view)
            return {"shown": False, "why": "the viewer has turned follow off: it shows as your suggestion", **self.session_view(name)}
        try:
            await self.start(name, project)
        except Full as e:
            raise DesignError(str(e)) from None
        view.suggestion = None
        await self._send(view, command)
        self._tell(view)
        shown = await self._settled(view, command)
        reply = {"shown": True, **self.session_view(name)}
        if not shown:
            reply["message"] = reply["message"] or f"the renderer hadn't shown {command['board']} within {OPEN_SETTLE:g} s: what it shows now is below"
        return reply

    async def _settled(self, view: View, command: dict) -> bool:
        """Waits until the renderer reports the opened board (and the asked choices), so the reply says what is shown."""
        def there() -> bool:
            state = view.state
            return state.get("board") == command["board"] and all(
                state.get(k) == command[k] for k in ("voice", "scheme", "pen", "width", "height") if k in command)
        loop = asyncio.get_running_loop()  # real time: the idle clock may be a test's
        deadline = loop.time() + OPEN_SETTLE
        while not there():
            if not view.alive() or loop.time() >= deadline:
                return False
            await asyncio.sleep(SETTLE_POLL)
        return True

    async def session_look(self, name: str) -> dict:
        """What the view shows, starting the renderer if it isn't running (FR-017: a tool call starts it)."""
        view = self._view(name)
        if not view.alive() and view.status != "crashed":
            try:
                await self.start(name)
            except DesignError:
                pass  # renderer says why
        return self.session_view(name)

    def session_view(self, name: str) -> dict:
        view = self._view(name)
        state = view.state
        size = {"width": state["width"], "height": state["height"]} if state.get("width") else None
        return {"project": view.project, "showing": state.get("view"), "board": state.get("board"), "voice": state.get("voice"),
                "scheme": state.get("scheme"), "pen": state.get("pen"), "size": size, "follow": view.follow,
                "viewers": len(view.viewers), "renderer": view.status, "message": view.message or None,
                "note": "What a board's own links and clicks led to is read from the renderer: a board name or a choice outside the folder's shows as null."}

    # --- a viewer ---------------------------------------------------------------------------
    async def attach(self, name, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, ok) -> None:
        """A page's connection, from after the login check: ok(reply) answers the request line."""
        try:
            view = self._view(name)
        except DesignError as e:
            await ok({"ok": False, "error": str(e)})
            return
        await ok({"ok": True})
        viewer = Viewer(writer)
        view.viewers.add(viewer)
        pump = asyncio.ensure_future(viewer.pump())
        try:
            await self._first_look(view, viewer)
            self._tell(view)
            reading = asyncio.ensure_future(self._listen(view, viewer, reader))
            closing = asyncio.ensure_future(viewer.closed.wait())
            await asyncio.wait([reading, closing], return_when=asyncio.FIRST_COMPLETED)
            for task in (reading, closing):
                task.cancel()
            await asyncio.gather(reading, closing, return_exceptions=True)
            if viewer.closed.is_set():  # what the view said last goes out before the end
                viewer.ready.set()
                await asyncio.sleep(0)
                await asyncio.wait_for(self._flush(viewer), STOP_WAIT)
        except (asyncio.IncompleteReadError, ConnectionError, TimeoutError):
            pass
        finally:
            view.viewers.discard(viewer)
            if not view.viewers:
                view.alone_since = self.clock()
            pump.cancel()
            await asyncio.gather(pump, return_exceptions=True)
            self._tell(view)
            try:
                writer.write(frame(FRAME_EXIT))
                await writer.drain()
            except (ConnectionError, RuntimeError):
                pass

    async def _flush(self, viewer: Viewer) -> None:
        while viewer.messages or viewer.picture is not None:
            await asyncio.sleep(0.01)
        await viewer.writer.drain()

    async def _listen(self, view: View, viewer: Viewer, reader: asyncio.StreamReader) -> None:
        try:
            while True:
                kind, length = _HEADER.unpack(await reader.readexactly(_HEADER.size))
                if length > MAX_IN:
                    return
                payload = await reader.readexactly(length)
                if kind == FRAME_EXIT:
                    return
                if kind != FRAME_JSON:
                    continue
                try:
                    message = json.loads(payload)
                    await self._from_viewer(view, viewer, message if isinstance(message, dict) else {})
                except (ValueError, DesignError) as e:
                    viewer.send({"t": "note", "text": _text(e)})
        except (asyncio.IncompleteReadError, ConnectionError):
            return

    async def _first_look(self, view: View, viewer: Viewer) -> None:
        """A new viewer gets where things stand and the newest picture, and the renderer starts if it isn't running."""
        if not view.alive() and view.status != "crashed":
            try:
                await self.start(view.name)
            except DesignError:
                pass  # the summary says what went wrong, and a "full" one which are running
        viewer.send(self.summary(view))
        if view.picture is not None:
            viewer.show(view.picture)

    async def _from_viewer(self, view: View, viewer: Viewer, m: dict) -> None:
        t = m.get("t")
        if t == "input":
            if view.alive():
                await self._send(view, input_command(m.get("input")))
        elif t == "open":
            command = open_command(m, boards(view.design), combinations(view.worktree))
            await self._send(view, command)
        elif t == "canvas":
            page = m.get("page")
            await self._send(view, {"op": "canvas", **({"page": _text(page, 100)} if isinstance(page, str) and page else {})})
        elif t == "viewport":
            await self._send(view, {"op": "viewport", "width": _integer(m.get("width"), 1, MAX_SIDE, "width"),
                                    "height": _integer(m.get("height"), 1, MAX_SIDE, "height")})
        elif t == "frame":
            await self._send(view, {"op": "frame"})
        elif t == "follow":
            if not isinstance(m.get("on"), bool):
                raise DesignError("follow is on or off")
            view.follow = m["on"]
            self._tell(view)
        elif t == "take":  # the session's suggestion, opened now
            wanted = view.suggestion
            if wanted:
                view.suggestion = None
                await self.start(view.name, wanted["project"])
                await self._send(view, open_command(wanted, boards(view.design), combinations(view.worktree)))
                self._tell(view)
        elif t == "project":
            await self._start_for(view, viewer, m.get("name"))
        elif t in ("restart", "start"):
            if t == "restart":
                await self._halt(view)
            await self._start_for(view, viewer, None)
        elif t == "stop_other":  # FR-017: the way past the limit, from the page that hit it
            other = m.get("name")
            if other not in self.running() or other == view.name:
                raise DesignError("that design view isn't running")
            await self.stop(other)
            await self._start_for(view, viewer, None)
        else:
            raise DesignError("unknown message")

    async def _start_for(self, view: View, viewer: Viewer, project) -> None:
        if project is not None and not isinstance(project, str):
            raise DesignError("a design folder is named")
        try:
            await self.start(view.name, project)
        except Full:
            return  # start told every viewer
        self._tell(view)


class Full(DesignError):
    def __init__(self, names: list[str]):
        super().__init__(f"{len(names)} design views are running ({', '.join(names)}): stop one to open this one")
        self.names = names
