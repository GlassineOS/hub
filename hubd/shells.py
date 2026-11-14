# SPDX-License-Identifier: GPL-2.0-or-later
"""Interactive host shells: tmux sessions on hubd's own tmux server.

The sessions belong to tmux, so they outlive the browser, the app and hubd. Attach from
a normal terminal with `tmux -L glassine-hub attach -t NAME`. The separate server keeps
the hub away from any tmux sessions the user runs for themselves.
"""
from __future__ import annotations

import asyncio
import fcntl
import json
import os
import pty
import re
import shlex
import shutil
import signal
import struct
import subprocess
import termios
from pathlib import Path

TMUX_SERVER = "glassine-hub"
PASTE_SETTLE = 0.4  # seconds
_PROMPT_MARKS = "❯>"
_ESCAPE = re.compile(r"\x1b(?:\[([0-9;:]*)([@-~])|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-_])")  # CSI, OSC, or a two-byte one
_NAME_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")
_FORMAT = "#{session_name}\t#{session_created}\t#{session_attached}\t#{session_windows}\t#{pane_current_path}\t#{pane_current_command}"

# Frames on the attached connection: type (1 byte), length (4 bytes, big endian), payload.
FRAME_DATA = 0
FRAME_RESIZE = 1
FRAME_EXIT = 2
_HEADER = struct.Struct(">BI")
MAX_FRAME = 1024 * 1024


class ShellError(Exception):
    pass


def _cells(line: str) -> list[tuple[str, bool, bool]]:
    """A captured line as (character, dim, reverse) cells, its escapes taken out. Only SGR changes the two: 2 and 7 set them,
    22, 27 and 0 (or no parameter) clear them."""
    cells, dim, reverse, at = [], False, False, 0
    for m in _ESCAPE.finditer(line):
        cells += [(c, dim, reverse) for c in line[at:m.start()]]
        at = m.end()
        if m.group(2) != "m":
            continue
        params, i = (m.group(1) or "").split(";"), 0
        while i < len(params):
            p = params[i].split(":")[0]
            i += 1
            if p in ("38", "48", "58"):  # a colour: its values could read as 2 or 7
                if ":" not in params[i - 1] and i < len(params):
                    i += {"5": 2, "2": 4}.get(params[i], 1)
            elif p in ("", "0"):
                dim = reverse = False
            elif p == "2":
                dim = True
            elif p == "22":
                dim = False
            elif p == "7":
                reverse = True
            elif p == "27":
                reverse = False
    cells += [(c, dim, reverse) for c in line[at:]]
    return cells


def _empty_after_mark(line: str) -> bool:
    """A prompt line with nothing typed: the marker alone, or followed only by dim text (Claude Code's suggested next
    prompt, which a paste replaces) and the cursor's reversed cell over its first character."""
    cells = _cells(line)
    text = [c for c, _d, _r in cells]
    first = next((i for i, c in enumerate(text) if not c.isspace()), None)
    if first is None or text[first] not in _PROMPT_MARKS:
        return False
    after = [cell for cell in cells[first + 1:] if not cell[0].isspace()]
    if after and after[0][2] and not after[0][1] and len(after) > 1 and all(d for _c, d, _r in after[1:]):
        after = after[1:]  # the cursor on the suggestion's first letter
    return all(d for _c, d, _r in after)


def prompt_empty_in(captured: str) -> bool:
    """Whether a pane, captured with its attributes (capture-pane -e), shows a prompt with nothing typed."""
    return any(_empty_after_mark(line) for line in captured.splitlines())


def frame(kind: int, payload: bytes = b"") -> bytes:
    return _HEADER.pack(kind, len(payload)) + payload


def _check_name(name) -> str:
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        raise ShellError("a session name is 1-40 letters, digits, _ or -")
    return name


