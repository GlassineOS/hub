# SPDX-License-Identifier: GPL-2.0-or-later
"""The hub's copies of the organization's repositories, and what sessions get of them.

Tests run with Btrfs only where the temporary folder is on it. Run pytest with
--basetemp under /home on this host to cover those, or they say skipped.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from hubd import machine, seeds as seeds_module
from hubd.agents import AgentError, Agents, Library, REPOS_FOLDER
from hubd.seeds import SeedError, Seeds, make_root, remove_tree, snapshot
from hubd.server import Hubd
from hubd.shells import Shells

LIBRARY = Library(Path(__file__).parents[1] / "agents")
NO_BTRFS = "no-such-btrfs"


def on_btrfs(path: Path) -> bool:
    found = subprocess.run(["stat", "-f", "-c", "%T", str(path)], capture_output=True, text=True)
    return found.stdout.strip() == "btrfs"


def run(*args, cwd):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class FakeGh:
    def __init__(self, repos=("alpha",), code=0):
        self.repos, self.code = list(repos), code

    async def run(self, argv, *_a):
        assert argv[:2] == ["api", "--paginate"]
        pages = [[{"name": r, "private": r == "secret", "size": 1, "archived": False} for r in self.repos], [{"name": "old", "archived": True}]]
        return {"code": self.code, "stdout": "".join(json.dumps(p) for p in pages), "stderr": "no network"}


async def real_git(*args, cwd=None):
    done = await asyncio.create_subprocess_exec("git", *args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = await done.communicate()
    if done.returncode != 0:
        raise RuntimeError(err.decode())
    return out.decode()


@pytest.fixture
def remote(tmp_path):
    root = tmp_path / "remote"
    work = root / "alpha"
    work.mkdir(parents=True)
    run("init", "-q", "-b", "main", cwd=work)
    (work / "a.txt").write_text("one\ntwo\nthree")
    (work / "dir").mkdir()
    (work / "dir" / "b.txt").write_text("in a folder")
    (work / "binary").write_bytes(b"\0\1\2")
    (work / ".gitignore").write_text("secret\n")
    (work / "secret").write_text("IGNORED-SECRET")
    run("add", "-A", cwd=work)
    run("commit", "-qm", "first", cwd=work)
    (work / "a.txt").write_text("one\ntwo\nthree")
    (work / "old-only").write_text("gone from the tree later")
    run("add", "-A", cwd=work)
    run("commit", "-qm", "second", cwd=work)
    run("rm", "-q", "old-only", cwd=work)
    run("commit", "-qm", "third", cwd=work)
    run("config", "uploadpack.allowFilter", "true", cwd=work)  # or git ignores the filter, and seeds aren't partial here
    return root


def seeds_at(tmp_path, remote, gh=None, btrfs=NO_BTRFS):
    return Seeds(tmp_path / "seeds", real_git, gh or FakeGh(), f"file://{remote}/", btrfs=btrfs)


def advance(remote, text="new"):
    work = remote / "alpha"
    (work / "a.txt").write_text(text)
    run("commit", "-qam", "more", cwd=work)
    return run("rev-parse", "HEAD", cwd=work)


def test_the_list_comes_from_the_organization_and_archived_ones_stay_out(tmp_path, remote):
    s = seeds_at(tmp_path, remote, FakeGh(["alpha", "secret"]))
    names = [r["name"] for r in asyncio.run(s.list_repos())]
    assert names == ["alpha", "secret"]
    status = s.status()["repos"]
    assert status["secret"]["private"] is True and status["alpha"]["private"] is False and "old" not in status


def test_a_failed_list_leaves_the_last_one_and_says_so(tmp_path, remote):
    s = seeds_at(tmp_path, remote)
    asyncio.run(s.refresh_all())
    s.gh = FakeGh(code=1)
    asyncio.run(s.refresh_all())
    report = s.report()
    assert "no network" in report["list_error"] and [r["repo"] for r in report["repos"]] == ["alpha"]
    assert report["repos"][0]["copied"]


def test_a_repository_gone_from_the_organization_loses_its_copy(tmp_path, remote):
    s = seeds_at(tmp_path, remote)
    asyncio.run(s.refresh_all())
    assert s.path("alpha").exists()
    s.gh = FakeGh([])
    asyncio.run(s.refresh_all())
    assert not s.path("alpha").exists() and s.status()["repos"] == {}


def test_a_seed_is_a_clone_and_has_no_ignored_files_or_hooks(tmp_path, remote):
    s = seeds_at(tmp_path, remote)
    asyncio.run(s.refresh_all())
    seed = s.path("alpha")
    assert (seed / "a.txt").exists() and (seed / ".git").is_dir() and not (seed / "secret").exists()
    assert not list((seed / ".git" / "hooks").glob("*")) if (seed / ".git" / "hooks").exists() else True


def test_a_failed_refresh_leaves_the_last_copy_and_the_hub_can_show_it(tmp_path, remote):
    s = seeds_at(tmp_path, remote)
    asyncio.run(s.refresh_all())
    first = s.status()["repos"]["alpha"]["commit"]
    (remote / "alpha").rename(remote / "moved")
    assert asyncio.run(s.refresh("alpha")) is False
    report = s.report()["repos"][0]
    assert "refresh_failed" in report and report["commit"] == first and report["copied"]
    assert (s.path("alpha") / "a.txt").read_text().startswith("one") and not list((tmp_path / "seeds" / "next").iterdir())
    (remote / "moved").rename(remote / "alpha")
    assert asyncio.run(s.refresh("alpha")) is True
    assert "refresh_failed" not in s.report()["repos"][0]


def test_a_refresh_replaces_the_seed_only_when_complete(tmp_path, remote):
    s = seeds_at(tmp_path, remote)
    asyncio.run(s.refresh_all())
    seen = []
    real = s.git

    async def watching(*args, cwd=None):
        if "reset" in args:
            seen.append((s.path("alpha") / "a.txt").read_text())
        return await real(*args, cwd=cwd)
    s.git = watching
    commit = advance(remote)
    assert asyncio.run(s.refresh("alpha")) is True
    assert seen and seen[0].startswith("one")  # still the old one while the next was being made
    assert (s.path("alpha") / "a.txt").read_text() == "new" and s.status()["repos"]["alpha"]["commit"] == commit


def test_an_unchanged_repository_costs_no_new_tree(tmp_path, remote):
    s = seeds_at(tmp_path, remote)
    asyncio.run(s.refresh_all())
    before = os.stat(s.path("alpha")).st_ino
    assert asyncio.run(s.refresh("alpha")) is True
    assert os.stat(s.path("alpha")).st_ino == before


@pytest.mark.parametrize("path", ["../outside", "a/../../x", "dir/./b.txt", "a\nb", "a\x00b"])
def test_paths_stay_in_the_repository(tmp_path, remote, path):
    s = seeds_at(tmp_path, remote)
    asyncio.run(s.refresh_all())
    with pytest.raises(SeedError):
        asyncio.run(s.read("alpha", path))


@pytest.mark.parametrize("repo", ["../alpha", "nothing", "a/b", "", None, "--upload-pack=x"])
def test_only_known_repositories(tmp_path, remote, repo):
    s = seeds_at(tmp_path, remote)
    asyncio.run(s.refresh_all())
    for call in (s.files(repo), s.read(repo, "a.txt"), s.ensure_fresh(repo)):
        with pytest.raises(SeedError):
            asyncio.run(call)


def test_reads_go_by_git_and_say_how_old_the_copy_is(tmp_path, remote):
    s = seeds_at(tmp_path, remote)
    asyncio.run(s.refresh_all())
    listing = asyncio.run(s.files("alpha"))
    assert {"path": "dir", "kind": "folder"} in listing["entries"] and listing["commit"] and listing["refreshed"] == "just now"
    assert [e["path"] for e in asyncio.run(s.files("alpha", "dir"))["entries"]] == ["dir/b.txt"]
    assert "dir/b.txt" in [e["path"] for e in asyncio.run(s.files("alpha", recursive=True))["entries"]]
    read = asyncio.run(s.read("alpha", "a.txt", 2, 1))
    assert read["text"] == "two" and read["total_lines"] == 3 and read["private"] is False
    assert asyncio.run(s.read("alpha", "binary"))["binary"] is True
    with pytest.raises(SeedError):
        asyncio.run(s.read("alpha", "secret"))


def test_a_read_says_where_a_long_file_was_cut(tmp_path, remote, monkeypatch):
    monkeypatch.setattr(seeds_module, "MAX_READ", 4)
    s = seeds_at(tmp_path, remote)
    asyncio.run(s.refresh_all())
    read = asyncio.run(s.read("alpha", "a.txt"))
    assert read["text"] == "one" and "cut" in read


def test_a_plain_copy_without_btrfs_can_be_read_only_and_removed(tmp_path, remote):
    s = seeds_at(tmp_path, remote)
    asyncio.run(s.refresh_all())
    into = tmp_path / "taken"
    assert asyncio.run(s.take("alpha", lambda _c: into, read_only=True))[2] is False
    assert not os.access(into / "a.txt", os.W_OK) and not os.access(into, os.W_OK)
    asyncio.run(remove_tree(into, NO_BTRFS))
    assert not into.exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores modes")
def test_btrfs_snapshots(tmp_path, remote):
    if not on_btrfs(tmp_path):
        pytest.skip("no Btrfs under the temporary folder")
    s = seeds_at(tmp_path, remote, btrfs="btrfs")
    asyncio.run(s.refresh_all())
    assert os.stat(s.path("alpha")).st_ino == seeds_module.SUBVOLUME_ROOT_INODE
    into = tmp_path / "taken"
    commit, _path, _already = asyncio.run(s.take("alpha", lambda _c: into, read_only=True))
    assert os.stat(into).st_ino == seeds_module.SUBVOLUME_ROOT_INODE and run("rev-parse", "HEAD", cwd=into) == commit
    with pytest.raises(OSError):
        (into / "new").write_text("x")
    advance(remote)
    assert asyncio.run(s.refresh("alpha"))
    assert (into / "a.txt").read_text().startswith("one") and (s.path("alpha") / "a.txt").read_text() == "new"
    asyncio.run(remove_tree(into))
    assert not into.exists() and not list((tmp_path / "seeds" / "old").iterdir())


def _with_session(tmp_path, remote, name, full, tools=("Read", "Grep", "Glob")):
    a = Agents(LIBRARY, Shells(default_cwd=str(tmp_path)), tmp_path / "state", clone_base=f"file://{remote}/", gh=FakeGh(), workspace=tmp_path / "ws", agent_token="t")
    a.seeds.btrfs = "btrfs" if on_btrfs(tmp_path) else NO_BTRFS
    directory = a.sessions / name
    directory.mkdir(parents=True)
    config = {"action": "issue-docs" if full else "pr-review", "tools": list(tools), "hub_tools": ["request_repository"], "repo": "alpha", "number": 1, "persona": "engineer", "model": "opus", "effort": "high"}
    (directory / "session.json").write_text(json.dumps({"name": name, "config": config, "full": full, "title": "t", "object": "issue", "session_id": "id"}))
    asyncio.run(a.seeds.refresh_all())
    return a, directory


def test_a_read_only_session_gets_a_tree_in_its_own_folder_and_a_newer_one_on_asking_again(tmp_path, remote):
    a, directory = _with_session(tmp_path, remote, "s", False)
    first = asyncio.run(a.request_repository("s", "alpha"))
    path = Path(first["path"])
    assert path.parent == directory / REPOS_FOLDER and (path / "a.txt").read_text().startswith("one") and first["commit"]
    assert "no credentials" in first["note"] and not os.access(path / "a.txt", os.W_OK)
    assert asyncio.run(a.request_repository("s", "alpha"))["path"] == first["path"]
    commit = advance(remote)
    asyncio.run(a.seeds.refresh("alpha"))
    second = asyncio.run(a.request_repository("s", "alpha"))
    assert second["commit"] == commit and second["path"] != first["path"]
    assert (path / "a.txt").read_text().startswith("one") and Path(second["path"], "a.txt").read_text() == "new"


def test_a_session_without_file_tools_gets_no_tree(tmp_path, remote):
    a, _directory = _with_session(tmp_path, remote, "s", False, tools=("AskUserQuestion",))
    with pytest.raises(AgentError, match="no file tools"):
        asyncio.run(a.request_repository("s", "alpha"))


@pytest.mark.parametrize("name", [None, "gone", "../s"])
def test_only_a_session_asks(tmp_path, remote, name):
    a, _directory = _with_session(tmp_path, remote, "s", False)
    with pytest.raises(AgentError, match="only a session"):
        asyncio.run(a.request_repository(name, "alpha"))


def test_removing_a_session_removes_its_snapshots(tmp_path, remote):
    a, directory = _with_session(tmp_path, remote, "s", False)
    path = Path(asyncio.run(a.request_repository("s", "alpha"))["path"])
    assert a.repo_copies()["held"][0]["session"] == "s"
    asyncio.run(a._remove("s"))
    assert not path.exists() and not directory.exists() and a.repo_copies()["held"] == []


def test_a_full_session_gets_its_own_branch_and_its_writes_stay_with_it(tmp_path, remote):
    a, _directory = _with_session(tmp_path, remote, "f", True)
    seed = a.seeds.path("alpha")
    head = run("rev-parse", "HEAD", cwd=seed)
    reply = asyncio.run(a.request_repository("f", "alpha"))
    into = Path(reply["path"])
    assert into == a.work / "f" / "alpha" and reply["commit"] == head and reply["branch"] == "agent/f"
    assert (into / ".git").is_file() and run("status", "--porcelain", cwd=into) == "" and run("rev-parse", "--abbrev-ref", "HEAD", cwd=into) == "agent/f"
    assert run("rev-parse", "HEAD", cwd=into) == head
    assert str(into) in run("worktree", "list", cwd=a.main_checkout("alpha"))
    assert not (into.parent / ".alpha.new").exists()
    (into / "a.txt").write_text("mine")
    run("commit", "-qam", "mine", cwd=into)
    assert (seed / "a.txt").read_text().startswith("one") and run("rev-parse", "HEAD", cwd=seed) == head
    # Asking again doesn't touch work in progress.
    assert "already have" in asyncio.run(a.request_repository("f", "alpha"))["note"] and (into / "a.txt").read_text() == "mine"
    assert a._present("f") == [into]


def test_a_full_session_keeps_a_requested_tree_with_work_in_it_and_discard_removes_it(tmp_path, remote):
    a, _directory = _with_session(tmp_path, remote, "f", True)
    into = Path(asyncio.run(a.request_repository("f", "alpha"))["path"])
    (into / "new").write_text("x")
    assert asyncio.run(a.forget("f")) == str(a.work / "f") and into.exists()
    assert asyncio.run(a.forget("f", discard=True)) is None
    assert not into.exists() and not (a.work / "f").exists()
    assert str(into) not in run("worktree", "list", cwd=a.main_checkout("alpha"))


def test_a_locked_session_can_reach_its_snapshots_and_a_full_one_needs_no_list(tmp_path):
    a = Agents(LIBRARY, Shells(default_cwd=str(tmp_path)), tmp_path / "state", agent_token="t")
    directory = tmp_path / "state" / "sessions" / "s"
    config = {"model": "opus", "effort": "high", "tools": ["Read"], "hub_tools": ["request_repository"]}
    locked = {"grant": machine.Grant()}
    argv = a._argv(config, locked, directory, tmp_path / "checkout", "id", tmp_path / "mcp.json")
    assert argv[argv.index("--add-dir") + 1:] == [str(tmp_path / "checkout"), str(directory / REPOS_FOLDER)]
    without = a._argv({**config, "hub_tools": []}, locked, directory, None, "id", tmp_path / "mcp.json")
    assert "--add-dir" not in without


def test_everyone_with_file_tools_can_ask_and_the_rest_read_through_tools():
    for action in LIBRARY.actions.values():
        if action["grant"].access == "full":
            continue
        if "Read" in action["grant"].tools:
            assert "request_repository" in action["grant"].hub_tools, action["id"]
    steward = LIBRARY.action("project-steward")
    assert {"list_repo_files", "read_repo_file"} <= set(steward["grant"].hub_tools) and "request_repository" not in steward["grant"].hub_tools


def test_planners_read_copies_and_the_drafter_doesnt(tmp_path):
    from hubd.agents import DRAFT_TOOLS, PLANNER_TOOLS
    assert all({"list_repo_files", "read_repo_file"} <= set(t) for t in PLANNER_TOOLS.values())
    assert not any({"list_repo_files", "read_repo_file", "request_repository"} & set(t) for t in DRAFT_TOOLS.values())
    a = Agents(LIBRARY, Shells(default_cwd=str(tmp_path)), tmp_path / "state", agent_token="t")
    told = LIBRARY.text(".", "repositories")
    assert told in a._headless_prompt("planner") and told not in a._headless_prompt("drafter")


def test_hubd_holds_each_token_to_its_list(tmp_path):
    class FakeAgents:
        def __init__(self):
            self.calls = []

        def scope(self, token):
            return {"list": {"session": "s", "tools": ["read_repo_file"]}, "full": {"session": "f", "tools": None}, "ask": {"session": "s", "tools": ["request_repository"]}}.get(token)

        async def request_repository(self, session, repo):
            self.calls.append((session, repo))
            return {"path": "p"}

        async def repo_read(self, repo, path, start, limit):
            return {"text": "x"}

        async def repo_files(self, repo, path, recursive):
            return {"entries": []}
    h = Hubd.__new__(Hubd)
    h.agents = FakeAgents()
    ask = lambda **req: asyncio.run(h.repo_request(req.pop("op"), req))
    assert ask(op="repos.request", agent_token="list", repo="a")["refused"]
    assert ask(op="repos.request", agent_token="general", repo="a")["refused"]
    assert ask(op="repos.files", agent_token="list", repo="a")["refused"]
    assert ask(op="repos.read", agent_token="list", repo="a", path="b")["text"] == "x"
    assert ask(op="repos.request", agent_token="ask", repo="a")["path"] == "p" and h.agents.calls == [("s", "a")]
    assert ask(op="repos.request", agent_token="full", repo="a")["ok"] and h.agents.calls[-1] == ("f", "a")


def test_seeds_are_really_partial_and_still_work_with_the_remote_gone(tmp_path, remote):
    s = seeds_at(tmp_path, remote)
    asyncio.run(s.refresh_all())
    missing = run("rev-list", "--objects", "--all", "--missing=print", cwd=s.path("alpha"))
    assert any(line.startswith("?") for line in missing.splitlines())
    advance(remote)
    assert asyncio.run(s.refresh("alpha")) is True  # fetches what the new tree needs
    (remote / "alpha").rename(remote / "moved")
    assert asyncio.run(s.read("alpha", "a.txt"))["text"] == "new"


def test_the_refresh_loop_goes_on_after_a_round(tmp_path, monkeypatch):
    from hubd import server
    rounds = []

    class FakeSeeds:
        auto = False

        async def round(self):
            rounds.append(1)
            if len(rounds) == 3:
                raise asyncio.CancelledError
    hubd = Hubd.__new__(Hubd)
    hubd.agents = type("A", (), {"seeds": FakeSeeds(), "maps": type("M", (), {"kick": lambda self: None})()})()
    monkeypatch.setattr(server, "TIDY_FIRST", 0)
    monkeypatch.setattr(server, "COPIES_EVERY", 0)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(server._keep_copies(hubd))
    assert len(rounds) == 3 and hubd.agents.seeds.auto


def test_a_round_survives_whatever_goes_wrong(tmp_path, remote):
    s = seeds_at(tmp_path, remote)

    async def broken():
        raise RuntimeError("no")
    s.refresh_all = broken
    asyncio.run(s.round())


def test_a_refresh_at_the_wrong_moment_cant_mislabel_a_tree(tmp_path, remote):
    """The reviewer's case: a refresh during the fetch that comes between reading a commit and taking the tree."""
    a, _directory = _with_session(tmp_path, remote, "f", True)
    real = a.seeds.ensure_fresh

    async def then_moved(repo):
        record = await real(repo)
        advance(remote)
        await a.seeds.refresh(repo)
        return record  # names the old commit, and the seed has moved on
    a.seeds.ensure_fresh = then_moved
    reply = asyncio.run(a.request_repository("f", "alpha"))
    into = Path(reply["path"])
    assert run("status", "--porcelain", cwd=into) == "" and run("rev-parse", "HEAD", cwd=into) == reply["commit"]
    assert (into / "a.txt").read_text() == "new"


