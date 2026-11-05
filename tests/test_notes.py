# SPDX-License-Identifier: GPL-2.0-or-later
"""The Notes query, through Hubd.request, against a stand-in for the workspace's tool."""
import ast
import asyncio
import json
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
    assert reply["ok"] and reply["here"] and reply["rows"] == ROWS
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
    assert call(hubd, op="notes.status", token=login) == {"ok": True, "here": True, "says": None}


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
    names |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert names - {"__future__"} <= set(sys.stdlib_module_names)


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