class Shells:
    def __init__(self, program: str = "tmux", env: dict | None = None, default_cwd: str | None = None):
        self.program = program
        self.env = dict(env or {})
        self.default_cwd = default_cwd or str(Path.home())

    def available(self) -> bool:
        return shutil.which(self.program) is not None

    async def _tmux(self, *args: str, stdin: bytes | None = None) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            self.program, "-L", TMUX_SERVER, *args,
            stdin=asyncio.subprocess.DEVNULL if stdin is None else asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate(stdin)
        return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")

    async def list(self) -> list[dict]:
        if not self.available():
            raise ShellError("tmux is not installed on the host")
        rc, out, _ = await self._tmux("list-sessions", "-F", _FORMAT)
        if rc != 0:  # no server yet = no sessions
            return []
        sessions = []
        for line in out.splitlines():
            name, created, attached, windows, cwd, command = (line.split("\t") + [""] * 6)[:6]
            sessions.append({"name": name, "created": int(created or 0), "attached": int(attached or 0),
                             "windows": int(windows or 0), "cwd": cwd, "command": command})
        return sessions

    async def new(self, name, cwd=None, command=None) -> dict:
        if not self.available():
            raise ShellError("tmux is not installed on the host")
        name = _check_name(name)
        cwd = os.path.expanduser(cwd or self.default_cwd)
        if not os.path.isdir(cwd):
            raise ShellError(f"no such directory: {cwd}")
        shell = os.environ.get("SHELL", "/bin/sh")
        args = ["new-session", "-d", "-s", name, "-c", cwd, "-x", "120", "-y", "40"]
        for key, value in self.env.items():
            args += ["-e", f"{key}={value}"]
        if command:
            if not isinstance(command, str):
                raise ShellError("command must be text")
            # A login shell, so the session gets the user's normal environment; the shell
            # stays when the command ends, with its output still on screen.
            script = f"{command}\nexec {shlex.quote(shell)} -l"
            args += [shell, "-lc", script]
        else:
            args += [shell, "-l"]
        rc, _, err = await self._tmux(*args)
        if rc != 0:
            raise ShellError(err.strip() or "tmux failed")
        await self._terminal_options()
        return {"name": name}

    async def _terminal_options(self) -> None:
        """The same terminal whatever the host's tmux config says, and again for each new server."""
        # The wheel scrolls tmux's history and a drag selects in it.
        await self._tmux("set-option", "-g", "mouse", "on")
        # A selection reaches the browser's clipboard; what runs inside can't write there itself.
        await self._tmux("set-option", "-s", "set-clipboard", "external")

    async def paste(self, name, text: str) -> None:
        """As if typed and sent. Only for a session known to be at its prompt: Enter would answer a question.
        The words go to tmux on stdin, never as an argument, where the process list would show them (004 FR-008)."""
        target, buffer = f"={_check_name(name)}:", f"hub-{name}"
        for args, data in ((("load-buffer", "-b", buffer, "-"), text.encode()), (("paste-buffer", "-p", "-d", "-b", buffer, "-t", target), None)):
            rc, _, err = await self._tmux(*args, stdin=data)
            if rc != 0:
                raise ShellError(err.strip() or "tmux refused the text")
        await asyncio.sleep(PASTE_SETTLE)  # right after a paste, Enter would be taken as part of it
        rc, _, err = await self._tmux("send-keys", "-t", target, "Enter")
        if rc != 0:
            raise ShellError(err.strip() or "tmux refused the key")

    async def prompt_empty(self, name) -> bool:
        """Whether its prompt is on screen with nothing typed. A draft, a picker or anything else: no. Read with its
        attributes, as a suggested next prompt is drawn dim where a draft would be (prompt_empty_in)."""
        rc, out, _ = await self._tmux("capture-pane", "-e", "-p", "-t", f"={_check_name(name)}:")
        return rc == 0 and prompt_empty_in(out)

    async def interrupt(self, name) -> None:
        """Esc, never Ctrl-C: Claude Code stops the turn and keeps the session."""
        rc, _, err = await self._tmux("send-keys", "-t", f"={_check_name(name)}:", "Escape")
        if rc != 0:
            raise ShellError(err.strip() or "tmux refused the key")

    async def kill(self, name) -> None:
        rc, _, err = await self._tmux("kill-session", "-t", f"={_check_name(name)}")
        if rc != 0:
            raise ShellError(err.strip() or "tmux failed")

    async def attach(self, name, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Bridges a PTY running `tmux attach` to the framed connection until either ends."""
        name = _check_name(name)
        rc, _, _ = await self._tmux("has-session", "-t", f"={name}")
        if rc != 0:
            raise ShellError(f"no such session: {name}")
        env = dict(os.environ, TERM="xterm-256color")
        master, slave = pty.openpty()
        # setsid --ctty, not pty.fork: hubd has threads, and the terminal must be the
        # client's controlling one for resizes to reach it.
        try:
            proc = subprocess.Popen(
                ["setsid", "--ctty", self.program, "-L", TMUX_SERVER, "attach-session", "-t", f"={name}"],
                stdin=slave, stdout=slave, stderr=slave, env=env, close_fds=True)
        except OSError as e:
            os.close(master)
            raise ShellError(f"can't start the terminal: {e}") from e
        finally:
            os.close(slave)
        os.set_blocking(master, False)
        loop = asyncio.get_running_loop()
        output: asyncio.Queue = asyncio.Queue(maxsize=64)

        def on_readable():
            try:
                data = os.read(master, 65536)
            except BlockingIOError:
                return
            except OSError:
                data = b""
            try:
                output.put_nowait(data)
            except asyncio.QueueFull:
                # A slow browser: stop reading until it catches up, tmux keeps the state.
                loop.remove_reader(master)
                loop.create_task(_resume(data))
            if not data:
                loop.remove_reader(master)

        async def _resume(data):
            await output.put(data)
            if data:
                loop.add_reader(master, on_readable)

        async def pump_out():
            while True:
                data = await output.get()
                if not data:
                    return
                writer.write(frame(FRAME_DATA, data))
                await writer.drain()

        async def pump_in():
            while True:
                kind, length = _HEADER.unpack(await reader.readexactly(_HEADER.size))
                if length > MAX_FRAME:
                    return
                payload = await reader.readexactly(length)
                if kind == FRAME_DATA:
                    await _write_all(master, payload)
                elif kind == FRAME_RESIZE:
                    size = json.loads(payload)
                    fcntl.ioctl(master, termios.TIOCSWINSZ,
                                struct.pack("HHHH", int(size["rows"]), int(size["cols"]), 0, 0))

        loop.add_reader(master, on_readable)
        tasks = [asyncio.create_task(pump_out()), asyncio.create_task(pump_in())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            loop.remove_reader(master)
            os.close(master)
            # Ends this client only: the tmux session keeps running.
            proc.send_signal(signal.SIGHUP)
            await loop.run_in_executor(None, proc.wait)
            try:
                writer.write(frame(FRAME_EXIT))
                await writer.drain()
            except (ConnectionError, RuntimeError):
                pass


async def _write_all(fd: int, data: bytes) -> None:
    while data:
        try:
            data = data[os.write(fd, data):]
        except BlockingIOError:
            await asyncio.sleep(0.01)
