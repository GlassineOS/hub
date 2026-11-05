# SPDX-License-Identifier: GPL-2.0-or-later
"""Past sessions and cleaning up: what's removed is only what's safe, looked at again at the time."""
import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from hubd.agents import _ORIGIN_REPO_RE, ENDED_FILE, AgentError, Agents, Library
from hubd.ghpolicy import check
from hubd.history import History

LIBRARY = Library(Path(__file__).parents[1] / "agents")


class FakeGh:
    """Holds the real policy to every call, as the real one does."""

    def __init__(self):
        self.prs = {}
        self.fail = False

    async def run(self, argv, *_a, **_k):
        check(argv)
        if self.fail:
            return {"code": 1, "stdout": "", "stderr": "no network"}
        query = parse_qs(urlsplit(argv[-1]).query)
        head = query["head"][0].split(":", 1)[1]
        assert query["head"][0].startswith("GlassineOS:") and query["state"] == ["all"]
        return {"code": 0, "stdout": json.dumps(self.prs.get(head, [])), "stderr": ""}


class FakeShells:
    def __init__(self):
        self.live, self.made, self.killed = set(), [], []

    async def list(self):
        return [{"name": n} for n in self.live]

    async def new(self, name, cwd, command):
        self.live.add(name)
        self.made.append(name)

    async def kill(self, name):
        self.live.discard(name)
        self.killed.append(name)


