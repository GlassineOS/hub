# SPDX-License-Identifier: GPL-2.0-or-later
"""The code map: what's extracted, how it's built and rebuilt, and what the tools say."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import pytest

from codemap.build import MAX_FILE, build
from codemap.extract import extract, language_of
from hubd import codemap as codemap_module
from hubd import limits
from hubd.agents import MAP_TOOLS, PLANNER_TOOLS, DRAFT_TOOLS, Library
from hubd.codemap import CAVEAT, CodeMaps, MapError
from hubd.seeds import Seeds
from hubd.server import Hubd

REPO = Path(__file__).parents[1]
LIBRARY = Library(REPO / "agents")
CTL = "/run/example-daemon.ctl"


def git(*args, cwd):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit(work: Path, files: dict[str, str | None], message="change") -> str:
    for path, text in files.items():
        target = work / path
        if text is None:
            target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    git("add", "-A", cwd=work)
    git("commit", "-qm", message, cwd=work)
    return git("rev-parse", "HEAD", cwd=work)


# --- what's extracted ----------------------------------------------------------------
def rows(facts, role=None):
    return [s for s in facts.strings if role is None or s[3] == role]


def test_c_a_macro_defines_the_string_and_its_uses_say_how_they_touch_the_file():
    facts = extract("c", f'''#include <fcntl.h>
#define CTL "{CTL}"
struct thing {{ int a; }};
typedef int count_t;
enum mode {{ MODE_ONE }};
int shared_counter;
extern int elsewhere;
int prototype_only(void);
static const char *const KEPT = "/etc/example/kept.conf";
static void send(void) {{
    int fd = open(CTL, O_WRONLY | O_CLOEXEC);
    int local_one = helper(fd);
    mkfifo(CTL, 0600);
    FILE *in = fopen("/run/example.state", "r");
    const char *shader = "#if CTL == 3\\n";
}}
'''.encode())
    defs = {(n, k) for n, k, _l, _e in facts.defs}
    assert {("CTL", "macro"), ("thing", "struct"), ("count_t", "typedef"), ("mode", "enum"), ("MODE_ONE", "enumerator"), ("shared_counter", "variable"), ("KEPT", "variable"), ("send", "function")} <= defs
    assert not {n for n, _k in defs} & {"elsewhere", "prototype_only"}
    assert (CTL, "path", 2, "define", "CTL", None, None, None) in facts.strings
    assert ("CTL", 11, "send", "open", "write") in facts.flows and ("CTL", 13, "send", "mkfifo", "create") in facts.flows
    assert ("/run/example.state", "path", 14, "use", None, "send", "fopen", "read") in facts.strings
    assert any(s[0] == "/etc/example/kept.conf" and s[4] == "KEPT" for s in rows(facts, "define"))
    assert "local_one" not in facts.refs and "helper" in facts.refs
    assert facts.refs["CTL"][1] == [11, 13]  # the text inside the shader's string isn't a use of the macro


def test_c_words_in_a_macro_body_count_as_uses():
    facts = extract("c", b"#define CALL(x) real_function(x, OTHER)\n")
    assert {"real_function", "OTHER"} <= set(facts.refs)


def test_shell_redirects_commands_and_variables():
    facts = extract("shell", f'''#!/bin/sh
FIFO={CTL}
send() {{
    echo stats > "$FIFO"
    echo direct > {CTL}
    cat "$FIFO"
    cat < {CTL}
}}
mkfifo "$FIFO"
'''.encode())
    assert (CTL, "path", 2, "define", "FIFO", None, None, None) in facts.strings
    assert ("FIFO", 4, "send", ">", "write") in facts.flows and ("FIFO", 6, "send", "cat", "read") in facts.flows and ("FIFO", 9, None, "mkfifo", "create") in facts.flows
    assert (CTL, "path", 5, "use", None, "send", ">", "write") in facts.strings and (CTL, "path", 7, "use", None, "send", "<", "read") in facts.strings
    assert ("send", "function", 3, 8) in facts.defs


def test_shell_packages():
    facts = extract("shell", b'''pkgname=example-tool
depends="busybox e2fsprogs $pkgname-extra"
apk add -q alpine-sdk openssl
docker run alpine sh -c 'apk add -q python3 >/dev/null'
''')
    found = {(s[0], s[3]) for s in facts.strings if s[1] == "package"}
    assert {("example-tool", "define"), ("busybox", "use"), ("e2fsprogs", "use"), ("alpine-sdk", "use"), ("openssl", "use"), ("python3", "use")} <= found
    assert not any(s[0] == "-q" or "$" in s[0] for s in facts.strings if s[1] == "package")


def test_scripts_inside_strings_are_read_with_their_real_lines():
    facts = extract("shell", f'''#!/bin/sh
echo outer
docker run --rm alpine sh -c '
    apk add -q python3 >/dev/null
    echo stats > {CTL}
    mkfifo "$INNER"
'
ssh device <<END
cat {CTL}
END
python3 - <<PY
open("/run/not-a-shell-script", "w")
PY
echo "just saying > /run/not-a-write"
'''.encode())
    assert (CTL, "path", 5, "use", None, None, ">", "write") in facts.strings and ("INNER", 6, None, "mkfifo", "create") in facts.flows
    assert any(s[0] == "python3" and s[1] == "package" and s[2] == 4 for s in facts.strings)
    assert (CTL, "path", 9, "use", None, None, "cat", "read") in facts.strings
    assert not any("not-a" in s[0] for s in facts.strings)


def test_a_script_in_pieces_is_still_read():
    facts = extract("shell", f"""docker run alpine sh -c '
