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


def test_only_a_note_of_the_notes_can_be_deleted():
    """009 FR-007: a row with a topic and an id; not another source's row, nor what's left of a deleted note."""
    got = run(["noteId"], """
        return [noteId({ topic: "gpu/hang", label: "c4 [seen: base=b1, cmd=x]", text: "Faults stop." }),
                noteId({ topic: "", label: "", text: "old words" }),
                noteId({ topic: "gpu/hang", label: "c5", text: "c5 DELETED 2026-11-06: wrong" }),
                noteId({ topic: "gpu/hang", label: "", text: "a log line" })];""")
    assert got == ["c4", None, None, None]
