# SPDX-License-Identifier: GPL-2.0-or-later
"""The Notes query, through Hubd.request, against a stand-in for the workspace's tool."""
import ast
import asyncio
import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path

import pytest

from hubd import auth, notes
from hubd.ghrun import Gh
from hubd.notes import Notes
from hubd.server import Hubd
from hubd.shells import Shells

ROWS = [{"state": "current", "label": "c12 [user]", "where": "gpu/hang:4", "text": "Faults stop."},
        {"state": "retracted", "label": "c9 [guess]", "where": "gpu/hang:9", "text": "RETRACTED by c12"},
        {"state": "archive, unreviewed", "label": "", "where": "/old/diary.md:1", "text": "old words"}]
# The tool's answer: rows on stdout, and the count and warnings on stderr, as the real one does.
TOOL = f"""import json, os, sys
seen = {{"argv": sys.argv[1:], "workspace": os.environ.get("GLASSINE_WORKSPACE"), "env": sorted(os.environ), "cwd": os.getcwd()}}
open(os.environ["GLASSINE_WORKSPACE"] + "/seen.json", "w").write(json.dumps(seen))
for row in {ROWS!r}:
    print(json.dumps(row))
print("notes: the search index was damaged, so it's being rebuilt", file=sys.stderr)
print("7 rows from notes, memory, showing 3: --limit for more", file=sys.stderr)
"""


class Agents:
    SCOPES = {"full-token": {"session": "full", "tools": None, "persona": None},
              "locked-token": {"session": "locked", "tools": ["get_pr"], "persona": None}}

    def scope(self, token):
        return self.SCOPES.get(token)

    def session_id_of(self, name):
        return None


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace"
    (root / "tools").mkdir(parents=True)
    (root / "notes").mkdir()
    (root / "tools" / "notes").write_text(TOOL)
    return root


def world(tmp_path, workspace, **kw):
    sessions = auth.Sessions()
    return Hubd(Gh("/nonexistent", workdir=str(tmp_path)), Shells(), sessions, "general-token", agents=Agents(),
                notes_search=Notes(workspace, **kw)), sessions.create()


def call(hubd, **req):
    return asyncio.run(hubd.request(req))


def test_no_token_has_it(tmp_path, workspace):
    hubd, _login = world(tmp_path, workspace)
    for op in ("notes.find", "notes.status", "notes.anything"):
        for token in ("full-token", "locked-token", "general-token", "wrong", None):
            for field in ("agent_token", "token"):
                reply = call(hubd, op=op, words="fault", **{field: token})
                assert reply == {"ok": False, "error": "login required", "denied": True}
    assert not (workspace / "seen.json").exists(), "the tool never ran"


def test_a_login_gets_the_same_query_with_each_rows_state_in_words(tmp_path, workspace):
    hubd, login = world(tmp_path, workspace)
    reply = call(hubd, op="notes.find", token=login, words="the  fault", limit=5)
    # 009 FR-003: each row also says its topic, from where it lives, and a date only when the tool gives one.
    assert reply["ok"] and reply["here"] and reply["rows"] == [{**r, "topic": t, "date": ""} for r, t in zip(ROWS, ("gpu/hang", "gpu/hang", ""))]
    assert reply["total"] == 7 and reply["says"] == "7 rows from notes, memory"
    assert reply["warnings"] == ["the search index was damaged, so it's being rebuilt"]
    seen = json.loads((workspace / "seen.json").read_text())
    assert seen["argv"] == ["find", "--json", "--limit", "5", "--", "the", "fault"]
    assert seen["workspace"] == str(workspace) and seen["cwd"] == str(workspace)


def test_what_you_typed_is_only_ever_words(tmp_path, workspace):
    hubd, login = world(tmp_path, workspace)
    call(hubd, op="notes.find", token=login, words="--limit 100000 -h")
    assert json.loads((workspace / "seen.json").read_text())["argv"][4:] == ["--", "--limit", "100000", "-h"]


def test_hubds_secrets_stay_out_of_the_tools_environment(tmp_path, workspace, monkeypatch):
    monkeypatch.setenv("GLASSINE_HUB_MCP_TOKEN", "secret")
    monkeypatch.setenv("GH_TOKEN", "secret")
    monkeypatch.setenv("PYTHONPATH", "/somewhere")
    hubd, login = world(tmp_path, workspace)
    call(hubd, op="notes.find", token=login, words="x")
    env = json.loads((workspace / "seen.json").read_text())["env"]
    assert not {"GLASSINE_HUB_MCP_TOKEN", "GH_TOKEN", "PYTHONPATH"} & set(env)


