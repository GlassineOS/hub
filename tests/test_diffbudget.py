# SPDX-License-Identifier: GPL-2.0-or-later
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from hub import diffbudget as d
from hub.github import BadRequest, GitHub
from hubd import agents  # noqa: E402

CONFIG = Path(__file__).resolve().parents[1] / "config" / "repos.toml"


class FakeDocs:
    async def search(self, q, k=5):
        return {"query": q, "results": []}


def hunk(path, n, prefix="", ctx=3, old=None):
    body = "\n".join([f" context {i}" for i in range(ctx)] + [f"+{prefix}new {i}" for i in range(n)] + ["-gone", " tail"])
    return (f"diff --git a/{old or path} b/{path}\nindex 1..2 100644\n--- a/{old or path}\n+++ b/{path}\n@@ -1,{ctx + 2} +1,{ctx + n + 1} @@ def f():\n{body}\n")


def build(*parts):
    return "".join(parts)


def test_a_diff_under_the_budget_comes_back_unchanged():
    diff = build(hunk("a.py", 5), hunk("b.py", 2))
    assert d.compress(diff) == diff


def test_the_file_list_comes_first_with_counts_and_context_is_dropped():
    diff = build(hunk("a.py", 5, ctx=300), hunk("b.py", 2, ctx=300))
    out = d.compress(diff, budget=2000)
    assert out.index("Files:") < out.index("diff --git")
    assert "M a.py  +5 -1" in out and "M b.py  +2 -1" in out
    assert " context 0" not in out and "+new 1" in out and "@@ -1,302" in out
    assert "Unchanged context lines are left out" in out


def test_lock_files_and_binaries_are_named_with_a_reason_and_their_hunks_dropped():
    lock = hunk("package-lock.json", 800, "LOCKLINE")
    binary = "diff --git a/logo.png b/logo.png\nindex 1..2 100644\nBinary files a/logo.png and b/logo.png differ\n"
    mini = hunk("static/app.min.js", 3, "MINI")
    gen = hunk("api/x_pb2.py", 3, "GEN")
    vend = hunk("vendor/lib/x.js", 3, "VEND")
    out = d.compress(build(hunk("a.py", 5), lock, binary, mini, gen, vend), budget=3000)
    for name, why in [("package-lock.json", "lock file"), ("logo.png", "binary file"), ("app.min.js", "minified file"),
                      ("x_pb2.py", "generated file"), ("vendor/lib/x.js", "vendored file")]:
        assert name in out.split("=")[0] and why in out
    for text in ("LOCKLINE", "MINI", "GEN", "VEND"):
        assert text not in out
    assert "+800 -1" in out and "Hunks of 5 file(s) left out" in out
    assert "+new 0" in out


def test_a_giant_file_cannot_crowd_out_the_others():
    giant = hunk("big.py", 5000)
    out = d.compress(build(giant, hunk("small1.py", 10, "S1"), hunk("small2.py", 10, "S2")), budget=4000)
    assert len(out) <= 4600
    assert "+S1new 9\n" in out and "+S2new 9\n" in out  # both small files whole
    assert "of the changes to big.py are not shown" in out
    assert 'get_pr_diff(repo, number, path="...")' in out


def test_the_cut_is_always_said_in_words():
    out = d.compress(hunk("big.py", 5000), budget=2000)
    assert "Cut from this view" in out and "Changed lines cut from 1 file(s)" in out and "big.py" in out
    assert 'get_pr_diff(repo, number, path="...") fetches one file in full.' in out
    out = d.compress(hunk("big.py", 5000), more='get_pr_diff_summary(repo, number, path="...") shows one file.', budget=2000)
    assert "get_pr_diff(" not in out and "get_pr_diff_summary(" in out


def test_many_files_each_get_a_share():
    diff = build(*[hunk(f"f{i}.py", 400) for i in range(10)])
    out = d.compress(diff, budget=6000)
    assert len(out) <= 7000
    for i in range(10):
        assert f"f{i}.py" in out and f"+0 " not in out
        assert out.count(f"diff --git a/f{i}.py") == 1