echo stats > {CTL}
echo don'"'"'t
echo more > {CTL}
'
""".encode())
    assert {s[2] for s in facts.strings if s[0] == CTL and s[7] == "write"} == {2, 4}


def test_c_keywords_a_macro_confused_the_grammar_about_arent_names():
    facts = extract("c", b"#define LOOP(x) for (x = 0; x < 3; x++)\nLOOP(i) { if (i) { work(i); } }\nif (ready) { go(); }\n")
    assert not {"if", "for"} & ({d[0] for d in facts.defs} | set(facts.refs))


def test_a_config_key_is_compared_without_its_value():
    words = extract("shell", b"echo deadband=4 > /run/example.ctl\n")
    code = extract("c", b'void f(char *l) { if (strstr(l, "deadband=")) g(); }\n')
    assert any(s[:2] == ("deadband=", "key") for s in words.strings) and any(s[:2] == ("deadband=", "key") for s in code.strings)
    assert any(s[:2] == ("deadband=", "key") for s in extract("shell", b'echo "@deadband=4" > /etc/x.conf\n').strings)
    assert not extract("c", b'void f(void) { g("a=1"); }\n').strings  # too short to mean anything across repositories


def test_python_constants_and_paths():
    facts = extract("python", f'''from pathlib import Path
CTL = "{CTL}"
STATE = Path("/run/example.state")
class Thing:
    def method(self, argument):
        local = 1
        Path("/run/example.out").write_text("x")
        with open(CTL, mode="w") as out:
            out.write(argument)
        return STATE.read_text()
'''.encode())
    assert any(s[0] == CTL and s[4] == "CTL" for s in facts.strings) and any(s[0] == "/run/example.state" and s[4] == "STATE" for s in facts.strings)
    assert ("/run/example.out", "path", 7, "use", None, "method", "write_text", "write") in facts.strings
    assert ("CTL", 8, "method", "open", "write") in facts.flows
    assert {("Thing", "class"), ("method", "function"), ("CTL", "variable")} <= {(n, k) for n, k, _l, _e in facts.defs}
    assert not {"local", "argument"} & set(facts.refs)


def test_a_method_with_a_common_name_isnt_taken_for_a_file():
    assert not extract("javascript", b"items.remove(n); doors.open(n);\n").flows


def test_rust():
    facts = extract("rust", f'''const CTL: &str = "{CTL}";
struct Daemon {{ fd: i32 }}
trait Run {{ fn run(&self); }}
fn send() {{
    let quiet = 1;
    let file = File::create(CTL);
    other::helper(quiet);
}}
'''.encode())
    assert {("CTL", "constant"), ("Daemon", "struct"), ("Run", "trait"), ("run", "function"), ("send", "function")} <= {(n, k) for n, k, _l, _e in facts.defs}
    assert (CTL, "path", 1, "define", "CTL", None, None, None) in facts.strings and ("CTL", 6, "send", "File::create", "write") in facts.flows
    assert "quiet" not in facts.refs and "helper" in facts.refs


def test_javascript():
    facts = extract("javascript", f'''const CTL = "{CTL}";
function send(argument) {{ const inner = 1; fs.writeFileSync(CTL, argument); helper(inner); }}
const arrow = () => 1;
class Thing {{ method() {{ return 1; }} }}
'''.encode())
    assert {("send", "function"), ("arrow", "function"), ("Thing", "class"), ("method", "method"), ("CTL", "variable")} <= {(n, k) for n, k, _l, _e in facts.defs}
    assert (CTL, "path", 1, "define", "CTL", None, None, None) in facts.strings and ("CTL", 2, "send", "fs.writeFileSync", "write") in facts.flows
    assert not {"inner", "argument"} & set(facts.refs) and "helper" in facts.refs


def test_the_first_lines_of_a_name_are_kept_in_order():
    source = b"int shared_thing;\n" + b"".join(b"int f%d(void) { return shared_thing; }\n" % i for i in range(40))
    facts = extract("c", source)
    assert facts.refs["shared_thing"] == [40, list(range(2, 14))]


def test_the_same_file_gives_the_same_facts_in_every_process():
    """Captures come in an order that changes from run to run, and reusing a file's facts relies on them not depending on that."""
    source = "".join(f'#define M{i} "/run/m{i}"\nint f{i}(void) {{ open(M{i}, O_WRONLY); return g(M0); }}\n' for i in range(30))
    code = ("import sys, dataclasses, json; sys.path.insert(0, sys.argv[1]); from codemap.extract import extract;"
            "print(json.dumps(dataclasses.asdict(extract('c', sys.argv[2].encode()))))")
    seen = {subprocess.run([sys.executable, "-c", code, str(REPO), source], capture_output=True, text=True, check=True, env={**os.environ, "PYTHONHASHSEED": str(seed)}).stdout for seed in range(5)}
    assert len(seen) == 1


def test_lines_from_a_script_in_a_string_are_kept_in_order_too():
    source = b"docker run a sh -c '\n" + b"".join(b"tool_name x\n" for _ in range(20)) + b"'\ntool_name y\n"
    assert extract("shell", source).refs["tool_name"] == [21, list(range(2, 14))]


@pytest.mark.parametrize("language, source", [("c", '#include <x.h>\nvoid f(void) {{ g({}); }}\n'), ("c", '#include <x.h>\nvoid f(void) {{ unlink({}); }}\n'), ("shell", 'rm {}\n'), ("python", 'g({})\n'), ("python", 'open({})\n')])
def test_a_call_with_thousands_of_paths_doesnt_take_forever(language, source):
    separator = " " if language == "shell" else ", "
    paths = separator.join((f"/run/p{i}" if language == "shell" else f'"/run/p{i}"') for i in range(4000))
    started = time.monotonic()
    assert len(extract(language, source.format(paths).encode()).strings) == 4000
    assert time.monotonic() - started < 5  # it was 10.9 s


def test_noise_and_ordinary_strings_arent_kept():
    assert not extract("c", b'void f(void) { puts("hello world"); open("/dev/null", 0); g("/api/route"); }\n').strings