def test_a_read_only_tree_is_named_for_what_it_holds(tmp_path, remote):
    a, _directory = _with_session(tmp_path, remote, "s", False)
    real = a.seeds.ensure_fresh

    async def then_moved(repo):
        record = await real(repo)
        advance(remote)
        await a.seeds.refresh(repo)
        return record
    a.seeds.ensure_fresh = then_moved
    reply = asyncio.run(a.request_repository("s", "alpha"))
    assert reply["commit"][:12] in reply["path"] and Path(reply["path"], "a.txt").read_text() == "new"
    assert run("rev-parse", "HEAD", cwd=reply["path"]) == reply["commit"]


def test_the_status_never_names_the_old_commit_for_a_new_seed(tmp_path, remote):
    s = seeds_at(tmp_path, remote)
    asyncio.run(s.refresh_all())
    seen = []
    real = seeds_module.remove_tree

    async def watching(path, btrfs="btrfs"):
        if Path(path).parent.name == "old" and os.path.lexists(path):
            seen.append((run("rev-parse", "HEAD", cwd=s.path("alpha")), s.status()["repos"]["alpha"]["commit"]))
        await real(path, btrfs)
    seeds_module.remove_tree = watching
    try:
        advance(remote)
        assert asyncio.run(s.refresh("alpha"))
    finally:
        seeds_module.remove_tree = real
    assert seen and seen[0][0] == seen[0][1]