def test_renames_deletions_additions_and_names_with_spaces():
    rename = ("diff --git a/old name.py b/new name.py\nsimilarity index 90%\nrename from old name.py\nrename to new name.py\n"
              "index 1..2 100644\n--- a/old name.py\n+++ b/new name.py\n@@ -1,2 +1,2 @@\n-x\n+y\n z\n")
    deleted = "diff --git a/gone.py b/gone.py\ndeleted file mode 100644\nindex 1..0\n--- a/gone.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-a\n-b\n"
    added = "diff --git a/dir with space/new.py b/dir with space/new.py\nnew file mode 100644\nindex 0..1\n--- /dev/null\n+++ b/dir with space/new.py\n@@ -0,0 +1,2 @@\n+a\n+b\n"
    mode = "diff --git a/run.sh b/run.sh\nold mode 100644\nnew mode 100755\n"
    out = d.compress(build(rename, deleted, added, mode, hunk("pad.py", 2000)), budget=3000)
    assert "R old name.py -> new name.py  +1 -1" in out
    assert "D gone.py  +0 -2" in out
    assert "A dir with space/new.py  +2 -0" in out
    assert "M run.sh  +0 -0" in out
    diff = build(rename, deleted, added)
    assert d.one_file(diff, "new name.py").startswith("diff --git a/old name.py")
    assert d.one_file(diff, "old name.py") == d.one_file(diff, "new name.py")
    assert d.one_file(diff, "gone.py").endswith("\n-a\n-b\n")
    assert "+b" in d.one_file(diff, "dir with space/new.py")


def test_a_removed_line_that_looks_like_a_header_is_still_counted():
    diff = "diff --git a/a.md b/a.md\n--- a/a.md\n+++ b/a.md\n@@ -1,2 +1,1 @@\n--- old\n+++ new\n+x\n"
    f = d.parse(diff)[0]
    assert (f.added, f.removed) == (2, 1)


def test_one_file_in_full_and_an_unknown_path_leaks_nothing():
    diff = build(hunk("a.py", 5), hunk("b.py", 2))
    assert d.one_file(diff, "b.py") == hunk("b.py", 2)
    with pytest.raises(d.Missing):
        d.one_file(diff, "c.py")
    with pytest.raises(d.Missing):
        d.one_file(diff, "/dev/null")


def test_one_file_short_is_cut_and_says_so():
    diff = hunk("big.py", 5000)
    out = d.one_file_short(diff, "big.py", more="Ask for nothing more.", budget=2000)
    assert len(out) <= 2000 and "[Cut: the last" in out and "Ask for nothing more." in out
    assert d.one_file_short(hunk("a.py", 3), "a.py", more="x") == hunk("a.py", 3)


# --- through the service -----------------------------------------------------------------------
class Fake:
    def __init__(self, diff):
        self.diff = diff

    async def gh(self, *args):
        return self.diff

    def __getattr__(self, name):
        raise AttributeError(name)


def service(diff):
    return GitHub(Fake(diff), CONFIG)


def test_the_service_serves_whole_summary_and_one_file():
    diff = build(hunk("a.py", 5), hunk("package-lock.json", 5000, "L"))
    g = service(diff)
    assert asyncio.run(g.pr_diff("hub", 3)) == diff
    assert asyncio.run(g.pr_diff("hub", 3, "a.py")) == hunk("a.py", 5)
    summary = asyncio.run(g.pr_diff_summary("hub", 3))
    assert len(summary) < len(diff) / 4 and "lock file" in summary and 'get_pr_diff_summary(repo, number, path="...")' in summary
    assert asyncio.run(g.pr_diff_summary("hub", 3, "a.py")) == hunk("a.py", 5)
    assert len(asyncio.run(g.pr_diff_summary("hub", 3, "package-lock.json"))) <= d.BUDGET


@pytest.mark.parametrize("call", ["pr_diff", "pr_diff_summary"])
@pytest.mark.parametrize("path", ["nope.py", "", 5, "../a.py"])
def test_an_unknown_path_is_a_clear_error_without_content(call, path):
    g = service(hunk("a.py", 5, "SECRETLINE"))
    with pytest.raises(BadRequest) as e:
        asyncio.run(getattr(g, call)("hub", 3, path))
    assert "SECRETLINE" not in str(e.value) and "a.py" not in str(e.value)


def test_planners_and_drafters_have_no_way_to_fetch_the_whole_diff():
    for tools in (*agents.PLANNER_TOOLS.values(), *agents.DRAFT_TOOLS.values()):
        assert "get_pr_diff" not in tools
    assert "get_pr_diff_summary" in agents.PLANNER_TOOLS["pr"] and "get_pr_diff_summary" in agents.DRAFT_TOOLS["pr"]


def test_the_tools_exist_and_are_read_only():
    from hub import tools
    listed = {t.name: t for t in asyncio.run(tools.build(service(""), FakeDocs()).list_tools())}
    for name in ("get_pr_diff", "get_pr_diff_summary"):
        assert listed[name].annotations.read_only_hint is True
        assert "path" in listed[name].input_schema["properties"] and "path" not in listed[name].input_schema.get("required", [])