@pytest.mark.parametrize("gone, words", [("tool", "notes tool isn't in this workspace"), ("folder", "no notes yet")])
def test_what_isnt_there_is_said_in_words_and_not_made(tmp_path, workspace, gone, words):
    if gone == "tool":
        (workspace / "tools" / "notes").unlink()
    else:
        (workspace / "notes").rmdir()
    hubd, login = world(tmp_path, workspace)
    status = call(hubd, op="notes.status", token=login)
    assert status["ok"] and status["here"] is False and words in status["says"]
    found = call(hubd, op="notes.find", token=login, words="fault")
    assert found["ok"] and found["here"] is False and words in found["says"] and "Nothing was searched" in found["says"]
    assert found["rows"] == []
    assert not (workspace / "seen.json").exists(), "the tool never ran"
    assert (workspace / "notes").exists() == (gone == "tool"), "nothing was created"


def test_when_all_is_there_status_says_so(tmp_path, workspace):
    hubd, login = world(tmp_path, workspace)
    assert call(hubd, op="notes.status", token=login) == {"ok": True, "here": True, "says": None, "indexing": False}


def test_a_workspace_that_isnt_there_is_said_too(tmp_path):
    hubd, login = world(tmp_path, tmp_path / "nowhere")
    assert call(hubd, op="notes.status", token=login)["here"] is False
    assert not (tmp_path / "nowhere").exists()


@pytest.mark.parametrize("words, limit", [(None, None), ("", None), ("   ", None), (["fault"], None), ("x" * 501, None), ("a\0b", None),
                                          (" ".join("w" * 33), None), ("x", 0), ("x", 101), ("x", "5"), ("x", True), ("x", 1.5)])
def test_bad_arguments_are_said_and_the_tool_doesnt_run(tmp_path, workspace, words, limit):
    hubd, login = world(tmp_path, workspace)
    reply = call(hubd, op="notes.find", token=login, words=words, limit=limit)
    assert reply["ok"] is False and reply["error"]
    assert not (workspace / "seen.json").exists()


def test_the_tools_own_words_when_it_refuses(tmp_path, workspace):
    (workspace / "tools" / "notes").write_text('import sys\nprint("notes: no words to look for", file=sys.stderr)\nsys.exit(1)\n')
    hubd, login = world(tmp_path, workspace)
    assert call(hubd, op="notes.find", token=login, words="!!!") == {"ok": False, "error": "no words to look for"}
    (workspace / "tools" / "notes").write_text('import sys\nsys.exit(3)\n')
    assert "status 3" in call(hubd, op="notes.find", token=login, words="x")["error"]


def test_a_broken_tool_is_said(tmp_path, workspace):
    (workspace / "tools" / "notes").write_text('print("not json")\n')
    hubd, login = world(tmp_path, workspace)
    assert "isn't a row" in call(hubd, op="notes.find", token=login, words="x")["error"]


def test_a_row_with_no_state_doesnt_read_as_a_fact(tmp_path, workspace):
    (workspace / "tools" / "notes").write_text('print(\'{"where": "a/b:1", "text": "some claim"}\')\nprint(\'{"state": 3, "text": 4}\')\n')
    hubd, login = world(tmp_path, workspace)
    rows = call(hubd, op="notes.find", token=login, words="x")["rows"]
    assert [r["state"] for r in rows] == [notes.NO_STATE, notes.NO_STATE] and rows[1]["text"] == ""


def test_a_long_row_is_cut_and_says_so(tmp_path, workspace):
    (workspace / "tools" / "notes").write_text(f'import json\nprint(json.dumps({{"state": "current", "text": "x" * {notes.MAX_TEXT + 5}}}))\n')
    hubd, login = world(tmp_path, workspace)
    assert call(hubd, op="notes.find", token=login, words="x")["rows"][0]["text"].endswith("x ...")


def test_a_search_that_hangs_is_stopped(tmp_path, workspace):
    marker = workspace / "pid"
    (workspace / "tools" / "notes").write_text(f'import os, time\nopen({str(marker)!r}, "w").write(str(os.getpid()))\ntime.sleep(60)\n')
    hubd, login = world(tmp_path, workspace, timeout=1)
    reply = call(hubd, op="notes.find", token=login, words="x")
    assert reply["ok"] is False and "no answer in 1 seconds" in reply["error"]
    pid = int(marker.read_text())
    assert not Path(f"/proc/{pid}").exists() or "Z" in Path(f"/proc/{pid}/stat").read_text().split()[2], "stopped"