@pytest.mark.parametrize("full", [False, True])
def test_overlapping_requests_leave_the_tree_they_handed_out(tmp_path, remote, full):
    a, _directory = _with_session(tmp_path, remote, "x", full)

    async def both():
        return await asyncio.gather(a.request_repository("x", "alpha"), a.request_repository("x", "alpha"))
    first, second = asyncio.run(both())
    assert first["path"] == second["path"] and Path(first["path"], "a.txt").exists() and "already have" in second["note"]


def test_a_partial_tree_never_passes_for_a_whole_one(tmp_path, remote):
    a, directory = _with_session(tmp_path, remote, "s", False)
    head = run("rev-parse", "HEAD", cwd=a.seeds.path("alpha"))
    scratch = directory / REPOS_FOLDER / f".alpha@{head[:12]}.new"
    scratch.mkdir(parents=True)  # a stop halfway through a copy
    (scratch / "half").write_text("x")
    reply = asyncio.run(a.request_repository("s", "alpha"))
    assert "already have" not in reply["note"] and Path(reply["path"], "a.txt").exists() and not scratch.exists()
    assert not os.path.exists(Path(reply["path"], "half")) and [h["copy"] for h in a.repo_copies()["held"]] == [Path(reply["path"]).name]
    scratch.mkdir()  # and removing the session takes such a folder too
    asyncio.run(a._remove("s"))
    assert not directory.exists()


