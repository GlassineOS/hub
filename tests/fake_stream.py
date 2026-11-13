# SPDX-License-Identifier: GPL-2.0-or-later
"""A stand-in for GlassineOS/ui's `tools/boards stream`: the same JSON lines, no browser, no Docker.

Each command it reads is appended to $FAKE_STREAM_LOG. The first frame is larger than 64 KiB, as real ones are.
$FAKE_STREAM_CRASH_ON names a command op that makes it exit with an error on stderr. $FAKE_STREAM_STATE, as JSON, is
merged into every state it reports (a board steering the page somewhere else)."""
import base64
import json
import os
import random
import struct
import sys
import zlib


def png(width: int, height: int, noise: bool = False) -> bytes:
    rng = random.Random(width * 7 + height)
    rows = b"".join(b"\x00" + (bytes(rng.getrandbits(8) for _ in range(width * 3)) if noise else b"\xff" * width * 3) for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


seq = 0
size = [1280, 800]
state = {"ev": "state", "view": "canvas", "width": 1280, "height": 800, "url": "/_boards/"}


def out(event: dict) -> None:
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()


def frame(noise: bool = False) -> None:
    global seq
    seq += 1
    w, h = (200, 200) if noise else (40, 30)
    out({"ev": "frame", "seq": seq, "width": w, "height": h, "png": base64.b64encode(png(w, h, noise)).decode()})


def report() -> None:
    out({**state, **json.loads(os.environ.get("FAKE_STREAM_STATE") or "{}")})


out({"ev": "ready", "url": "http://127.0.0.1:4790/"})
report()
frame(noise=True)
for line in sys.stdin:
    command = json.loads(line)
    with open(os.environ.get("FAKE_STREAM_LOG", os.devnull), "a") as log:
        log.write(json.dumps(command) + "\n")
    op = command.get("op")
    if op == os.environ.get("FAKE_STREAM_CRASH_ON"):
        sys.stderr.write("chromium went away\n")
        sys.exit(3)
    if op == "open":
        state = {"ev": "state", "view": "board", "board": command["board"], "width": command.get("width", 320), "height": command.get("height", 240),
                 "url": "/" + command["board"], **{k: str(command[k]) for k in ("voice", "scheme", "pen") if k in command}}
        report()
    elif op == "canvas":
        state = {"ev": "state", "view": "canvas", "width": 1280, "height": 800, "url": "/_boards/"}
        report()
    elif op == "state":
        report()
    elif op == "frame" or op in ("mouse", "key", "touch", "wheel"):
        pass
    else:
        out({"ev": "error", "op": op, "message": "unknown command"})
        continue
    frame()