def test_the_tool_needs_no_execute_bit(tmp_path, workspace):
    path = workspace / "tools" / "notes"
    path.chmod(path.stat().st_mode & ~(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    hubd, login = world(tmp_path, workspace)
    assert call(hubd, op="notes.find", token=login, words="x")["ok"]


def test_without_a_store_it_says_so(tmp_path):
    sessions = auth.Sessions()
    hubd = Hubd(Gh("/nonexistent", workdir=str(tmp_path)), Shells(), sessions, "general-token")
    assert call(hubd, op="notes.find", token=sessions.create(), words="x") == {"ok": False, "error": "notes aren't set up"}


def test_an_unknown_op_is_refused_behind_the_login(tmp_path, workspace):
    hubd, login = world(tmp_path, workspace)
    assert call(hubd, op="notes.write", token=login)["error"] == "unknown request: notes.write"


def test_hubd_never_imports_the_tool_and_uses_only_the_standard_library():
    tree = ast.parse(Path(notes.__file__).read_text())
    names = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    names |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module and not node.level}
    assert names - {"__future__"} <= set(sys.stdlib_module_names)
    # hubd's own modules, which are standard library too (agents' test for what a card can't show): none of them is the tool
    own = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level}
    assert all(module and (Path(notes.__file__).parent / f"{module}.py").is_file() for module in own) and own <= {"agents"}


# --- from the review ---------------------------------------------------------------------------
def _tool_says(workspace, text):
    (workspace / "tools").mkdir(exist_ok=True)
    (workspace / "notes").mkdir(exist_ok=True)
    (workspace / "tools" / "notes").write_text(text)


@pytest.mark.parametrize("char", ["\u2028", "\u2029", "\u0085"])
def test_a_row_breaks_only_on_a_newline(tmp_path, char):
    row = json.dumps({"state": "current", "where": "w", "label": "", "text": f"a{char}b"}, ensure_ascii=False)
    _tool_says(tmp_path, f"import sys\nsys.stdout.buffer.write({(row + chr(10)).encode()!r})\n")
    found = asyncio.run(Notes(tmp_path).find("words"))
    assert [r["text"] for r in found["rows"]] == [f"a{char}b"]


def test_a_word_that_cant_go_on_a_command_line_is_refused_in_words(tmp_path):
    _tool_says(tmp_path, "")
    with pytest.raises(notes.NotesError, match="can't be searched for"):
        asyncio.run(Notes(tmp_path).find("\ud800"))


def test_hubd_keeps_to_the_limit_and_caps_every_field(tmp_path):
    long = "x" * (notes.MAX_TEXT + 10)
    row = json.dumps({"state": "current", "where": long, "label": long, "text": long})
    _tool_says(tmp_path, f"import sys\nfor _ in range(30):\n    print({row!r})\nfor _ in range(50):\n    print('notes: ' + {long!r}, file=sys.stderr)\n")
    found = asyncio.run(Notes(tmp_path).find("words", 5))
    assert len(found["rows"]) == 5 and found["total"] == 30
    assert all(len(r[k]) < notes.MAX_TEXT + 10 for r in found["rows"] for k in ("where", "label", "text"))
    assert len(found["warnings"]) <= 20 and all(len(w) < notes.MAX_TEXT + 10 for w in found["warnings"])


# --- 009: totals, a session that reads the notes, and the operations a login applies -------------------
from hubd import results  # noqa: E402
from hubd.agents import Library, LibraryError  # noqa: E402

LIBRARY = Library(Path(__file__).resolve().parents[1] / "agents")
# A tool that writes down every call and answers like `notes set`: what hubd ran is all a test needs to see.
WRITER = """import json, os, sys
open(os.environ["GLASSINE_WORKSPACE"] + "/calls.jsonl", "a").write(json.dumps(sys.argv[1:]) + "\\n")
if "--retract=c2" in sys.argv:
    print("notes: c2 is already retracted", file=sys.stderr)
    sys.exit(1)
print("ok " + " ".join(sys.argv[1:3]))
"""