def test_something_in_the_way_of_a_full_tree_is_left_alone(tmp_path, remote):
    a, _directory = _with_session(tmp_path, remote, "f", True)
    into = a.work / "f" / "alpha"
    into.mkdir(parents=True)
    (into / "keep").write_text("x")
    with pytest.raises(AgentError, match="in the way"):
        asyncio.run(a.request_repository("f", "alpha"))
    assert (into / "keep").exists()


def test_a_failure_while_making_a_full_tree_cleans_up_only_what_it_made(tmp_path, remote):
    a, _directory = _with_session(tmp_path, remote, "f", True)
    real = a._isolate

    async def broken(_into):
        raise AgentError("no")
    a._isolate = broken
    with pytest.raises(AgentError):
        asyncio.run(a.request_repository("f", "alpha"))
    into = a.work / "f" / "alpha"
    assert not into.exists() and not (into.parent / ".alpha.worktree").exists()
    a._isolate = real
    assert (Path(asyncio.run(a.request_repository("f", "alpha"))["path"]) / ".git").is_file()  # nothing left in the way


def test_names_that_arent_ascii_can_be_listed_and_opened(tmp_path, remote):
    work = remote / "alpha"
    (work / "café.txt").write_text("hello")
    run("add", "-A", cwd=work)
    run("commit", "-qm", "name", cwd=work)
    s = seeds_at(tmp_path, remote)
    asyncio.run(s.refresh_all())
    names = [e["path"] for e in asyncio.run(s.files("alpha"))["entries"]]
    assert "café.txt" in names and asyncio.run(s.read("alpha", "café.txt"))["text"] == "hello"


