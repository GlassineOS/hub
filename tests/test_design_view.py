# SPDX-License-Identifier: GPL-2.0-or-later
"""The design view's page side (011): the WebSocket's rules (FR-016), the relay, the tools' listing, and the view's code."""
import asyncio
import json
import re
import shutil
import socket
import struct
import subprocess
import threading
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.hub import tools, web
from app.hub.github import GitHub
from app.hub.hubd_client import DESIGN, FRAME_EXIT, FRAME_JSON, FRAME_PNG, HEADER, SEES, HubdError
from test_app import CONFIG, ORIGIN, FakeDocs, FakeHubd, signed_in

APP = Path(__file__).resolve().parents[1] / "app" / "hub" / "static" / "app.js"
NODE = shutil.which("node")


def _read(sock: socket.socket, n: int) -> bytes:
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError
        data += chunk
    return data


class RelayHubd(FakeHubd):
    """hubd's end of a design view on a socket pair: it says what the test tells it to, and keeps what reaches it."""

    def __init__(self):
        super().__init__()
        self.attached = []
        self.received = []
        self.refuse = None
        self.done = threading.Event()

    async def attach(self, token, name, op="shell.attach"):
        self.attached.append((token, name, op))
        if self.refuse:
            raise self.refuse
        ours, theirs = socket.socketpair()

        def host():
            theirs.sendall(HEADER.pack(FRAME_JSON, len(b'{"t": "view", "status": "running"}')) + b'{"t": "view", "status": "running"}')
            picture = struct.pack(">III", 7, 40, 30) + b"\x89PNG\r\n\x1a\n<script>alert(1)</script>"
            theirs.sendall(HEADER.pack(FRAME_PNG, len(picture)) + picture)
            try:
                while True:
                    kind, length = HEADER.unpack(_read(theirs, HEADER.size))
                    payload = _read(theirs, length)
                    self.received.append((kind, payload))
                    if kind == FRAME_EXIT:
                        break
            except (ConnectionError, OSError):
                pass
            self.done.set()
            theirs.close()
        threading.Thread(target=host, daemon=True).start()
        return await asyncio.open_connection(sock=ours)


@pytest.fixture
def relay():
    hubd = RelayHubd()
    client = TestClient(web.build(hubd, GitHub(hubd, CONFIG), FakeDocs(), secure_cookie=False, allowed_hosts={"testserver"}))
    return client, hubd


def test_the_view_refuses_other_origins_and_no_login(relay):
    client, hubd = relay
    with pytest.raises(WebSocketDisconnect) as e:  # no cookie
        with client.websocket_connect("/api/designs/design-7/view", headers=ORIGIN):
            pass
    assert e.value.code == 4403
    signed_in(client)
    for headers in ({"origin": "http://evil.example"}, {}):
        with pytest.raises(WebSocketDisconnect) as e:
            with client.websocket_connect("/api/designs/design-7/view", headers=headers):
                pass
        assert e.value.code == 4403
    assert hubd.attached == []  # refused before hubd is asked


def test_hubd_s_refusal_closes_the_view(relay):
    client, hubd = relay
    signed_in(client)
    hubd.refuse = HubdError("implement-3 is not a design session")
    with client.websocket_connect("/api/designs/implement-3/view", headers=ORIGIN) as ws:
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_text()
    assert e.value.code == 4404 and "not a design session" in e.value.reason
    hubd.refuse = HubdError("login required", denied=True)
    with client.websocket_connect("/api/designs/x/view", headers=ORIGIN) as ws:
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_text()
    assert e.value.code == 4401


def test_the_relay_passes_pictures_as_bytes_words_as_text_and_only_json_objects_back(relay):
    client, hubd = relay
    signed_in(client)
    with client.websocket_connect("/api/designs/design-7/view", headers=ORIGIN) as ws:
        assert json.loads(ws.receive_text()) == {"t": "view", "status": "running"}
        picture = ws.receive_bytes()
        assert struct.unpack(">III", picture[:12]) == (7, 40, 30) and picture[12:20] == b"\x89PNG\r\n\x1a\n"
        ws.send_bytes(b"raw bytes go nowhere")
        ws.send_text("not json")
        ws.send_text("[1, 2]")
        ws.send_text(json.dumps({"t": "pad", "x": "y" * 20000}))  # over the size a viewer's message has
        ws.send_text(json.dumps({"t": "input", "input": {"op": "mouse", "type": "mousePressed", "x": 1, "y": 2}}))
        ws.close()  # the viewer leaves; leaving the block instead would cancel the relay mid-close
        assert hubd.done.wait(10)
    assert hubd.attached == [("good", "design-7", "design.attach")]
    assert hubd.received == [(FRAME_JSON, json.dumps({"t": "input", "input": {"op": "mouse", "type": "mousePressed", "x": 1, "y": 2}}).encode()),
                             (FRAME_EXIT, b"")]


# --- the tools ----------------------------------------------------------------------------------------
def listed(design: bool, sees=None) -> set[str]:
    hubd = FakeHubd()
    mcp = tools.build(GitHub(hubd, CONFIG), FakeDocs())

    async def go():
        DESIGN.set(design)
        SEES.set(sees)
        return {t.name for t in await mcp.list_tools()}
    return asyncio.run(go())