def calls(workspace):
    path = workspace / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@pytest.mark.parametrize("op,argv", [
    ({"op": "supersede", "topic": "gpu/hang", "ids": ["c3", "c4"], "words": "Faults stop with r107."},
     ["set", "--replaces=c3", "--inferred=c4", "--", "gpu/hang", "Faults stop with r107."]),
    ({"op": "merge", "topic": "gpu/hang", "ids": ["c3", "c4", "c6"], "words": "--retract c5 is words"},
     ["set", "--replaces=c3", "--inferred=c4,c6", "--", "gpu/hang", "--retract c5 is words"]),
    ({"op": "retract", "topic": "gpu/hang", "ids": ["c9"], "by": "c12", "why": "-x looks like a flag"},
     ["set", "--retract=c9", "--by=c12", "--why=-x looks like a flag", "--", "gpu/hang"]),
    ({"op": "answer", "topic": "gpu/hang", "ids": ["c7"], "why": "settled by c12"}, ["set", "--close=c7", "--why=settled by c12", "--", "gpu/hang"]),
    ({"op": "add", "topic": "gpu/hang", "words": "Does r108 change it?", "open": True},
     ["add", "--open", "--guess", "--", "gpu/hang", "Does r108 change it?"]),
    ({"op": "add", "topic": "gpu/hang", "words": "Merged c3 and c4."}, ["add", "--", "gpu/hang", "Merged c3 and c4."]),
])
def test_each_op_is_one_tool_run_and_words_are_never_flags(op, argv):
    assert notes.argv_of(notes.clean_op(op)) == argv
    assert notes.command_of(notes.clean_op(op)).startswith("notes " + argv[0])


@pytest.mark.parametrize("op,words", [
    ({"op": "delete", "topic": "gpu/hang", "ids": ["c1"]}, "none deletes"),
    ({"op": "supersede", "topic": "../etc", "ids": ["c1"], "words": "w"}, "AREA/TOPIC"),
    ({"op": "supersede", "topic": "gpu/hang", "ids": ["1"], "words": "w"}, "note ids"),
    ({"op": "supersede", "topic": "gpu/hang", "ids": ["c1"], "words": "w", "command": "rm -rf"}, "not command"),
    ({"op": "supersede", "topic": "gpu/hang", "ids": ["c1"], "words": "w"}, "can't rest on the one it replaces"),
    ({"op": "distil", "topic": "gpu/hang", "ids": ["c1"], "words": "w"}, "at least one current note"),
    ({"op": "retract", "topic": "gpu/hang", "ids": ["c1", "c2"], "by": "c3", "why": "w"}, "one note"),
    ({"op": "retract", "topic": "gpu/hang", "ids": ["c1"], "by": "c1", "why": "w"}, "shows it wrong"),
    *(({"op": "add", "topic": "gpu/hang", "words": f"hidden{c}word"}, "invisible") for c in "\u200b\u2800\u3164\u034f\ufe0f\U000e0100"),
    ({"op": "retract", "topic": "gpu/hang", "ids": ["c1"], "by": "c2", "why": "blank\u2800why"}, "invisible"),
    ({"op": "add", "topic": "gpu/hang", "words": "x" * 2001}, "1 to 2000"),
])
def test_an_op_outside_the_shape_is_refused(op, words):
    with pytest.raises(notes.OpError, match=words):
        notes.clean_op(op)


def test_a_notes_result_carries_the_command_hubd_built():
    payload = results.clean_payload("notes", {"ops": [{"op": "answer", "topic": "gpu/hang", "ids": ["c7"], "why": "settled"}], "summary": "s"}, [])
    assert payload["ops"][0]["command"] == "notes set --close=c7 '--why=settled' -- gpu/hang".replace("'--why=settled'", "--why=settled")
    assert payload["ops"][0]["state"] == "pending"
    with pytest.raises(results.ResultError, match="at least one"):
        results.clean_payload("notes", {"ops": []}, [])


def note_world(tmp_path, tool=WRITER, ops=None, **kw):
    root = tmp_path / "workspace"
    (root / "tools").mkdir(parents=True)
    (root / "notes").mkdir()
    (root / "tools" / "notes").write_text(tool)
    hubd, login = world(tmp_path, root, **kw)
    hubd.results = results.Results(tmp_path / "results")
    hubd.agents.library = LIBRARY
    hubd.sessions.own_user = lambda: "me"
    hubd.work = None
    ops = ops or [{"op": "supersede", "topic": "gpu/hang", "ids": ["c3", "c4"], "words": "New words."},
                  {"op": "retract", "topic": "gpu/hang", "ids": ["c2"], "by": "c3", "why": "wrong"},
                  {"op": "add", "topic": "gpu/hang", "words": "Log line."}]
    record = hubd.results.submit("notes", {"ops": ops}, session="notes-compact", session_id="i", launch=None, items=[],
                                 action="notes-compact", persona="archivist")
    return hubd, login, root, record