@pytest.mark.parametrize("path, head, language", [
    ("a.c", None, "c"), ("a.h", None, "c"), ("a.py", None, "python"), ("a.mjs", None, "javascript"), ("a.sh", None, "shell"), ("a.rs", None, "rust"), ("dir/APKBUILD", None, "shell"),
    ("a.cpp", None, None), ("README.md", None, None), ("tool", None, None), ("tool", b"#!/bin/sh\n", "shell"), ("tool", b"#!/usr/bin/env python3\n", "python"), ("tool", b"#!/sbin/openrc-run\n", "shell"),
    ("tool", b"#!/usr/bin/env -S node\n", "javascript"), ("tool", b"\x7fELF", None), ("tool", b"#!/usr/bin/perl\n", None)])
def test_which_language(path, head, language):
    assert language_of(path, head) == language


# --- building ------------------------------------------------------------------------
@pytest.fixture
def work(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git("init", "-q", "-b", "main", cwd=root)
    commit(root, {"one.c": "int used(void) { return 1; }\n", "two.c": "int user(void) { return used(); }\n", "script": "#!/bin/sh\necho hi\n", "notes.md": "# no\n", "more.cpp": "int x;\n"})
    return root


def query(path, sql, *args):
    db = sqlite3.connect(path)
    try:
        return db.execute(sql, args).fetchall()
    finally:
        db.close()


def test_a_build_says_its_commit_and_what_it_doesnt_cover(work, tmp_path):
    out = str(tmp_path / "map.sqlite")
    stats = build(str(work), out)
    assert stats["commit"] == git("rev-parse", "HEAD", cwd=work) and stats["parsed"] == 3 and stats["reused"] == 0 and stats["bytes"] > 0
    assert stats["languages"] == {"c": 2, "shell": 1}
    assert dict(query(out, "SELECT suffix, files FROM uncovered")) == {".md": 1, ".cpp": 1}
    assert not os.path.exists(f"{out}.new")


def test_only_what_changed_is_read_again(work, tmp_path):
    out = str(tmp_path / "map.sqlite")
    build(str(work), out)
    commit(work, {"two.c": "int user(void) { return used() + used(); }\n", "notes.md": None})
    git("mv", "script", "renamed", cwd=work)
    git("commit", "-qm", "move", cwd=work)
    again = build(str(work), out, previous=out)
    assert (again["parsed"], again["reused"], again["files"]) == (1, 2, 3)
    assert query(out, "SELECT r.count FROM refs r JOIN names n ON n.id = r.name_id JOIN files f ON f.id = r.file_id WHERE n.name = 'used' AND f.path = 'two.c'") == [(2,)]
    assert query(out, "SELECT d.line FROM defs d JOIN names n ON n.id = d.name_id JOIN files f ON f.id = d.file_id WHERE n.name = 'used' AND f.path = 'one.c'") == [(1,)]  # carried, and still right
    assert ("renamed",) in query(out, "SELECT path FROM files") and ("script",) not in query(out, "SELECT path FROM files")
    assert query(out, "SELECT used_files FROM symbols s JOIN names n ON n.id = s.name_id WHERE n.name = 'used'") == [(1,)]


def test_a_new_extractor_reads_everything_again(work, tmp_path, monkeypatch):
    out = str(tmp_path / "map.sqlite")
    build(str(work), out)
    monkeypatch.setattr("codemap.build.EXTRACTOR", 999)
    assert build(str(work), out, previous=out)["reused"] == 0


def test_a_last_map_that_cant_be_read_is_only_a_slower_build(work, tmp_path):
    out = tmp_path / "map.sqlite"
    out.write_bytes(b"not a database at all, just some bytes" * 100)
    stats = build(str(work), str(out), previous=str(out))
    assert stats["parsed"] == 3 and len(query(out, "SELECT * FROM files")) == 3


def test_links_arent_followed_and_only_whats_committed_is_read(work, tmp_path):
    secret = tmp_path / "outside.c"
    secret.write_text("int outside_secret;\n")
    (work / "link.c").symlink_to(secret)
    git("add", "-A", cwd=work)
    git("commit", "-qm", "link", cwd=work)
    (work / "uncommitted.c").write_text("int not_committed;\n")
    out = str(tmp_path / "map.sqlite")
    build(str(work), out)
    names = {n for n, in query(out, "SELECT name FROM names")}
    assert not {"outside_secret", "not_committed"} & names and ("link.c",) not in query(out, "SELECT path FROM files")


def test_a_file_too_large_is_counted_not_read(work, tmp_path):
    commit(work, {"huge.c": "int a;\n" * (MAX_FILE // 7 + 1)})
    out = str(tmp_path / "map.sqlite")
    assert build(str(work), out)["too_large"] == 1 and ("huge.c",) not in query(out, "SELECT path FROM files")


# --- the service ---------------------------------------------------------------------
class FakeGh:
    def __init__(self, repos):
        self.repos = repos

    async def run(self, argv, *_a):
        return {"code": 0, "stdout": json.dumps(self.repos), "stderr": ""}


async def plain_git(*args, cwd=None):
    done = await asyncio.create_subprocess_exec("git", *args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = await done.communicate()
    if done.returncode != 0:
        raise RuntimeError(err.decode())
    return out.decode()


@pytest.fixture
def org(tmp_path):
    remote = tmp_path / "remote"
    sources = {
        "daemon": {"src/daemon.c": f'#define CTL "{CTL}"\nint daemon_main(void) {{ mkfifo(CTL, 0600); return open(CTL, O_RDWR); }}\n'},
        "client": {"client.c": f'#define THE_FIFO "{CTL}"\nvoid hint(void) {{ int fd = open(THE_FIFO, O_WRONLY); daemon_main(); }}\n', "test.sh": f"#!/bin/sh\necho stats > {CTL}\n", "more.cpp": "int a;\n"},
        "upstream": {"huge.c": "int only_in_the_fork;\n"},
    }
    for name, files in sources.items():
        work = remote / name
        work.mkdir(parents=True)
        git("init", "-q", "-b", "main", cwd=work)
        git("config", "uploadpack.allowFilter", "true", cwd=work)
        commit(work, files)
    gh = FakeGh([{"name": "daemon", "fork": False, "private": True}, {"name": "client", "fork": False, "private": False}, {"name": "upstream", "fork": True, "private": False}])
    seeds = Seeds(tmp_path / "seeds", plain_git, gh, f"file://{remote}/", btrfs="no-such-btrfs")
    maps = CodeMaps(tmp_path / "codemap", seeds, python=Path(sys.executable), sandbox=False, source=REPO, bwrap="no-such-bwrap", installed=Path(sys.executable))
    asyncio.run(seeds.refresh_all())
    return maps, seeds, remote


def group(reply, repo):
    return next(g for g in reply["repos"] if g["repo"] == repo)


def test_who_writes_to_this_fifo_across_repositories_with_commits(org):
    maps, seeds, _remote = org
    asyncio.run(maps._round())
    reply = maps.string(CTL, everything=True)
    assert reply["caveat"] == CAVEAT and reply["covers"] == ["C", "Python", "JavaScript", "Shell", "Rust"]
    assert reply["by_access"]["write"] == 2 and reply["by_access"]["create"] == 1 and reply["by_access"]["read and write"] == 1
    client = group(reply, "client")
    assert client["commit"] == seeds.status()["repos"]["client"]["commit"]
    assert client["defines"] == [{"string": CTL, "path": "client.c", "line": 1, "constant": "THE_FIFO", "shape": "path"}]
    # The C writer names only the macro, so a search for the path doesn't find this line.
    assert {"via": "THE_FIFO", "path": "client.c", "line": 2, "function": "hint", "call": "open", "access": "write"} in client["uses"]
    assert {"string": CTL, "path": "test.sh", "line": 2, "function": None, "call": ">", "access": "write"} in client["uses"]
    assert {"via": "CTL", "path": "src/daemon.c", "line": 2, "function": "daemon_main", "call": "mkfifo", "access": "create"} in group(reply, "daemon")["uses"]
    assert group(reply, "daemon")["private"] is True and client["private"] is False


def test_forks_are_never_built_and_every_reply_says_so(org):
    maps, _seeds, _remote = org
    asyncio.run(maps._round())
    assert not maps.path("upstream").exists()
    assert {"repo": "upstream", "private": False, "why": codemap_module._FORK} in maps.definition("only_in_the_fork")["not_searched"]
    for call in (lambda: maps.overview("upstream"), lambda: maps.definition("x", "upstream"), lambda: maps.usages("x", "upstream"), lambda: maps.string("x", "upstream")):
        with pytest.raises(MapError, match="fork"):
            call()


def test_a_repository_that_doesnt_say_counts_as_a_fork(tmp_path, org):
    maps, seeds, _remote = org
    status = seeds.status()
    del status["repos"]["daemon"]["fork"]
    seeds._write_status(status)
    asyncio.run(maps._round())
    assert not maps.path("daemon").exists() and maps.path("client").exists()


def test_a_fork_that_has_a_map_loses_it(org):
    maps, seeds, _remote = org
    asyncio.run(maps._round())
    status = seeds.status()
    status["repos"]["daemon"]["fork"] = True
    seeds._write_status(status)
    asyncio.run(maps._round())
    assert not maps.path("daemon").exists()


def test_definitions_and_usages_with_repository_path_line_and_commit(org):
    maps, seeds, _remote = org
    asyncio.run(maps._round())
    found = maps.definition("daemon_main", "daemon")
    assert [g["repo"] for g in found["repos"]] == ["daemon"]
    assert found["repos"][0]["commit"] == seeds.status()["repos"]["daemon"]["commit"]
    assert found["repos"][0]["rows"][0] == {"path": "src/daemon.c", "line": 2, "end_line": 2, "kind": "function", "language": "c"}
    used = maps.usages("daemon_main")  # by name, across repositories
    assert group(used, "client")["rows"][0]["path"] == "client.c" and group(used, "client")["rows"][0]["lines"] == [2] and group(used, "client")["defined_here"] == 0
    touching = maps.usages("THE_FIFO", "client")["repos"][0]["rows"][0]
    assert touching["touches_a_file"] == [{"line": 2, "function": "hint", "call": "open", "access": "write"}]
    assert used["caveat"] == CAVEAT and found["caveat"] == CAVEAT


def test_finding_nothing_says_what_the_map_doesnt_read(org):
    maps, _seeds, _remote = org
    asyncio.run(maps._round())
    for reply in (maps.definition("no_such_name"), maps.usages("no_such_name"), maps.string("/run/no-such-thing")):
        assert reply["repos"] == [] and "doesn't prove" in reply["note"] and reply["not_covered_files"] == [{"repo": "client", "private": False, "files": 1}]


def test_overviews(org):
    maps, _seeds, _remote = org
    asyncio.run(maps._round())
    one = maps.overview("daemon")
    assert one["main_files"][0]["path"] == "src/daemon.c" and one["languages"] == {"c": 1} and one["caveat"] == CAVEAT and one["private"] is True
    assert one["most_used"] == []  # nothing else in this one repository uses it
    assert one["shared_strings"] == [{"string": CTL, "shape": "path", "defined_in": ["client", "daemon"], "used_in": ["client"], "private_repos": ["daemon"]}]
    client = maps.overview("client")
    assert client["not_covered_by_suffix"] == {".cpp": 1} and client["not_covered_files"] == 1 and client["private"] is False
    everything = maps.overview(everything=True)
    assert {m["repo"] for m in everything["maps"]} == {"client", "daemon"} and everything["shared_strings"][0]["private_repos"] == ["daemon"]
    assert [r["repo"] for r in everything["not_searched"]] == ["upstream"]


@pytest.mark.parametrize("call", [lambda m: m.definition(""), lambda m: m.definition(None), lambda m: m.usages(["a"]), lambda m: m.string("a\nb"), lambda m: m.string("x" * 301),
                                  lambda m: m.overview("../../etc"), lambda m: m.definition("x", "not-ours"), lambda m: m.string("x", 3)])
def test_odd_queries_get_a_clear_error(org, call):
    maps, _seeds, _remote = org
    asyncio.run(maps._round())
    with pytest.raises(MapError):
        call(maps)


def test_a_query_is_only_ever_a_value(org):
    maps, _seeds, _remote = org
    asyncio.run(maps._round())
    for text in ("%", "_", "' OR 1=1 --", '"; DROP TABLE strings; --'):
        assert maps.string(text)["repos"] == [] and maps.definition(text)["repos"] == []
    assert maps.string(CTL)["repos"]


def test_a_config_key_is_found_from_a_whole_setting(tmp_path, org):
    maps, seeds, remote = org
    commit(remote / "client", {"s.sh": "echo deadband=4 > /run/x.ctl\n"})
    asyncio.run(seeds.refresh("client"))
    asyncio.run(maps._round())
    assert group(maps.string("deadband=9"), "client")["uses"][0]["string"] == "deadband="


def test_a_push_reaches_the_map_at_the_next_refresh_with_no_manual_step(org):
    maps, seeds, remote = org
    seeds.on_change = maps.kick
    seeds.auto = True

    async def go():
        await seeds.refresh_all()
        maps.kick()  # as hubd's loop does after each round, for what's not mapped yet
        await maps._task
        before = maps.definition("added_later", "daemon")
        moved = commit(remote / "daemon", {"new.c": "int added_later;\n"})
        await seeds.refresh("daemon")
        await maps._task
        return before, moved, maps.definition("added_later", "daemon")
    before, moved, after = asyncio.run(go())
    assert before["repos"] == [] and after["repos"][0]["commit"] == moved and after["repos"][0]["rows"][0]["path"] == "new.c"


def test_a_map_behind_its_copy_says_so(org):
    maps, seeds, remote = org
    asyncio.run(maps._round())
    moved = commit(remote / "daemon", {"new.c": "int x;\n"})
    asyncio.run(seeds.refresh("daemon"))
    behind = group(maps.string(CTL, "daemon"), "daemon")
    assert moved in behind["map_behind"] and behind["commit"] != moved


def test_a_failed_build_leaves_the_last_map_says_so_and_isnt_repeated(org, monkeypatch):
    maps, seeds, remote = org
    asyncio.run(maps._round())
    good = maps._commit_of("daemon")
    commit(remote / "daemon", {"new.c": "int x;\n"})
    asyncio.run(seeds.refresh("daemon"))
    runs = []

    async def fails(_argv, _scratch):
        runs.append(1)
        return "the parser fell over"
    monkeypatch.setattr(maps, "_run", fails)
    asyncio.run(maps._round())
    asyncio.run(maps._round())
    assert len(runs) == 1 and maps._commit_of("daemon") == good
    assert "the parser fell over" in group(maps.string(CTL, "daemon"), "daemon")["map_failed"]
    assert maps.report()["failed"][0]["repo"] == "daemon" and "the parser fell over" in maps.report()["failed"][0]["error"]
    assert not list((maps.root / "trees").iterdir()) and not list((maps.root / "building").iterdir())  # nothing left behind


def test_without_its_parser_the_map_says_how_to_get_it(org, tmp_path):
    maps, _seeds, _remote = org
    maps.installed = tmp_path / "nothing" / "requirements.txt"
    asyncio.run(maps._round())
    with pytest.raises(MapError, match="deploy/install.sh"):
        maps.overview("daemon")
    assert maps.overview()["maps"] == []
    assert "deploy/install.sh" in maps.report()["failed"][0]["error"]


def test_installing_the_parser_brings_the_map_back_with_no_push(org, tmp_path):
    maps, _seeds, _remote = org
    missing = tmp_path / "later" / "requirements.txt"
    maps.installed = missing
    asyncio.run(maps._round())
    assert not maps.path("daemon").exists()
    missing.parent.mkdir()
    missing.write_text("installed")
    asyncio.run(maps._round())
    assert maps.overview("daemon")["languages"] == {"c": 1} and maps.report()["failed"] == []


def test_a_half_installed_parser_counts_as_not_installed(tmp_path):
    maps = CodeMaps(tmp_path / "codemap", None)
    assert maps.installed == tmp_path / "codemap" / "venv" / "requirements.txt"


def test_a_failure_on_this_host_is_tried_again_after_a_while(org, monkeypatch):
    maps, _seeds, _remote = org
    real, runs = maps._run, []

    async def fails_once(argv, scratch):
        runs.append(1)
        return "the disk was full" if len(runs) == 1 else await real(argv, scratch)
    monkeypatch.setattr(maps, "_run", fails_once)
    asyncio.run(maps.build("daemon"))
    asyncio.run(maps._round())
    assert not maps.path("daemon").exists() and len(runs) == 2  # client built; daemon waits its turn
    status = maps.status()
    status["daemon"]["tried"] -= codemap_module.RETRY_FAILED + 1
    maps._status_file.write_text(json.dumps(status))
    asyncio.run(maps._round())
    assert maps.path("daemon").exists() and "daemon" not in {f["repo"] for f in maps.report()["failed"]}


# --- private repositories ------------------------------------------------------------
def test_with_no_repository_named_private_ones_are_skipped_and_listed(org):
    maps, _seeds, _remote = org
    asyncio.run(maps._round())
    for reply in (maps.string(CTL), maps.definition("daemon_main"), maps.usages("daemon_main"), maps.overview()):
        assert {"repo": "daemon", "private": True, "why": codemap_module._PRIVATE} in reply["not_searched"]
        assert "daemon" not in {g["repo"] for g in reply.get("repos", ())} and "daemon" not in {m["repo"] for m in reply.get("maps", ())}
    assert not maps.definition("daemon_main")["repos"]
    assert [g["repo"] for g in maps.string(CTL)["repos"]] == ["client"]
    assert maps.overview()["shared_strings"] == []  # it's shared only with a private repository
    assert maps.overview("client")["shared_strings"] == []


def test_a_private_repository_answers_when_named_and_says_so(org):
    maps, _seeds, _remote = org
    asyncio.run(maps._round())
    assert group(maps.string(CTL, "daemon"), "daemon")["private"] is True
    assert maps.definition("daemon_main", "daemon")["repos"][0]["private"] is True
    assert maps.usages("CTL", "daemon")["repos"][0]["private"] is True


def test_a_session_that_reads_the_whole_project_gets_all_of_them_labelled(org):
    maps, _seeds, _remote = org
    asyncio.run(maps._round())
    reply = maps.string(CTL, everything=True)
    assert {g["repo"]: g["private"] for g in reply["repos"]} == {"client": False, "daemon": True}
    assert [r["repo"] for r in reply["not_searched"]] == ["upstream"]


def test_a_repository_that_doesnt_say_counts_as_private(org):
    maps, seeds, _remote = org
    asyncio.run(maps._round())
    status = seeds.status()
    del status["repos"]["client"]["private"]
    seeds._write_status(status)
    assert maps.string(CTL)["repos"] == []


# --- a damaged map, and a build that can't be trusted --------------------------------
@pytest.mark.parametrize("damage", ["garbage", "no-meta-row", "wrong-types", "link"])
def test_one_bad_map_takes_only_itself_out(org, damage):
    maps, seeds, _remote = org
    status = seeds.status()
    status["repos"]["daemon"]["private"] = False  # so it's searched with nothing named
    seeds._write_status(status)
    asyncio.run(maps._round())
    bad = maps.path("daemon")
    if damage == "garbage":
        bad.write_bytes(b"not a database" * 200)
    elif damage == "link":
        bad.unlink()
        bad.symlink_to(maps.path("client"))
    else:
        db = sqlite3.connect(bad)
        db.execute("DELETE FROM meta WHERE key = 'built'" if damage == "no-meta-row" else "UPDATE refs SET lines = 'not numbers'")
        db.commit()
        db.close()
    # The other repository still answers, whichever way it's asked.
    assert group(maps.string(CTL), "client")["uses"] and group(maps.usages("daemon_main"), "client")["rows"] and maps.overview("client")["languages"]
    assert maps.overview()["maps"]
    # And the damaged one is reported, not silently missing or passed off as another.
    asked = maps.usages("CTL") if damage == "wrong-types" else maps.string(CTL)
    assert "daemon" not in {g["repo"] for g in asked["repos"]}
    why = next(r["why"] for r in asked["not_searched"] if r["repo"] == "daemon")
    assert why == ("no map yet" if damage == "link" else "its map can't be read")


def test_a_link_never_serves_another_repositorys_map_under_this_name(org):
    maps, _seeds, _remote = org
    asyncio.run(maps._round())
    public = maps.path("client")
    public.unlink()
    public.symlink_to(maps.path("daemon"))
    with pytest.raises(MapError):
        maps.definition("daemon_main", "client")


def test_a_bad_map_that_was_named_says_so(org):
    maps, _seeds, _remote = org
    asyncio.run(maps._round())
    maps.path("client").write_bytes(b"not a database" * 200)
    with pytest.raises(MapError, match="couldn't be read"):
        maps.string(CTL, "client")
    with pytest.raises(MapError, match="couldn't be read"):
        maps.overview("client")


def fake_builder(tmp_path, script: str) -> Path:
    fake = tmp_path / "fake-python"
    fake.write_text("#!/bin/sh\n" + script)
    fake.chmod(0o755)
    return fake


def test_a_build_cant_put_a_link_where_maps_are_kept(org, tmp_path):
    maps, _seeds, _remote = org
    asyncio.run(maps._round())
    before = maps.path("client").read_bytes()
    maps.python = fake_builder(tmp_path, 'ln -s "%s" "$5"\n' % maps.path("daemon"))
    asyncio.run(maps.build("client"))  # it's up to date, but asked anyway
    assert not maps.path("client").is_symlink() and maps.path("client").read_bytes() == before
    assert "no usable map" in maps.status()["client"]["error"]


def test_a_build_that_writes_nonsense_or_the_wrong_commit_isnt_published(org, tmp_path):
    maps, _seeds, _remote = org
    maps.python = fake_builder(tmp_path, 'echo nonsense > "$5"\n')
    assert not asyncio.run(maps.build("daemon")) and not maps.path("daemon").exists()
    made = tmp_path / "other.sqlite"
    db = sqlite3.connect(made)
    db.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    db.execute("INSERT INTO meta VALUES ('commit', 'some-other-commit')")
    db.commit()
    db.close()
    maps.python = fake_builder(tmp_path, 'cp "%s" "$5"\n' % made)
    assert not asyncio.run(maps.build("daemon")) and not maps.path("daemon").exists() and "some-other-commit" in maps.status()["daemon"]["error"]


def test_only_a_bounded_part_of_what_a_build_says_is_kept(org, tmp_path):
    maps, _seeds, _remote = org
    maps.python = fake_builder(tmp_path, 'head -c 20000000 /dev/zero | tr "\\0" x >&2\necho the-end >&2\nexit 1\n')
    assert not asyncio.run(maps.build("daemon"))
    error = maps.status()["daemon"]["error"]
    assert len(error) <= codemap_module.MAX_ERROR and error.endswith("the-end")


def test_a_build_that_writes_too_much_is_stopped_and_cleared(org, tmp_path, monkeypatch):
    maps, _seeds, _remote = org
    monkeypatch.setattr(codemap_module, "MAX_SCRATCH", 1_000_000)
    maps.python = fake_builder(tmp_path, 'head -c 400000 /dev/zero > "$5.a"; head -c 400000 /dev/zero > "$5.b"; head -c 400000 /dev/zero > "$5.c"; exec sleep 30\n')
    assert not asyncio.run(maps.build("daemon"))
    assert "wrote more than" in maps.status()["daemon"]["error"] and not list((maps.root / "building").iterdir())


def test_a_build_that_never_ends_is_stopped(org, tmp_path, monkeypatch):
    maps, _seeds, _remote = org
    monkeypatch.setattr(codemap_module, "BUILD_TIMEOUT", 1)
    maps.python = fake_builder(tmp_path, "exec sleep 30\n")
    assert not asyncio.run(maps.build("daemon")) and "no result" in maps.status()["daemon"]["error"]


def test_maps_are_only_ours_to_read(org):
    maps, _seeds, _remote = org
    asyncio.run(maps._round())
    for folder in (maps.root, maps.root / "maps", maps.root / "maps" / "daemon", maps.root / "trees", maps.root / "building"):
        assert folder.stat().st_mode & 0o777 == 0o700, folder
    assert maps.path("daemon").stat().st_mode & 0o777 == 0o600


def test_a_reply_fits_what_a_planner_can_read(org):
    maps, seeds, remote = org
    lines = "".join(f"#define NAME_{i} NAME_0\n" for i in range(1, 800))
    files = {f"f{i}.c": f"int fine_name;\n{lines}int g{i}(void) {{ return fine_name; }}\n" for i in range(300)}
    commit(remote / "daemon", files)
    asyncio.run(seeds.refresh("daemon"))
    asyncio.run(maps._round())
    for reply in (maps.definition("fine_name"), maps.usages("fine_name"), maps.overview("daemon")):
        assert len(json.dumps(reply)) <= codemap_module.MAX_REPLY


def test_limits_reach_the_builder(org, tmp_path):
    maps, _seeds, _remote = org
    seen = tmp_path / "seen"
    maps.python = fake_builder(tmp_path, f'ulimit -v > "{seen}"; ulimit -f >> "{seen}"; nice >> "{seen}"\nexit 1\n')
    asyncio.run(maps.build("daemon"))
    values = seen.read_text().split()
    assert int(values[0]) == limits.MAX_MEMORY // 1024 and int(values[1]) * 512 in (limits.MAX_OUTPUT, limits.MAX_OUTPUT * 2) and int(values[2]) >= 15


def test_the_sandbox_names_only_what_the_builder_needs(org, tmp_path):
    maps, _seeds, _remote = org
    maps.sandbox = True
    previous = tmp_path / "kept" / "map.sqlite"
    previous.parent.mkdir()
    previous.write_text("last")
    argv = maps._argv(tmp_path / "tree", tmp_path / "scratch", previous)
    assert argv[0] == "no-such-bwrap" and "--unshare-all" in argv and "--share-net" not in argv and "--clearenv" in argv
    binds = [argv[i + 1] for i, a in enumerate(argv) if a in ("--bind", "--ro-bind", "--ro-bind-try")]
    assert binds == ["/usr", "/bin", "/sbin", "/lib", "/lib64", str(Path(sys.executable).parent.parent), str(REPO / "codemap"), str(tmp_path / "tree"), str(previous), str(tmp_path / "scratch")]
    # The only place it can write, and it isn't where maps are kept.
    assert [argv[i + 1] for i, a in enumerate(argv) if a == "--bind"] == [str(tmp_path / "scratch")]


def _bwrap_works() -> bool:
    if not shutil.which("bwrap"):
        return False
    return subprocess.run(["bwrap", "--unshare-all", "--ro-bind", "/usr", "/usr", "--ro-bind-try", "/lib", "/lib", "--ro-bind-try", "/lib64", "/lib64", "--ro-bind-try", "/bin", "/bin", "/usr/bin/true"], capture_output=True).returncode == 0


if os.environ.get("HUB_REQUIRE_SANDBOX") and not _bwrap_works():
    raise RuntimeError("HUB_REQUIRE_SANDBOX is set and bubblewrap doesn't work here")


@pytest.mark.skipif(not _bwrap_works(), reason="no working bubblewrap here")
def test_the_real_sandbox_holds(org, tmp_path):
    maps, _seeds, _remote = org
    maps.sandbox, maps.bwrap = True, "bwrap"
    asyncio.run(maps._round())  # with no sandbox, for a last map to protect
    outside = tmp_path / "outside-the-sandbox"
    outside.write_text("no")
    other = maps.path("client")
    before = maps.path("daemon").read_bytes()
    venv = tmp_path / "venv" / "bin"
    venv.mkdir(parents=True)
    fake = venv / "python"
    fake.write_text(f"""#!/bin/sh
tree="$4"; out="$5"; previous="$7"
{{
  [ -e "{outside}" ] && echo saw-outside
  [ -e "{other}" ] && echo saw-another-map
  [ -e "{Path.home()}/.ssh" ] && echo saw-home
  [ -d "$tree/.git" ] || echo no-tree
  touch "$tree/written" 2>/dev/null && echo wrote-tree
  {{ echo x >> "$previous"; }} 2>/dev/null && echo wrote-last-map
  [ -e "$previous" ] || echo no-last-map
  touch "{tmp_path}/written" 2>/dev/null
  touch "$out" || echo no-scratch
  env | grep -q AGENT_SECRET && echo saw-env
  git -C "$tree" rev-parse HEAD >/dev/null 2>&1 || echo no-git
  echo the-end
}} >&2
exit 1
""")
    fake.chmod(0o755)
    maps.python = fake
    os.environ["AGENT_SECRET"] = "x"
    try:
        assert not asyncio.run(maps.build("daemon"))
    finally:
        del os.environ["AGENT_SECRET"]
    assert maps.status()["daemon"]["error"] == "the-end"
    assert not (tmp_path / "written").exists()  # inside it's a scratch root that's gone afterwards, so only this side can tell
    assert maps.path("daemon").read_bytes() == before


@pytest.mark.skipif(not _bwrap_works() or not sys.base_prefix.startswith("/usr"), reason="needs bubblewrap, and a Python under /usr")
def test_the_real_builder_runs_in_the_real_sandbox_and_again_on_its_last_map(org):
    maps, seeds, remote = org
    maps.sandbox, maps.bwrap = True, "bwrap"
    assert asyncio.run(maps.build("daemon")), maps.status()
    commit(remote / "daemon", {"new.c": "int added_later;\n"})
    asyncio.run(seeds.refresh("daemon"))
    assert asyncio.run(maps.build("daemon")), maps.status()
    meta = dict(query(maps.path("daemon"), "SELECT key, value FROM meta"))
    assert (meta["parsed"], meta["reused"]) == ("1", "1")
    assert maps.definition("added_later", "daemon")["repos"][0]["rows"][0]["path"] == "new.c"


# --- who can use it ------------------------------------------------------------------
def test_the_tools_go_where_the_other_repository_readers_go():
    assert all(set(MAP_TOOLS) <= set(tools) for tools in PLANNER_TOOLS.values())
    assert not any(set(MAP_TOOLS) & set(tools) for tools in DRAFT_TOOLS.values())
    assert set(MAP_TOOLS) <= set(LIBRARY.action("project-steward")["hub_tools"])
    for action in LIBRARY.actions.values():
        if "request_repository" in action["hub_tools"]:
            assert set(MAP_TOOLS) <= set(action["hub_tools"]), action["id"]
        if "request_repository" not in action["hub_tools"] and action["id"] != "project-steward":
            assert not set(MAP_TOOLS) & set(action["hub_tools"]), action["id"]


def test_hubd_holds_each_token_to_its_list():
    calls = []

    class FakeAgents:
        def scope(self, token):
            return {"has": {"session": "s", "tools": ["map_string"]}, "other": {"session": "s", "tools": ["read_repo_file"]}, "full": {"session": "f", "tools": None},
                    "steward": {"session": "t", "tools": ["map_string"], "all_repos": True}}.get(token)

        async def repo_map(self, tool, **args):
            calls.append((tool, args))
            return {"repos": []}
    h = Hubd.__new__(Hubd)
    h.agents = FakeAgents()
    ask = lambda **req: asyncio.run(h.repo_request(req.pop("op"), req))
    assert ask(op="repos.map_string", agent_token="has", text="x", repo="a")["ok"] and calls == [("string", {"text": "x", "repo": "a", "everything": False})]
    assert ask(op="repos.map_usages", agent_token="has", symbol="x")["refused"]
    assert ask(op="repos.map_string", agent_token="other", text="x")["refused"]
    assert ask(op="repos.map_string", agent_token="general", text="x")["refused"]
    assert ask(op="repos.map_overview", agent_token="full", repo="a")["ok"] and calls[-1] == ("overview", {"repo": "a", "everything": False})
    # A request can't ask for more reach: it comes from the token.
    assert ask(op="repos.map_string", agent_token="has", text="x", everything=True, all_repos=True)["ok"] and calls[-1][1]["everything"] is False
    assert ask(op="repos.map_string", agent_token="steward", text="x")["ok"] and calls[-1][1]["everything"] is True


def test_the_app_only_passes_requests_on():
    source = (REPO / "app" / "hub" / "github.py").read_text() + (REPO / "app" / "hub" / "tools.py").read_text()
    assert "tree_sitter" not in source and "sqlite3" not in source


def test_the_app_sends_each_tool_on_with_the_callers_token():
    sys.path.insert(0, str(REPO / "app"))
    from hub.github import GitHub
    from hub.hubd_client import CALLER

    class FakeHubd:
        def __init__(self):
            self.calls = []

        async def call(self, **request):
            self.calls.append(request)
            return {"ok": True, "repos": []}
    service = GitHub.__new__(GitHub)
    service.hubd = FakeHubd()

    async def go():
        CALLER.set("session-token")
        return [await service.repo_map("overview", repo="a"), await service.repo_map("definition", symbol="s", repo=""), await service.repo_map("string", text="t", repo="a")]
    assert all("ok" not in r for r in asyncio.run(go()))
    assert service.hubd.calls == [{"op": "repos.map_overview", "agent_token": "session-token", "repo": "a"}, {"op": "repos.map_definition", "agent_token": "session-token", "symbol": "s", "repo": ""},
                                  {"op": "repos.map_string", "agent_token": "session-token", "text": "t", "repo": "a"}]


def test_a_refusal_from_the_map_reaches_the_session_as_words(tmp_path):
    from hubd.agents import AgentError, Agents
    from hubd.shells import Shells
    agents = Agents(LIBRARY, Shells(default_cwd=str(tmp_path)), tmp_path / "state", agent_token="t")
    assert agents.seeds.on_change == agents.maps.kick and agents.maps.path("x") == tmp_path / "state" / "codemap" / "maps" / "x" / "map.sqlite"
    assert agents.maps.python == tmp_path / "state" / "codemap" / "venv" / "bin" / "python"  # where deploy/install.sh puts it
    with pytest.raises(AgentError, match="isn't a repository"):
        asyncio.run(agents.repo_map("overview", repo="nope"))
    assert asyncio.run(agents.repo_map("definition", symbol="x", repo=None, everything=True))["repos"] == []
    assert agents.repo_copies()["maps"] == {"mapped": 0, "forks": [], "failed": []}


def test_hubd_doesnt_load_the_parser():
    assert not any("tree_sitter" in p.read_text() or "codemap.build" in p.read_text() and "import" in p.read_text().split("codemap.build")[0].splitlines()[-1] for p in (REPO / "hubd").glob("*.py"))


def test_the_pins_are_the_same_in_both_places():
    wanted = set((REPO / "deploy" / "codemap-requirements.txt").read_text().split())
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text())
    assert wanted <= set(pyproject["project"]["optional-dependencies"]["dev"]) and all("==" in w for w in wanted)