def test_only_a_design_session_lists_the_design_tools():
    assert {"design_open", "design_view"} <= listed(True)
    assert not {"design_open", "design_view"} & listed(False)  # a full session of another action, or a hub shell
    assert listed(True, sees=["overview"]) == {"overview"}


def test_the_tools_send_the_caller_s_token_and_no_name():
    hubd = FakeHubd()
    calls = []

    async def call(**request):
        calls.append(request)
        return {"ok": True, "shown": True}
    hubd.call = call
    github = GitHub(hubd, CONFIG)
    from app.hub.hubd_client import CALLER

    async def go():
        CALLER.set("token-of-the-caller")
        await github.design_open("Main.dc.html", scheme="eink", pen=2)
        await github.design_view()
    asyncio.run(go())
    assert calls[0] == {"op": "design.open", "agent_token": "token-of-the-caller", "board": "Main.dc.html", "voice": None, "scheme": "eink",
                        "pen": 2, "width": None, "height": None, "project": None}
    assert calls[1] == {"op": "design.view", "agent_token": "token-of-the-caller"}
    params = {t.name: t for t in asyncio.run(tools.build(github, FakeDocs()).every_tool())}
    for name in ("design_open", "design_view"):
        assert "name" not in params[name].input_schema.get("properties", {})  # a session can't name another's view


# --- the view's code ------------------------------------------------------------------------------------
def _function(name: str) -> str:
    match = re.search(rf"^function {name}\(.*?^}}$", APP.read_text(), re.S | re.M)
    assert match, f"no top-level function {name} in app.js"
    return match.group(0)


def _run(names, body: str, prelude: str = ""):
    script = prelude + "\n".join(_function(n) for n in names) + f"\nconsole.log(JSON.stringify((() => {{ {body} }})()));"
    return json.loads(subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30, check=True).stdout)


needs_node = pytest.mark.skipif(NODE is None, reason="node isn't installed")


@needs_node
def test_a_frame_is_shown_at_100_percent_when_it_fits_and_scaled_down_otherwise():
    got = _run(["designScale"], """
        const f = { width: 800, height: 600 };
        return [designScale(f, { width: 1200, height: 900 }, false), designScale(f, { width: 400, height: 900 }, false),
                designScale(f, { width: 1200, height: 300 }, false), designScale(f, { width: 400, height: 300 }, true),
                designScale(null, { width: 10, height: 10 }, false)];""")
    assert got == [1, 0.5, 0.5, 1, 1]


@needs_node
def test_a_pointer_maps_back_to_frame_pixels():
    got = _run(["designPoint"], """
        const f = { width: 800, height: 600 };
        return [designPoint(110, 220, { left: 10, top: 20, width: 400, height: 300 }, f),   // drawn at 50 %
                designPoint(10, 20, { left: 10, top: 20, width: 800, height: 600 }, f),    // at 100 %, the corner
                designPoint(810, 620, { left: 10, top: 20, width: 800, height: 600 }, f)];""")
    assert got == [{"x": 200, "y": 400}, {"x": 0, "y": 0}, {"x": 800, "y": 600}]


@needs_node
def test_keys_become_the_renderer_s_key_input():
    got = _run(["designModifiers", "designKey"], """
        const k = (o) => designKey({ type: "keydown", altKey: false, ctrlKey: false, metaKey: false, shiftKey: false, code: "", keyCode: 0, ...o });
        return [k({ key: "a", code: "KeyA", keyCode: 65 }), k({ key: "A", code: "KeyA", keyCode: 65, shiftKey: true }),
                k({ key: "Enter", code: "Enter", keyCode: 13 }), k({ key: "Backspace", code: "Backspace", keyCode: 8 }),
                k({ key: "c", code: "KeyC", keyCode: 67, ctrlKey: true }), k({ type: "keyup", key: "a", code: "KeyA", keyCode: 65 })];""")
    assert got == [
        {"op": "key", "type": "keyDown", "key": "a", "code": "KeyA", "modifiers": 0, "keyCode": 65, "text": "a"},
        {"op": "key", "type": "keyDown", "key": "A", "code": "KeyA", "modifiers": 8, "keyCode": 65, "text": "A"},
        {"op": "key", "type": "keyDown", "key": "Enter", "code": "Enter", "modifiers": 0, "keyCode": 13, "text": "\r"},
        {"op": "key", "type": "rawKeyDown", "key": "Backspace", "code": "Backspace", "modifiers": 0, "keyCode": 8},
        {"op": "key", "type": "rawKeyDown", "key": "c", "code": "KeyC", "modifiers": 2, "keyCode": 67},
        {"op": "key", "type": "keyUp", "key": "a", "code": "KeyA", "modifiers": 0, "keyCode": 65}]