def test_a_login_applies_ops_in_order_and_a_failure_stops_the_rest(tmp_path):
    hubd, login, root, record = note_world(tmp_path)
    reply = call(hubd, op="result.apply", token=login, id=record["id"])
    assert not reply["ok"] or reply["result"]["state"] == "pending"
    ops = hubd.results.get(record["id"])["payload"]["ops"]
    assert [o["state"] for o in ops] == ["applied", "failed", "pending"] and "already retracted" in ops[1]["said"]
    assert calls(root) == [["set", "--replaces=c3", "--inferred=c4", "--", "gpu/hang", "New words."],
                           ["set", "--retract=c2", "--by=c3", "--why=wrong", "--", "gpu/hang"]]
    assert not any(a[0] not in ("add", "set") for a in calls(root))  # nothing but add and set: no delete
    call(hubd, op="result.apply", token=login, id=record["id"], indexes=[2])
    assert [o["state"] for o in hubd.results.get(record["id"])["payload"]["ops"]] == ["applied", "failed", "applied"]
    refused = call(hubd, op="result.apply", token=login, id=record["id"], indexes=[0])
    assert "isn't applied yet" in refused["error"]  # an applied op isn't run twice


# A tool that writes down, on each call, the op states in the one result on disk: what a restart then would find.
PEEKER = """import glob, json, os, sys, time
root = os.environ["GLASSINE_WORKSPACE"]
record = json.load(open(glob.glob(root + "/../results/r-*.json")[0]))
open(root + "/seen.jsonl", "a").write(json.dumps([o["state"] for o in record["payload"]["ops"]]) + "\\n")
if "Hangs." in sys.argv:
    time.sleep(30)
print("ok")
"""


def test_each_op_is_on_disk_as_it_runs_and_one_with_no_answer_waits_for_a_look(tmp_path):
    ops = [{"op": "add", "topic": "gpu/hang", "words": "One."}, {"op": "add", "topic": "gpu/hang", "words": "Hangs."},
           {"op": "add", "topic": "gpu/hang", "words": "Three."}]
    hubd, login, root, record = note_world(tmp_path, PEEKER, ops, write_timeout=0.5)
    call(hubd, op="result.apply", token=login, id=record["id"])
    seen = [json.loads(line) for line in (root / "seen.jsonl").read_text().splitlines()]
    assert seen == [["running", "pending", "pending"], ["applied", "running", "pending"]]  # each on disk before the next runs
    record = hubd.results.get(record["id"])
    assert [o["state"] for o in record["payload"]["ops"]] == ["applied", "unknown", "pending"]  # it may have committed
    assert record["state"] == "pending" and "Operation 2 may or may not be in the notes" in record["note"]
    for indexes in (None, [1]):  # the rest may run, but not the unknown one, by all or by name
        reply = call(hubd, op="result.apply", token=login, id=record["id"], **({"indexes": indexes} if indexes else {}))
        assert indexes is None or "say first whether it is" in reply["error"]
    assert len((root / "seen.jsonl").read_text().splitlines()) == 3  # only Three ran
    assert "only a note operation whose outcome is unknown" in call(hubd, op="result.resolve", token=login, id=record["id"], index=0, found=True)["error"]
    assert call(hubd, op="result.resolve", agent_token="full-token", id=record["id"], index=1, found=True)["denied"]
    reply = call(hubd, op="result.resolve", token=login, id=record["id"], index=1, found=True)
    assert reply["result"]["state"] == "applied" and reply["result"]["payload"]["ops"][1]["said"] == "You found it in the notes."


def test_after_a_restart_the_op_that_was_running_is_unknown_and_what_finished_stays(tmp_path):
    hubd, login, root, record = note_world(tmp_path)
    hubd.results.claim(record["id"])
    hubd.results.save_op(record["id"], 0, state="applied", said="ok")
    hubd.results.save_op(record["id"], 1, state="running", said=None)
    again = results.Results(tmp_path / "results").get(record["id"])
    assert [o["state"] for o in again["payload"]["ops"]] == ["applied", "unknown", "pending"]
    assert again["state"] == "pending" and again["note"] == results.NOTES_INTERRUPTED and "GitHub" not in again["note"]
    hubd.results = results.Results(tmp_path / "results")
    reply = call(hubd, op="result.resolve", token=login, id=record["id"], index=1, found=False)
    assert reply["result"]["payload"]["ops"][1]["state"] == "pending"  # you looked: it can run again
    call(hubd, op="result.apply", token=login, id=record["id"], indexes=[1])
    assert calls(root)[-1][:2] == ["set", "--retract=c2"]