def test_listing_a_file_or_nothing_says_so(tmp_path, remote):
    s = seeds_at(tmp_path, remote)
    asyncio.run(s.refresh_all())
    with pytest.raises(SeedError, match="is a file"):
        asyncio.run(s.files("alpha", "a.txt"))
    with pytest.raises(SeedError, match="nothing at"):
        asyncio.run(s.files("alpha", "nope"))


def test_a_long_file_says_where_to_read_on(tmp_path, remote, monkeypatch):
    monkeypatch.setattr(seeds_module, "MAX_READ", 6)
    s = seeds_at(tmp_path, remote)
    asyncio.run(s.refresh_all())
    read = asyncio.run(s.read("alpha", "a.txt"))
    assert read["text"] == "one" and read["cut"].endswith("start_line 2")
    assert asyncio.run(s.read("alpha", "a.txt", 2))["text"].startswith("two")


def test_links_are_copied_as_links_and_nothing_outside_changes(tmp_path, remote):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "file").write_text("OUTSIDE")
    os.chmod(outside / "file", 0o644)
    work = remote / "alpha"
    (work / "to-file").symlink_to(outside / "file")
    (work / "to-folder").symlink_to(outside)
    run("add", "-A", cwd=work)
    run("commit", "-qm", "links", cwd=work)
    s = seeds_at(tmp_path, remote)
    asyncio.run(s.refresh_all())
    assert asyncio.run(s.read("alpha", "to-file"))["text"] == str(outside / "file")  # the link's text, not the file
    into = tmp_path / "taken"
    asyncio.run(s.take("alpha", lambda _c: into, read_only=True))
    assert (into / "to-file").is_symlink() and (into / "to-folder").is_symlink()
    assert os.access(outside / "file", os.W_OK)
    asyncio.run(remove_tree(into, NO_BTRFS))
    assert (outside / "file").read_text() == "OUTSIDE" and os.access(outside / "file", os.W_OK) and os.access(outside, os.W_OK)
    link = tmp_path / "link"
    link.symlink_to(outside)
    asyncio.run(remove_tree(link, NO_BTRFS))
    assert not link.is_symlink() and outside.is_dir() and (outside / "file").exists()


def test_the_service_passes_each_call_to_hubd_with_the_callers_token():
    sys.path.insert(0, str(Path(__file__).parents[1] / "app"))
    pytest.importorskip("mcp")
    from hub.github import GitHub
    from hub.hubd_client import CALLER

    class FakeHubd:
        def __init__(self):
            self.calls = []

        async def call(self, **request):
            self.calls.append(request)
            return {"ok": True, "path": "p"}
    service = GitHub.__new__(GitHub)
    service.hubd = FakeHubd()

    async def go():
        CALLER.set("session-token")
        return [await service.request_repository("a"), await service.repo_files("a", "d", True), await service.repo_read("a", "f", 2, 3)]
    replies = asyncio.run(go())
    assert all("ok" not in r and r["path"] == "p" for r in replies)
    assert service.hubd.calls == [{"op": "repos.request", "agent_token": "session-token", "repo": "a"},
                                  {"op": "repos.files", "agent_token": "session-token", "repo": "a", "path": "d", "recursive": True},
                                  {"op": "repos.read", "agent_token": "session-token", "repo": "a", "path": "f", "start_line": 2, "max_lines": 3}]