@needs_node
def test_esc_twice_or_f6_leaves_the_picture_and_one_esc_goes_to_the_board():
    got = _run(["designLeave"], """
        const e = (key, o) => ({ key, shiftKey: false, repeat: false, ...o });
        const first = designLeave(e("Escape"), 0, 1000);
        return [first, designLeave(e("Escape"), first.lastEsc, 1500), designLeave(e("Escape"), first.lastEsc, 2500),
                designLeave(e("a"), first.lastEsc, 1100), designLeave(e("F6"), 0, 1), designLeave(e("F6", { shiftKey: true }), 0, 1),
                designLeave(e("Escape", { repeat: true }), 1000, 1100)];""", prelude="const DESIGN_ESC_TWICE = 800;\n")
    assert got == [{"step": 0, "lastEsc": 1000}, {"step": -1, "lastEsc": 0}, {"step": 0, "lastEsc": 2500},
                   {"step": 0, "lastEsc": 0}, {"step": 1, "lastEsc": 0}, {"step": -1, "lastEsc": 0}, {"step": 0, "lastEsc": 0}]


@needs_node
def test_a_picture_message_is_read_as_header_and_png_bytes():
    got = _run(["designPicture"], """
        const b = new ArrayBuffer(16); const d = new DataView(b);
        d.setUint32(0, 7); d.setUint32(4, 800); d.setUint32(8, 600); d.setUint8(12, 0x89);
        const p = designPicture(b);
        return [p.seq, p.width, p.height, p.png.length, p.png[0]];""")
    assert got == [7, 800, 600, 4, 0x89]


def _design_source() -> str:
    text = APP.read_text()
    start = text.index("// --- the design view (011")
    return text[start:text.index("// --- SessionView (004", start)]


def test_the_view_never_puts_board_html_into_the_hub_s_page():
    """FR-012, SC-004: the page draws PNG bytes on a canvas and sends input. No markup, frame or script from the renderer."""
    source = _design_source()
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "DOMParser", "createContextualFragment", "srcdoc", "<iframe", "iframe",
                   "document.write", "dangerouslySetInnerHTML", "<${Md}", "eval(", "new Function", "<img", "URL.createObjectURL", "window.open", "location ="):
        assert banned not in source, banned
    assert 'createImageBitmap(new Blob([p.png], { type: "image/png" }))' in source
    assert "drawImage(bitmap" in source
    # the whole page has no frame or embed a board's page could ride in, and the CSP still allows no other origin
    text = APP.read_text()
    assert "<iframe" not in text and "<embed" not in text and "<object" not in text
    assert "frame-src" not in web.CSP and "default-src 'self'" in web.CSP and "blob:" not in web.CSP


@needs_node
def test_words_from_the_renderer_end_up_as_text():
    """A board name or note full of markup stays text: htm puts a hole's string into a text node, never parses it."""
    vendor = APP.parent / "vendor" / "preact-htm.js"
    if not vendor.exists():
        pytest.skip("the browser libraries aren't fetched (app/fetch-vendor.sh)")
    script = f"""
import {{ html, render }} from {json.dumps(str(vendor))};
const nodes = [];
const el = (tag) => ({{ nodeType: 1, localName: tag, nodeName: tag.toUpperCase(), childNodes: [], attributes: [], style: {{}},
  appendChild(c) {{ this.childNodes.push(c); nodes.push(c); return c; }}, insertBefore(c) {{ this.childNodes.push(c); nodes.push(c); return c; }},
  removeChild() {{}}, setAttribute(k, v) {{ this.attributes.push([k, v]); }}, removeAttribute() {{}}, addEventListener() {{}}, removeEventListener() {{}} }});
globalThis.document = {{ createElement: el, createElementNS: (_n, t) => el(t), createTextNode: (data) => ({{ nodeType: 3, data }}) }};
const root = el("div");
const name = '<img src=x onerror=alert(1)>Main.dc.html';
render(html`<li>${{name}}</li><option value=${{name}}>${{name}}</option>`, root);
console.log(JSON.stringify(nodes.map((n) => n.nodeType === 3 ? ["text", n.data] : ["el", n.localName])));
"""
    out = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert ["el", "img"] not in got and ["text", "<img src=x onerror=alert(1)>Main.dc.html"] in got


def test_a_design_session_s_view_opens_from_its_session_view_at_every_size():
    """FR-010: the entry is in the head (full and embedded) and in the send row (compact, which has no head)."""
    text = APP.read_text()
    assert 'const designing = Boolean(a && a.action === "design")' in text
    assert text.count('href=${hash("design", { name })}>Design view</a>') == 2
    assert "${compact && designing &&" in text
    assert "design: DesignView" in text


def test_the_view_keeps_its_own_controls_reachable():
    """FR-019: keys go to the picture only while it has focus, and the way out is written on the page."""
    source = _design_source()
    assert 'tabindex="0"' in source and "onKeyDown=${onKey}" in source
    assert "Esc twice or F6 leaves" in source and "focusPast(canvas.current, leave.step)" in source
    assert 'role="toolbar"' in source
    assert "touch-action: none" in (APP.parent / "style.css").read_text()
    assert ".design-bar { display: flex; flex-wrap: wrap;" in (APP.parent / "style.css").read_text()