def test_no_token_applies_ops(tmp_path):
    hubd, _login, root, record = note_world(tmp_path)
    for token in ("full-token", "locked-token", "general-token", None):
        assert call(hubd, op="result.apply", agent_token=token, id=record["id"])["denied"]
        assert call(hubd, op="result.apply", token=token, id=record["id"])["denied"]
    assert calls(root) == []


# The workspace's own tool, where this host has one (hubd's default place, or HUBD_WORKSPACE): the stand-ins above only
# record what hubd ran, and can't say whether the tool would take it. It runs on a copy, in a workspace of its own.
REAL_WORKSPACE = Path(os.environ.get("HUBD_WORKSPACE") or Path.home() / "GlassineOS").expanduser()
SCAN = Path(".glassine/org/scripts/safety-scan.sh")


@pytest.fixture
def real_tool(tmp_path, monkeypatch):
    if not (REAL_WORKSPACE / "tools" / "notes").is_file() or not (REAL_WORKSPACE / SCAN).is_file():
        pytest.skip("skipped: no workspace here with tools/notes and the safety scan")
    root = tmp_path / "GlassineOS"
    shutil.copytree(REAL_WORKSPACE / "tools", root / "tools", ignore=shutil.ignore_patterns("__pycache__"))
    (root / SCAN).parent.mkdir(parents=True)
    shutil.copy2(REAL_WORKSPACE / SCAN, root / SCAN)
    (root / "workspace.toml").write_text('[identity]\nname = "N"\nemail = "n@example.org"\n')
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # no global git settings, and the search index stays in here
    tool = Notes(root)
    for words in ("Faults start with r106.", "r107 runs clean on b2.", "One hang is in the scheduler.",
                  "Another hang is in the scheduler.", "The panel resets at 3 V.", "The panel resets on a brownout."):
        asyncio.run(tool._run(["set", "--seen=base=b1, cmd=run it", "--", "gpu/hang", words], 60))  # c1 to c6, as a person sets them
    return tool, root / "notes" / "gpu" / "hang.md"


def test_every_op_is_one_the_real_notes_tool_takes(real_tool):
    tool, topic = real_tool
    ops = [{"op": "supersede", "topic": "gpu/hang", "ids": ["c1", "c2"], "words": "Faults stop with r107."},  # c7
           {"op": "merge", "topic": "gpu/hang", "ids": ["c3", "c4"], "words": "Both hangs are in the scheduler."},  # c8
           {"op": "distil", "topic": "gpu/hang", "ids": ["c5", "c6", "c2"], "words": "-x: the panel resets when power drops."},  # c9
           {"op": "add", "topic": "gpu/hang", "words": "Does r108 change it?", "open": True},  # c10
           {"op": "answer", "topic": "gpu/hang", "ids": ["c10"], "why": "settled by c7"},
           {"op": "retract", "topic": "gpu/hang", "ids": ["c8"], "by": "c9", "why": "the hangs differ"},
           {"op": "add", "topic": "gpu/hang", "words": "Compacted."}]
    done = asyncio.run(tool.apply([notes.clean_op(op) for op in ops]))
    assert [d["state"] for d in done] == ["applied"] * len(ops), done
    asyncio.run(tool._run(["lint", "gpu/hang"], 60))  # exits 1, and so raises, if anything may not stand
    current = topic.read_text().split("## Current")[1].split("## Open")[0]
    assert sorted(re.findall(r"- (c[0-9]+) ", current)) == ["c2", "c4", "c6", "c7", "c9"]
    assert "[inferred: c2] Faults stop with r107." in current and "[inferred: c6,c2] -x: the panel" in current
    # The tool's own refusal comes back in its words: c1 went to Log, so nothing can rest on it.
    refused = asyncio.run(tool.apply([notes.clean_op({"op": "supersede", "topic": "gpu/hang", "ids": ["c7", "c1"], "words": "w"})]))
    assert refused[0]["state"] == "failed" and "isn't in Current" in refused[0]["said"]


class NotesAgents(Agents):
    SCOPES = {**Agents.SCOPES, "compact-token": {"session": "notes-compact", "tools": ["notes_find", "submit_result"], "persona": "archivist"},
              "steward-token": {"session": "steward", "tools": ["docs_search"], "persona": "steward"},
              "issue-token": {"session": "issue-triage-boot-3", "tools": ["get_issue"], "persona": "triager"},
              "old-token": {"session": "old", "tools": ["get_issue"], "persona": "triager"}}
    library = LIBRARY