def git(cwd, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A workspace with a checkout of boot, its remote, and a Claude config dir for transcripts."""
    remote = tmp_path / "remote" / "boot"
    remote.mkdir(parents=True)
    git(remote, "init", "-q", "-b", "main")
    (remote / "a").write_text("a")
    git(remote, "add", "a"); git(remote, "commit", "-qm", "base")
    claude = tmp_path / "claude"
    claude.write_text("#!/bin/sh\n")
    claude.chmod(0o755)
    gh = FakeGh()
    a = Agents(LIBRARY, FakeShells(), tmp_path / "state", claude=str(claude), mcp_url="u", agent_token="t",
               clone_base=str(tmp_path / "remote") + "/", gh=gh, workspace=tmp_path / "ws",
               environment={"CLAUDE_CONFIG_DIR": str(tmp_path / "cc")})
    return a, gh, tmp_path


def transcript(tmp_path, session_id, *rows):
    folder = tmp_path / "cc" / "projects" / "x"
    folder.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"type": role, "message": {"content": text}}) for role, text in rows]
    (folder / f"{session_id}.jsonl").write_text("\n".join(lines + ["not json", '{"type": "system"}']) + "\n")


def full_session(a, name="s", number=1):
    config = {**a.defaults("issue-implement", "boot", number), "name": name}
    return asyncio.run(a.start(config))["name"]


def run(coroutine):
    return asyncio.run(coroutine)


def test_a_session_that_ends_is_remembered_with_its_last_words(world):
    a, _gh, tmp = world
    name = full_session(a)
    record = json.loads((a.sessions / name / "session.json").read_text())
    transcript(tmp, record["session_id"], ("user", "Do it"), ("assistant", "Done it"), ("user", "Thanks"), ("assistant", "Bye"))
    a.shells.live.discard(name)
    assert run(a.forget(name)) is None
    row = run(a.past())[0]
    assert (row["name"], row["kind"], row["worktree"], row["turns"], row["last"]) == (name, "ended", "removed", 2, "Bye")


def test_the_steward_isnt_listed(world):
    a, _gh, tmp = world
    run(a.start(a.defaults("project-steward", None, None)))
    a.shells.live.clear()
    assert run(a.past()) == []
    run(a.forget("steward"))
    assert run(a.past()) == []


def test_a_running_session_isnt_past_and_a_lost_one_is_interrupted(world):
    a, _gh, _tmp = world
    name = full_session(a)
    assert run(a.past()) == []
    a.shells.live.discard(name)
    row = run(a.past())[0]
    assert (row["kind"], row["worktree"], row["transcript"]) == ("interrupted", "kept", False)
    a.shells.live.add(name)
    (a.sessions / name / ENDED_FILE).write_text("")
    assert run(a.past())[0]["kind"] == "finished"


def test_restore_and_resume_brings_the_checkout_back_at_the_same_path(world):
    a, _gh, tmp = world
    name = full_session(a)
    session_id = json.loads((a.sessions / name / "session.json").read_text())["session_id"]
    transcript(tmp, session_id, ("user", "x"))
    into = a.work / name / "boot"
    assert into.is_dir()
    a.shells.live.discard(name)
    run(a.forget(name))
    assert not into.exists()
    assert run(a.resume_past(session_id))["name"] == name
    assert (into / ".git").exists() and name in a.shells.live
    assert (a.sessions / name / "persona.md").read_text() and (a.sessions / name / "prompt.md").read_text()
    assert a.history.get(session_id) is None
    assert git(into, "rev-parse", "--abbrev-ref", "HEAD").strip() == f"agent/{name}"


def test_resume_keeps_the_record_if_it_fails_and_refuses_a_taken_name(world):
    a, _gh, tmp = world
    name = full_session(a)
    session_id = json.loads((a.sessions / name / "session.json").read_text())["session_id"]
    a.shells.live.discard(name)
    run(a.forget(name))
    with pytest.raises(AgentError, match="transcript is gone"):
        run(a.resume_past(session_id))
    assert a.history.get(session_id) and not (a.sessions / name).exists()
    transcript(tmp, session_id, ("user", "x"))
    full_session(a)
    with pytest.raises(AgentError, match="in use"):
        run(a.resume_past(session_id))
    assert a.history.get(session_id)


@pytest.mark.parametrize("bad", ["../../etc/passwd", None, 3, "x" * 100])
def test_a_transcript_is_only_for_a_session_the_hub_ran(world, bad):
    a, _gh, _tmp = world
    with pytest.raises(AgentError):
        run(a.past_transcript(bad))


def test_an_unknown_id_doesnt_read_another_transcript(world):
    a, _gh, tmp = world
    transcript(tmp, "aaaaaaaa-1111", ("user", "someone else's"))
    with pytest.raises(AgentError):
        run(a.past_transcript("aaaaaaaa-1111"))


def test_search_finds_words_and_ignores_case(world):
    a, _gh, tmp = world
    name = full_session(a)
    session_id = json.loads((a.sessions / name / "session.json").read_text())["session_id"]
    transcript(tmp, session_id, ("user", "Look at the LUT table"))
    a.shells.live.discard(name)
    assert "LUT" in run(a.past_search("lut"))["matches"][session_id]
    assert run(a.past_search("nothing like this"))["matches"] == {}
    with pytest.raises(AgentError):
        run(a.past_search("x"))


def transcripts_long(tmp_path):
    transcript(tmp_path, "b" * 12, *[("assistant", f"m{i}") for i in range(250)])
    return next((tmp_path / "cc" / "projects").glob("*/*.jsonl"))


def test_a_long_transcript_says_what_it_left_out(tmp_path):
    read = History.read(transcripts_long(tmp_path))
    assert read["cut"] == 50 and read["messages"][-1]["text"] == "m249"


# --- cleaning up ------------------------------------------------------------------------------
def row_of(a, name):
    return next(r for r in run(a.cleanup_scan()) if r["id"] == name)


def ended(a, name):
    a.shells.live.discard(name)
    return a.work / name / "boot"


def test_running_is_in_use(world):
    a, _gh, _tmp = world
    assert row_of(a, full_session(a))["state"] == "inuse"


def test_clean_and_on_github_is_safe_and_the_commands_force_nothing(world):
    a, _gh, _tmp = world
    name = full_session(a)
    ended(a, name)
    row = row_of(a, name)
    assert row["state"] == "safe" and row["commands"]
    assert not any("--force" in c or " -f" in c for c in row["commands"])
    assert "_argv" not in row


@pytest.mark.parametrize("change,word", [("dirty", "uncommitted"), ("commit", "not on GitHub"), ("ignored", "ignored")])
def test_anything_only_here_is_review_first_and_cant_be_removed(world, change, word):
    a, _gh, _tmp = world
    name = full_session(a)
    into = ended(a, name)
    if change == "dirty":
        (into / "new").write_text("x")
    elif change == "commit":
        (into / "new").write_text("x")
        git(into, "add", "new"); git(into, "commit", "-qm", "local")
    else:
        (into / "built").write_text("x")
        info = Path(git(into, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()) / "info"
        info.mkdir(exist_ok=True)
        (info / "exclude").write_text("built\n")
    row = row_of(a, name)
    assert row["state"] == "review" and word in row["what"]
    result = run(a.cleanup_remove([name]))
    assert result["removed"] == [] and word in result["failed"][0]["error"] and into.exists()


def test_an_open_pull_request_keeps_it(world):
    a, gh, _tmp = world
    name = full_session(a)
    ended(a, name)
    gh.prs[f"agent/{name}"] = [pr(6, "merged", "2026-01-01T00:00:00Z"), pr(7, "open")]
    assert row_of(a, name)["state"] == "keep"
    assert run(a.cleanup_remove([name]))["removed"] == []


def test_if_github_cant_say_it_stays(world):
    a, gh, _tmp = world
    name = full_session(a)
    ended(a, name)
    gh.fail = True
    assert row_of(a, name)["state"] == "review"


def test_someone_elses_worktree_is_never_ours(world):
    a, _gh, tmp = world
    name = full_session(a)
    main = a.main_checkout("boot")
    mine = a.work / "my-own-work" / "boot"
    git(main, "worktree", "add", "-q", "-b", "my-branch", str(mine))
    row = row_of(a, "my-own-work")
    assert row["state"] == "other" and row["commands"] == []
    assert run(a.cleanup_remove(["my-own-work"]))["removed"] == [] and mine.exists()
    assert name


def test_removing_leaves_it_resumable_and_says_so(world):
    a, _gh, tmp = world
    name = full_session(a)
    session_id = json.loads((a.sessions / name / "session.json").read_text())["session_id"]
    transcript(tmp, session_id, ("user", "x"))
    into = ended(a, name)
    assert run(a.cleanup_remove([name])) == {"removed": [name], "failed": []}
    assert not into.exists() and not (a.sessions / name).exists()
    row = run(a.past())[0]
    assert row["id"] == session_id and row["worktree"] == "removed" and row["kind"] == "interrupted"


def test_a_read_only_checkout_with_no_remote_refs_is_safe(world, tmp_path):
    a, _gh, _tmp = world
    repo = tmp_path / "bare-source"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "a").write_text("a")
    git(repo, "add", "a"); git(repo, "commit", "-qm", "x")
    name = "pr-review-boot-1"
    (a.sessions / name / "checkout").mkdir(parents=True)
    (a.sessions / name / "session.json").write_text(json.dumps({"session_id": "c" * 12, "name": name, "config": a.defaults("pr-review", "boot", 1)}))
    git(repo, "worktree", "add", "-q", "--detach", str(a.sessions / name / "checkout" / "boot"))
    assert row_of(a, name)["state"] == "safe"


def test_a_change_between_the_page_and_the_click_is_seen(world):
    a, _gh, _tmp = world
    name = full_session(a)
    into = ended(a, name)
    assert row_of(a, name)["state"] == "safe"
    (into / "new").write_text("just now")
    assert run(a.cleanup_remove([name]))["removed"] == [] and into.exists()


@pytest.mark.parametrize("ids", [None, [], "x", ["../x"], [1]])
def test_bad_ids_are_refused(world, ids):
    a, _gh, _tmp = world
    with pytest.raises(AgentError):
        run(a.cleanup_remove(ids))


def pr(number, state, merged_at=None, sha="0" * 40):
    return {"number": number, "state": "closed" if state == "merged" else state, "merged_at": merged_at, "head": {"sha": sha}}


def tip(a, name, repo="boot"):
    return git(a.work / name / repo, "rev-parse", "HEAD").strip()


def merged(a, gh, name, days):
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days * 86400))
    gh.prs[f"agent/{name}"] = [pr(7, "closed", stamp, tip(a, name))]


def test_on_its_own_only_merged_long_enough_ago_and_only_if_on(world):
    a, gh, _tmp = world
    young, old, no_pr = full_session(a, "young"), full_session(a, "old"), full_session(a, "nopr")
    for name in (young, old, no_pr):
        ended(a, name)
    merged(a, gh, young, 2)
    merged(a, gh, old, 8)
    a.cleanup_settings(False)
    assert run(a.cleanup_after_merge()) == []
    a.cleanup_settings(True)
    assert run(a.cleanup_after_merge()) == [old]
    assert (a.work / young / "boot").exists() and (a.work / no_pr / "boot").exists()


def push_commit(a, name, repo="boot", file="work"):
    into = a.work / name / repo
    (into / file).write_text("x")
    git(into, "add", file)
    git(into, "commit", "-qm", "work")
    git(into, "push", "-q", "origin", f"agent/{name}")
    return into


def test_a_commit_after_the_merge_isnt_due_on_its_own(world):
    a, gh, _tmp = world
    name = full_session(a)
    ended(a, name)
    merged(a, gh, name, 8)
    push_commit(a, name)
    row = row_of(a, name)
    assert row["state"] == "safe" and row["merged_at"] is None and "after pull request #7" in row["what"]
    assert run(a.cleanup_after_merge()) == [] and (a.work / name / "boot").exists()


def test_a_branch_deleted_on_github_isnt_called_on_github(world):
    a, gh, tmp = world
    name = full_session(a)
    push_commit(a, name)
    ended(a, name)
    assert row_of(a, name)["state"] == "safe"
    git(tmp / "remote" / "boot", "update-ref", "-d", f"refs/heads/agent/{name}")
    row = row_of(a, name)
    assert row["state"] == "review" and "isn't on GitHub" in row["what"]


def test_removal_clears_the_branch_and_starting_point_and_the_session(world):
    a, gh, tmp = world
    name = full_session(a)
    session_id = a.session_id_of(name)
    push_commit(a, name)  # pushed without -u: `branch -d` would refuse this one
    ended(a, name)
    assert run(a.cleanup_remove([name])) == {"removed": [name], "failed": []}
    main = a.main_checkout("boot")
    assert not (a.work / name).exists() and not (a.sessions / name).exists()
    assert git(main, "for-each-ref", f"refs/heads/agent/{name}", f"refs/remotes/origin/hub-start/{name}").strip() == ""
    assert a.history.get(session_id)["name"] == name


def submodule_session(a, tmp):
    sub = tmp / "remote" / "sub"
    sub.mkdir()
    git(sub, "init", "-q", "-b", "main")
    (sub / "s").write_text("s")
    git(sub, "add", "s")
    git(sub, "commit", "-qm", "sub")
    remote = tmp / "remote" / "boot"
    git(remote, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(sub), "sub")
    git(remote, "commit", "-qm", "add sub")
    name = full_session(a)
    into = a.work / name / "boot"
    git(into, "-c", "protocol.file.allow=always", "submodule", "update", "--init", "--quiet")
    ended(a, name)
    return name, into


def test_a_checkout_with_a_submodule_can_be_removed(world):
    a, _gh, tmp = world
    name, into = submodule_session(a, tmp)
    assert row_of(a, name)["state"] == "safe"
    assert run(a.cleanup_remove([name]))["removed"] == [name] and not into.exists()


def test_commits_inside_a_submodule_stop_the_removal(world):
    a, _gh, tmp = world
    name, into = submodule_session(a, tmp)
    (into / "sub" / "new").write_text("n")
    git(into / "sub", "add", "new")
    git(into / "sub", "commit", "-qm", "mine")
    git(into, "add", "sub")
    git(into, "commit", "-qm", "move sub")
    git(into, "push", "-q", "origin", f"agent/{name}")
    row = row_of(a, name)
    assert row["state"] == "review" and "submodule" in row["what"]
    assert run(a.cleanup_remove([name]))["removed"] == [] and into.exists()


def test_a_starting_session_isnt_removed(world):
    a, _gh, _tmp = world
    name = full_session(a)
    ended(a, name)
    a._starting.add(name)
    assert row_of(a, name)["state"] == "inuse"
    assert run(a.cleanup_remove([name]))["removed"] == []


def test_a_session_being_removed_cant_be_restored(world):
    a, _gh, tmp = world
    name = full_session(a)
    session_id = a.session_id_of(name)
    transcript(tmp, session_id, ("user", "x"))
    a.shells.live.discard(name)
    run(a.forget(name))
    a._removing.add(name)
    with pytest.raises(AgentError, match="cleaned up"):
        run(a.resume_past(session_id))


def test_restoring_keeps_commits_github_never_had(world):
    a, _gh, tmp = world
    name = full_session(a)
    session_id = a.session_id_of(name)
    transcript(tmp, session_id, ("user", "x"))
    into = a.work / name / "boot"
    (into / "local").write_text("x")
    git(into, "add", "local")
    git(into, "commit", "-qm", "local")
    a.shells.live.discard(name)
    run(a.forget(name, discard=True))
    assert not into.exists() and a.history.get(session_id)
    run(a.resume_past(session_id))
    assert (into / "local").read_text() == "x"


def test_an_older_conversation_cant_land_on_a_later_run(world):
    a, _gh, tmp = world
    first = full_session(a, "same")
    old = a.session_id_of(first)
    transcript(tmp, old, ("user", "x"))
    a.shells.live.discard(first)
    run(a.forget(first))
    second = full_session(a, "same")
    newer = a.session_id_of(second)
    transcript(tmp, newer, ("user", "y"))
    a.shells.live.discard(second)
    run(a.forget(second))
    with pytest.raises(AgentError, match="later session"):
        run(a.resume_past(old))
    assert run(a.resume_past(newer))


def test_search_skips_a_transcript_too_long_to_read(tmp_path, monkeypatch):
    monkeypatch.setattr("hubd.history.MAX_SEARCH_BYTES", 400)
    long, short = tmp_path / "long.jsonl", tmp_path / "short.jsonl"
    short.write_text(json.dumps({"type": "user", "message": {"content": "needle"}}) + "\n")
    long.write_text(json.dumps({"type": "user", "message": {"content": "needle " + "x" * 800}}) + "\n")
    os.utime(short, (1, 1))
    found = History.search({"long": long, "short": short}, "needle")
    assert list(found["matches"]) == ["short"] and found["cut"]


def test_a_full_disk_doesnt_stop_a_session_ending(world, monkeypatch):
    a, _gh, _tmp = world
    name = full_session(a)
    def full(*_a, **_k):
        raise OSError("no space")
    monkeypatch.setattr(a.history, "add", full)
    a._remember(name)


def test_restoring_a_merged_pull_request_branch_uses_the_pull_ref(world):
    a, gh, tmp = world
    remote = tmp / "remote" / "boot"
    git(remote, "switch", "-qc", "fix-foo")
    (remote / "fix").write_text("f")
    git(remote, "add", "fix")
    git(remote, "commit", "-qm", "fix")
    git(remote, "switch", "-q", "main")
    head = git(remote, "rev-parse", "fix-foo").strip()
    git(remote, "update-ref", "refs/pull/7/head", head)
    git(remote, "branch", "-qD", "fix-foo")  # merged, and deleted as usual
    plain = gh.run

    async def viewing(argv, *x, **y):
        if argv[:2] == ["pr", "view"]:
            return {"code": 0, "stdout": json.dumps({"isCrossRepository": False, "headRefName": "fix-foo"}), "stderr": ""}
        return await plain(argv, *x, **y)
    gh.run = viewing
    into = tmp / "co" / "boot"
    run(a._checkout("pr-branch", "boot", 7, "s", into, restoring=True))
    assert (into / "fix").read_text() == "f" and git(into, "rev-parse", "--abbrev-ref", "HEAD").strip() == "fix-foo"
    with pytest.raises(AgentError):  # a new session on it still needs the branch
        run(a._checkout("pr-branch", "boot", 7, "t", tmp / "co2" / "boot"))


@pytest.mark.parametrize("url, repo", [("https://github.com/GlassineOS/.github.git", ".github"), ("git@github.com:GlassineOS/boot.git", "boot"),
                                       ("https://github.com/GlassineOS/boot", "boot")])
def test_the_repository_comes_from_origin_not_the_folder(url, repo):
    assert _ORIGIN_REPO_RE.search(url).group(1) == repo
