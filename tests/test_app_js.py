"""Behaviour of the page's pure functions, run in node: what static checks of the source can't show.

Each function is taken from app.js as it is (a top-level `function name(...) { ... }` that ends at a line holding only
`}`), so the test runs the shipped code, not a copy."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app" / "hub" / "static" / "app.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node isn't installed")


def function(name: str) -> str:
    match = re.search(rf"^function {name}\(.*?^}}$", APP.read_text(), re.S | re.M)
    assert match, f"no top-level function {name} in app.js"
    return match.group(0)


def run(names: list[str], body: str):
    script = "\n".join(function(n) for n in names) + f"\nconsole.log(JSON.stringify((() => {{ {body} }})()));"
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30, check=True).stdout
    return json.loads(out)


def test_only_rows_for_the_words_typed_now_count():
    """#28 review: a late reply for "battery" can't stand in for "battery drain", nor be picked with Enter."""
    rows = [{"repo": "hub", "number": 1}]
    got = run(["currentRows"], f"""
        const rows = {json.dumps(rows)};
        return [
          currentRows({{ words: "battery", rows }}, "battery"),
          currentRows({{ words: "battery", rows }}, "battery drain"),
          currentRows({{ words: "", rows: [] }}, "battery"),
        ];""")
    assert got == [rows, [], []]


def test_a_run_says_how_it_ended():
    """#28 review: a cancelled or timed-out run doesn't read "closed"."""
    got = run(["pillState"], """
        const run = (conclusion, status = "completed") => pillState("run", { status, conclusion });
        return [run(null, "in_progress"), run("success"), run("failure"), run("timed_out"), run("startup_failure"),
                run("cancelled"), run("skipped"), run("neutral")];""")
    assert got == ["running", "passed", "failing", "failing", "failing", "cancelled", "skipped", "closed"]


def test_esc_is_left_alone_when_no_list_is_open():
    """#28 review: an empty picker inside a dialog mustn't swallow the Esc that closes the dialog."""
    got = run(["listKeys"], """
        const press = (open) => {
          const e = { key: "Escape", prevented: false, stopped: false,
                      preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; } };
          let closed = false;
          listKeys(e, { size: 0, active: 0, setActive() {}, pick() {}, close() { closed = true; }, open });
          return [e.prevented, e.stopped, closed];
        };
        return [press(true), press(false)];""")
    assert got == [[True, True, True], [False, False, False]]


def test_a_session_is_embedded_only_in_the_item_it_was_placed_on():
    """#34 review 5: a move on this page is keyed by session and item, and the stored view counts only for its own item."""
    got = run(["embeddedPhase"], """
        const view = (over) => ({ name: "s", agent: { view: { mode: "embedded", where: "Work", ref: "hub#1", ...over } } });
        const A = "hub#1", B = "hub#2";
        return [
          embeddedPhase(null, A, {}),                                   // no session
          embeddedPhase(view({}), A, {}),                               // stored for this item
          embeddedPhase(view({}), B, {}),                               // stored for another item: background here, as after a reload
          embeddedPhase(view({ ref: null }), B, {}),                    // stored with no item: any
          embeddedPhase(view({ where: "Sessions" }), A, {}),            // placed from Sessions
          embeddedPhase(view({ mode: "background" }), A, {}),
          embeddedPhase({ name: "s", agent: {} }, A, {}),               // no stored view at all
          embeddedPhase(view({}), B, { "s@hub#1": "embedded" }),        // moved on item A says nothing about B
          embeddedPhase(view({}), A, { "s@hub#1": "background" }),      // moved here wins over the stored view
          embeddedPhase(view({ mode: "background" }), B, { "s@hub#2": "embedded" }),
        ];""")
    assert got == [None, "embedded", "background", "embedded", "background", "background", "background", "background", "background", "embedded"]


def test_the_origin_is_told_in_words():
    """#34 follow-up: a session started with the one click says so, and only one with no origin at all is called old."""
    constants = "\n".join(re.search(rf"^const {n} = .*;$", APP.read_text(), re.M).group(0) for n in ("STEWARD", "byWords"))
    script = f"{constants}\n{function('originWords')}\nconsole.log(JSON.stringify((() => {{ %s }})()));"
    body = """
        const words = (a) => originWords(a);
        return [
          words({ origin: { launch: null, from: null, by: "you" } }),
          words({ origin: { launch: "w1", from: { view: "Work", ref: "hub#4" }, by: "you" } }),
          words({ origin: { launch: "w2", from: { view: "Needs you", ref: null }, by: "steward" } }),
          words({ origin: { launch: "w3", from: null, by: "you" } }),
          words({ origin: null, started_by: "steward" }),
          words({ origin: null, started_by: null }),
        ];"""
    out = subprocess.run([NODE, "-e", script % body], capture_output=True, text=True, timeout=30, check=True).stdout
    assert json.loads(out) == ["started directly, by you", "from Work item hub#4, by you", "from Needs you, by the Steward",
                               "from Launch, by you", "started by the Steward", "started before origins were kept"]