def test_a_session_whose_list_has_the_search_uses_it(tmp_path, workspace):
    """hubd goes by the token's own list: the library decides which actions list the tool. A full session's list is open, and
    a hub shell holds the general token."""
    hubd, _login = world(tmp_path, workspace)
    hubd.agents = NotesAgents()
    for token in ("compact-token", "full-token", "general-token"):
        reply = call(hubd, op="notes_tool.find", agent_token=token, words="fault")
        assert reply["ok"] and reply["rows"], token
    # An action that can post or plan has no tool in its list, and hubd doesn't hand it one: nor does an unknown token.
    for token in ("steward-token", "issue-token", "old-token", "locked-token", "nope", None):
        assert call(hubd, op="notes_tool.find", agent_token=token, words="fault")["refused"], token
    # And not the page's query: that one stays behind the login.
    assert call(hubd, op="notes.find", agent_token="compact-token", words="fault")["denied"]


def _tool_answering(workspace, rows, summary):
    (workspace / "tools" / "notes").write_text("import json, sys\n"
                                               f"for row in {rows!r}:\n    print(json.dumps(row))\n"
                                               "print('notes: /srv/archive/diaries isn\\'t there, so it wasn\\'t searched', file=sys.stderr)\n"
                                               f"print({summary!r}, file=sys.stderr)\n")


def test_a_locked_session_gets_the_notes_and_not_the_archive(tmp_path, workspace):
    """Transcripts, diaries and old memory never passed the scan: the tool ranks them last, and hubd leaves them out of a locked
    session's search, with the sources and paths the tool names. A full session and a hub shell could read the files anyway."""
    hubd, _login = world(tmp_path, workspace)
    hubd.agents = NotesAgents()
    reply = call(hubd, op="notes_tool.find", agent_token="compact-token", words="fault")
    assert [r["state"] for r in reply["rows"]] == ["current", "retracted"] and "old words" not in json.dumps(reply)
    assert reply["total"] == 2 and reply["says"] == "2 rows in the notes" and reply["warnings"] == []
    for token in ("full-token", "general-token"):
        reply = call(hubd, op="notes_tool.find", agent_token=token, words="fault")
        assert [r["state"] for r in reply["rows"]] == ["current", "retracted", "archive, unreviewed"], token
        assert reply["says"] == "7 rows from notes, memory" and reply["warnings"], token
    # The page's own query is the login's and keeps the archive in its counts.
    hubd, login = world(tmp_path, workspace)
    assert [r["state"] for r in call(hubd, op="notes.find", token=login, words="fault")["rows"]] == ["current", "retracted", "archive, unreviewed"]


def test_a_locked_sessions_search_keeps_only_states_it_knows(tmp_path, workspace):
    rows = [{"state": s, "label": "", "where": f"a/b:{i}", "text": f"t{i}"}
            for i, s in enumerate(["current", "open", "history", "retracted", "archive, unreviewed", "something new", ""])]
    _tool_answering(workspace, rows, "7 rows from notes, memory")
    hubd, _login = world(tmp_path, workspace)
    hubd.agents = NotesAgents()
    reply = call(hubd, op="notes_tool.find", agent_token="compact-token", words="x")
    assert [r["where"] for r in reply["rows"]] == ["a/b:0", "a/b:1", "a/b:2", "a/b:3"] and reply["total"] == 4
    assert "memory" not in json.dumps(reply) and "/srv/archive" not in json.dumps(reply)  # the tool's sources and warnings name this host's paths


def test_a_locked_session_is_told_when_more_notes_match(tmp_path, workspace):
    rows = [{"state": "current", "label": "", "where": f"a/b:{i}", "text": f"t{i}"} for i in range(2)]
    _tool_answering(workspace, rows, "9 rows from notes, memory, showing 2: --limit for more")
    hubd, _login = world(tmp_path, workspace)
    hubd.agents = NotesAgents()
    reply = call(hubd, op="notes_tool.find", agent_token="compact-token", words="x", limit=2)
    assert len(reply["rows"]) == 2 and reply["total"] == 9 and "more match" in reply["says"] and "memory" not in reply["says"]


def test_the_notes_search_is_on_the_actions_that_only_read():
    """The tool is added to a locked action that can't carry a note out: no shell, no write or post tool, nothing that asks
    first. One that can post or send never has it (SECURITY.md, Notes)."""
    from hubd.agents import _full, _may_search_notes
    for action in LIBRARY.actions.values():
        assert ("notes_find" in action.get("hub_tools", ())) == _may_search_notes(action), action["id"]
        if _full(action):  # a full session has no list: hubd lets it use any tool
            assert "notes_find" not in action.get("hub_tools", ())
    for reads in ("notes-compact", "notes-sweep", "knowledge-research", "new-issue", "new-security-audit"):
        assert "notes_find" in LIBRARY.action(reads)["hub_tools"], reads
    # The ones that read an outsider's text and post (comment_issue, comment_pr), or have a shell with the internet, or ask first.
    for posts in ("issue-triage", "pr-security-audit", "pr-review", "project-steward"):
        assert "notes_find" not in LIBRARY.action(posts)["hub_tools"], posts
    assert "comment_issue" in LIBRARY.action("issue-triage")["hub_tools"] and "comment_pr" in LIBRARY.action("pr-security-audit")["hub_tools"]
    assert "Bash" in LIBRARY.action("pr-review")["tools"] and LIBRARY.action("project-steward")["asks_first"]


def _copy_of_the_library(tmp_path):
    root = tmp_path / "agents"
    shutil.copytree(Path(__file__).resolve().parents[1] / "agents", root)
    return root


def test_the_library_adds_the_search_only_where_it_cant_carry_a_note_out(tmp_path):
    """An action added later with a post tool, a shell or a card to ask doesn't pick the tool up by being new."""
    root = _copy_of_the_library(tmp_path)
    base = (root / "actions" / "new-issue.toml").read_text()
    variants = {"posts": base.replace('"submit_drafts"]', '"submit_drafts", "comment_issue"]'),
                "writes": base.replace('"submit_drafts"]', '"submit_drafts", "create_issue"]'),
                "shell": base.replace('tools = ["Read", "Grep", "Glob", "AskUserQuestion"]', 'tools = ["Read", "Grep", "Glob", "AskUserQuestion", "Bash"]'),
                "asks": base + 'asks_first = ["comment_issue"]\n'}
    for name, text in variants.items():
        assert text != base, name
        (root / "actions" / f"x-{name}.toml").write_text(text.replace('verb = "issue"', f'verb = "{name}"'))
    (root / "actions" / "x-reads.toml").write_text(base.replace('verb = "issue"', 'verb = "reads"'))
    library = Library(root)
    assert "notes_find" in library.action("x-reads")["hub_tools"]
    for name in variants:
        assert "notes_find" not in library.action(f"x-{name}")["hub_tools"], name


def test_the_library_refuses_a_hand_listed_search_on_an_action_that_can_post(tmp_path):
    root = _copy_of_the_library(tmp_path)
    action = root / "actions" / "notes-compact.toml"
    good = action.read_text()
    for bad in (good.replace('"submit_result"]', '"submit_result", "comment_issue"]'), good + 'asks_first = ["comment_issue"]\n',
                good.replace('tools = ["AskUserQuestion"]', 'tools = ["AskUserQuestion", "Bash"]'),
                good + 'access = "full"\n'):
        assert bad != good
        action.write_text(bad)
        with pytest.raises(LibraryError, match="notes_find"):
            Library(root)
    action.write_text(good)
    Library(root)  # as it ships, it loads


def test_totals_come_from_the_last_search_and_say_so(tmp_path, workspace):
    hubd, login = world(tmp_path, workspace)
    assert call(hubd, op="notes.totals", token=login)["source"] is None
    call(hubd, op="notes.find", token=login, words="fault")
    totals = call(hubd, op="notes.totals", token=login)
    assert totals["source"] == "last-search" and totals["rows"] == 3
    assert totals["by_label"] == {"current": 1, "retracted": 1, "archive, unreviewed": 1} and totals["by_topic"] == {"gpu/hang": 2}


def test_a_sessions_search_leaves_your_totals_alone(tmp_path, workspace):
    hubd, login = world(tmp_path, workspace)
    hubd.agents = NotesAgents()
    assert call(hubd, op="notes_tool.find", agent_token="compact-token", words="fault")["ok"]
    assert call(hubd, op="notes.totals", token=login)["source"] is None  # the Archivist's search isn't yours
    call(hubd, op="notes.find", token=login, words="fault", limit=2)
    assert call(hubd, op="notes.totals", token=login)["rows"] == 2
    assert call(hubd, op="notes_tool.find", agent_token="compact-token", words="fault")["ok"]
    assert call(hubd, op="notes.totals", token=login)["rows"] == 2
