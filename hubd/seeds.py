# SPDX-License-Identifier: GPL-2.0-or-later
"""The hub's own copy of each repository in the organization, and snapshots of them for sessions.

A seed is a clone only the hub writes to, never a main checkout, so ignored files such as secrets
can't reach a session. It has its default branch and no tags, and no file contents beyond its
current tree until someone asks: a read-only snapshot has no credentials to fetch more, which the
tools say. A refresh works on a snapshot of the seed and replaces it only when complete, so a
snapshot never catches a half-updated tree, and a failed one leaves the last good copy.

Btrfs makes a snapshot of any size near-instant. Elsewhere it's `cp --reflink=auto`, which is a
plain copy where the filesystem can't share. Standard library only, like the rest of hubd.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import time
from pathlib import Path

log = logging.getLogger("hubd.seeds")

FRESH = 300  # seconds: a seed checked this recently isn't checked again before a session starts
WAIT_FOR_REFRESH = 20  # seconds a request waits for a newer copy before giving what there is
COPY_TIMEOUT = 1800  # seconds for a plain copy, on a host that has to make one
SUBVOLUME_ROOT_INODE = 256  # on Btrfs, what makes a folder a subvolume
MAX_LISTED = 5000
MAX_READ = 40_000  # characters of one reply: a planner has no way to read a longer one that Claude Code saves to a file
_REPO_RE = re.compile(r"\.?[A-Za-z0-9_][A-Za-z0-9._-]*")


class SeedError(Exception):
    pass


async def _run(*argv: str, timeout: int = COPY_TIMEOUT) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(*argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except OSError as e:
        return 127, str(e)
    try:
        _out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, f"{argv[0]} gave no result in {timeout} s"
    return proc.returncode, err[-300:].decode(errors="replace").strip()


def _is_subvolume(path: Path) -> bool:
    try:
        return os.stat(path).st_ino == SUBVOLUME_ROOT_INODE
    except OSError:
        return False


async def make_root(path: Path, btrfs: str = "btrfs") -> None:
    """An empty folder for a seed, which can be snapshotted if this host can do that."""
    code, _err = await _run(btrfs, "subvolume", "create", str(path))
    if code != 0:
        path.mkdir()


async def snapshot(source: Path, into: Path, read_only: bool = False, btrfs: str = "btrfs") -> str:
    """A separate tree. Says how it was made."""
    if _is_subvolume(source):
        code, err = await _run(btrfs, "subvolume", "snapshot", *(["-r"] if read_only else []), str(source), str(into))
        if code == 0:
            return "snapshot"
        log.warning("no snapshot of %s: %s", source, err)
    code, err = await _run("cp", "-a", "--reflink=auto", "--", str(source), str(into))
    if code != 0:
        await remove_tree(into, btrfs)
        raise SeedError(f"couldn't copy {source.name}: {err}")
    if read_only:
        await asyncio.to_thread(_chmod_tree, into, False)
    return "copy"


def _chmod_tree(root: Path, writable: bool) -> None:
    """Folders on the way down when opening them up, or they can't be listed; on the way back when closing."""
    def change(path: str) -> None:
        mode = stat.S_IMODE(os.lstat(path).st_mode)
        os.chmod(path, (mode | stat.S_IRWXU) if writable else (mode & ~0o222))
    if writable:
        change(str(root))
    for parent, folders, files in os.walk(root, topdown=writable):
        for name in folders:
            path = os.path.join(parent, name)
            if not os.path.islink(path):
                change(path)
        if not writable:
            for name in files:
                path = os.path.join(parent, name)
                if not os.path.islink(path):
                    change(path)
    if not writable:
        change(str(root))


async def remove_tree(path: Path, btrfs: str = "btrfs") -> None:
    """Without root: this host's mount doesn't let `btrfs subvolume delete` run, and an empty subvolume goes with rmdir.
    A read-only one has to be made writable first. Raises if anything is left."""
    if not os.path.lexists(path):
        return
    if os.path.islink(path):  # never through a link to whatever it points at
        os.unlink(path)
        return
    if _is_subvolume(path):
        await _run(btrfs, "property", "set", "-f", str(path), "ro", "false")
    await asyncio.to_thread(_chmod_tree, path, True)
    await asyncio.to_thread(shutil.rmtree, path)


def _repo_list(text: str) -> list[dict]:
    """gh --paginate gives one JSON array per page, however it happens to join them."""
    decoder, at, found = json.JSONDecoder(), 0, []
    text = text.strip()
    while at < len(text):
        page, at = decoder.raw_decode(text, at)
        found.extend(page)
        while at < len(text) and text[at].isspace():
            at += 1
    return found


def age_in_words(seconds: float) -> str:
    if seconds < 90:
        return "just now"
    if seconds < 5400:
        return f"{round(seconds / 60)} min ago"
    if seconds < 129600:
        return f"{round(seconds / 3600)} h ago"
    return f"{round(seconds / 86400)} days ago"


class Seeds:
    """git is a coroutine like Agents._git; fetching is what the network commands need put in front of them."""

    def __init__(self, root: Path, git, gh, clone_base: str, fetching: tuple[str, ...] = (), org: str = "GlassineOS", btrfs: str = "btrfs"):
        self.root = root
        self.git = git
        self.gh = gh
        self.clone_base = clone_base
        self.fetching = fetching
        self.org = org
        self.btrfs = btrfs
        self.auto = False  # hubd's own loop turns this on, so nothing refreshes unless a hub is running
        self.on_change = None  # called with no arguments when a copy has moved to a new commit
        self.live = root / "live"
        self._next = root / "next"
        self._old = root / "old"
        self._status_file = root / "status.json"
        self._refreshing: dict[str, asyncio.Lock] = {}  # for as long as a refresh of it runs
        self._swapping: dict[str, asyncio.Lock] = {}  # while it's being replaced, or read from or copied
        self._round: asyncio.Task | None = None

    # --- what's known ---------------------------------------------------------------
    def status(self) -> dict:
        try:
            return json.loads(self._status_file.read_text())
        except (OSError, ValueError):
            return {"repos": {}, "listed": None, "list_error": None}

    def _write_status(self, status: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        scratch = self._status_file.with_suffix(".new")
        scratch.write_text(json.dumps(status))
        scratch.replace(self._status_file)

    def _note(self, repo: str, **fields) -> None:
        status = self.status()
        status["repos"].setdefault(repo, {}).update(fields)
        self._write_status(status)

    def path(self, repo: str) -> Path:
        return self.live / repo

    def _known(self, repo) -> dict:
        if not (isinstance(repo, str) and _REPO_RE.fullmatch(repo) and ".." not in repo):
            raise SeedError(f"not a repository name: {repo}")
        record = self.status()["repos"].get(repo)
        if record is None:
            raise SeedError(f"{repo} isn't a repository of the organization that the hub knows of. Code outside the organization stays out of reach: say you couldn't check it")
        return record

    def about(self, repo: str, record: dict | None = None, now: float | None = None) -> dict:
        """What a reply says about the copy: which commit, how old, whether the last refresh failed, whether it's private."""
        record = record if record is not None else self.status()["repos"].get(repo, {})
        now = time.time() if now is None else now
        about = {"repo": repo, "commit": record.get("commit"), "private": record.get("private", True)}
        if record.get("refreshed"):
            about["refreshed"] = age_in_words(now - record["refreshed"])
        if record.get("error"):
            about["refresh_failed"] = f"{age_in_words(now - record['tried'])}: {record['error']}. This is the last good copy."
        return about

    # --- refreshing -----------------------------------------------------------------
    async def list_repos(self) -> list[dict] | None:
        """From the organization, not workspace.toml, which doesn't name them all. If that fails the last list stands, and it says so."""
        if self.gh is None:
            return None
        reply = await self.gh.run(["api", "--paginate", f"orgs/{self.org}/repos?per_page=100"])
        status = self.status()
        error = None
        repos = None
        if reply["code"] != 0:
            error = reply["stderr"].strip()[-300:] or f"gh exited with {reply['code']}"
        else:
            try:
                repos = [r for r in _repo_list(reply["stdout"]) if not r.get("archived") and _REPO_RE.fullmatch(r.get("name", "")) and ".." not in r["name"]]
            except (ValueError, TypeError, AttributeError) as e:
                error = f"GitHub's list of repositories made no sense: {e}"
        status["list_error"] = error
        if repos is not None:
            status["listed"] = time.time()
            names = {r["name"] for r in repos}
            for r in repos:
                record = status["repos"].setdefault(r["name"], {})
                record["private"] = r.get("private") is not False  # if it doesn't say, it's private
                record["fork"] = r.get("fork") is not False  # if it doesn't say, it counts as one, and the code map leaves it out
            for gone in [n for n in status["repos"] if n not in names]:
                del status["repos"][gone]
        self._write_status(status)
        if repos is None:
            log.warning("no list of repositories: %s", error)
            return None
        for gone in {p.name for p in self.live.iterdir()} - {r["name"] for r in repos} if self.live.is_dir() else ():
            try:
                await remove_tree(self.live / gone, self.btrfs)
            except OSError as e:
                log.warning("couldn't remove the copy of %s: %s", gone, e)
        return repos

    async def refresh_all(self) -> None:
        repos = await self.list_repos()
        if repos is not None:
            names = [r["name"] for r in sorted(repos, key=lambda r: r.get("size") or 0)]  # the big first clone doesn't hold up the rest
        else:
            names = sorted(self.status()["repos"])
        for name in names:
            await self.refresh(name)

    def refresh_soon(self) -> None:
        """Before a session starts: in the background, as a stalled fetch mustn't hold up a start."""
        if not self.auto or (self._round and not self._round.done()):
            return
        checked = [r.get("tried") or 0 for r in self.status()["repos"].values()]
        if checked and min(checked) > time.time() - FRESH:
            return
        self._round = asyncio.ensure_future(self.round())

    async def round(self) -> None:
        """A round of refreshes that can't stop whatever runs it."""
        try:
            await self.refresh_all()
        except Exception:  # whatever it was, the last good copies stand and the next round may go better
            log.exception("the round of refreshes failed")

    async def refresh(self, repo: str) -> bool:
        """Whether there's now a current copy. A failure is written down, for the hub to show."""
        async with self._refreshing.setdefault(repo, asyncio.Lock()):
            now = time.time()
            try:
                await self._update(repo, now)
            except Exception as e:  # git, the disk or a timeout: the last good copy stands either way
                log.warning("copy of %s not refreshed: %s", repo, e)
                self._note(repo, tried=now, error=str(e)[-300:])
                await self._drop(self._next / repo)
                return False
            return True

    async def _drop(self, path: Path) -> None:
        try:
            await remove_tree(path, self.btrfs)
        except OSError as e:
            log.warning("left %s behind: %s", path, e)

    async def _update(self, repo: str, now: float) -> None:
        for folder in (self.live, self._next, self._old):
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        scratch, seed = self._next / repo, self.live / repo
        await self._drop(scratch)  # from a stop halfway through
        if not (seed / ".git").exists():
            await self._drop(seed)
            await make_root(scratch, self.btrfs)
            await self.git(*self.fetching, "clone", "--quiet", "--filter=blob:none", "--single-branch", "--no-tags", "--template=", f"{self.clone_base}{repo}", str(scratch))
        else:
            ours = (await self.git("rev-parse", "HEAD", cwd=seed)).strip()
            theirs = (await self.git(*self.fetching, "ls-remote", "origin", "HEAD", cwd=seed)).split()
            if theirs and theirs[0] == ours:
                self._note(repo, tried=now, refreshed=now, commit=ours, error=None)
                return
            await snapshot(seed, scratch, btrfs=self.btrfs)
            await self.git(*self.fetching, "fetch", "--quiet", "--no-tags", "origin", "HEAD", cwd=scratch)
            await self.git(*self.fetching, "reset", "--quiet", "--hard", "FETCH_HEAD", cwd=scratch)
        commit = (await self.git("rev-parse", "HEAD", cwd=scratch)).strip()
        old = self._old / repo
        await self._drop(old)
        async with self._swapping.setdefault(repo, asyncio.Lock()):
            if seed.exists():
                seed.rename(old)
            try:
                scratch.rename(seed)
            except OSError:
                if old.exists():
                    old.rename(seed)
                raise
            # Inside the lock: nothing can read the new seed under the old seed's commit.
            self._note(repo, tried=now, refreshed=now, commit=commit, error=None)
        await self._drop(old)
        if self.on_change:
            self.on_change()

    async def ensure_fresh(self, repo: str) -> dict:
        """The copy to use: newer if one comes quickly, or else the one there is, which the reply dates."""
        record = self._known(repo)
        if record.get("tried", 0) < time.time() - FRESH or not self.path(repo).exists():
            task = asyncio.ensure_future(self.refresh(repo))
            try:
                await asyncio.wait_for(asyncio.shield(task), WAIT_FOR_REFRESH)
            except TimeoutError:
                pass
        if not (self.path(repo) / ".git").exists():
            raise SeedError(f"{repo} is still being copied for the first time: ask again in a few minutes")
        return self.status()["repos"][repo]

    # --- giving it out --------------------------------------------------------------
    async def take(self, repo: str, place, read_only: bool) -> tuple[str, Path, bool]:
        """A tree of the seed where place(commit) says, under a temporary name until it's complete, so a stop halfway
        leaves nothing that passes for a tree. The commit is read from the seed in the same lock as the copy: it's what
        this tree holds, whatever a refresh does around it. Returns the commit, the path, and whether it was already there."""
        async with self._swapping.setdefault(repo, asyncio.Lock()):
            self._ready(repo)
            commit = (await self.git("rev-parse", "HEAD", cwd=self.path(repo))).strip()
            into = place(commit)
            if os.path.lexists(into):
                return commit, into, True
            scratch = into.with_name(f".{into.name}.new")
            await remove_tree(scratch, self.btrfs)  # from a stop halfway through
            await snapshot(self.path(repo), scratch, read_only, self.btrfs)
            scratch.rename(into)
            return commit, into, False

    async def files(self, repo, path: str = "", recursive: bool = False) -> dict:
        record = self._known(repo)
        where = _inside(path)
        async with self._swapping.setdefault(repo, asyncio.Lock()):
            self._ready(repo)
            cwd = self.path(repo)
            commit = (await self.git("rev-parse", "HEAD", cwd=cwd)).strip()
            if where:
                try:
                    kind = (await self.git("cat-file", "-t", f"{commit}:{where}", cwd=cwd)).strip()
                except Exception as e:
                    raise SeedError(f"nothing at {where} in the copy of {repo}") from e
                if kind != "tree":
                    raise SeedError(f"{where} is a file: use read_repo_file")
            # -z: without it git quotes any name that isn't plain ASCII, and that quoted name opens nothing.
            listing = await self.git("ls-tree", "-z", *(["-r"] if recursive else []), commit, "--", *([where + "/"] if where else []), cwd=cwd)
        rows = [row for row in listing.split("\0") if row]
        entries = []
        for row in rows[:MAX_LISTED]:
            head, _tab, name = row.partition("\t")
            kind = head.split()[1] if len(head.split()) > 1 else "?"
            entries.append({"path": name, "kind": {"tree": "folder", "blob": "file", "commit": "submodule"}.get(kind, kind)})
        reply = {**self.about(repo, {**record, "commit": commit}), "entries": entries}
        if len(rows) > MAX_LISTED:
            reply["cut"] = f"{len(rows) - MAX_LISTED} more not listed: name a folder"
        return reply

    async def read(self, repo, path, start_line: int = 1, max_lines: int | None = None) -> dict:
        record = self._known(repo)
        where = _inside(path)
        if not where:
            raise SeedError("name a file: list_repo_files shows what's there")
        if not isinstance(start_line, int) or isinstance(start_line, bool) or start_line < 1:
            raise SeedError("start_line counts from 1")
        if max_lines is not None and (not isinstance(max_lines, int) or isinstance(max_lines, bool) or max_lines < 1):
            raise SeedError("max_lines has to be a positive number")
        async with self._swapping.setdefault(repo, asyncio.Lock()):
            self._ready(repo)
            cwd = self.path(repo)
            commit = (await self.git("rev-parse", "HEAD", cwd=cwd)).strip()
            try:
                text = await self.git("cat-file", "blob", f"{commit}:{where}", cwd=cwd)
            except Exception as e:
                raise SeedError(f"no file {where} in the copy of {repo}") from e
        about = self.about(repo, {**record, "commit": commit})
        if "\0" in text:
            return {**about, "path": where, "binary": True, "text": ""}
        lines = text.split("\n")
        chosen = lines[start_line - 1:][:max_lines]
        kept, size = [], 0
        for line in chosen:
            size += len(line) + 1
            if size > MAX_READ and kept:
                break
            kept.append(line)
        body = "\n".join(kept)[:MAX_READ]
        reply = {**about, "path": where, "start_line": start_line, "total_lines": len(lines), "text": body}
        if len(kept) < len(chosen) or len(body) < len("\n".join(kept)):
            reply["cut"] = f"cut at {MAX_READ} characters: read on with start_line {start_line + len(kept)}"
        return reply

    def _ready(self, repo: str) -> None:
        if not (self.path(repo) / ".git").exists():
            raise SeedError(f"{repo} hasn't been copied yet: ask again in a few minutes")

    def report(self) -> dict:
        """For the page: each copy in words, and any failure."""
        status, now = self.status(), time.time()
        return {"listed": age_in_words(now - status["listed"]) if status.get("listed") else None, "list_error": status.get("list_error"),
                "repos": [self.about(name, record, now) | {"copied": (self.path(name) / ".git").exists()} for name, record in sorted(status["repos"].items())]}


def _inside(path) -> str:
    """A path in the repository as git will name it. It only ever reaches git's object lookup, never the filesystem."""
    if path is None:
        return ""
    if not isinstance(path, str) or any(ord(c) < 32 for c in path) or len(path) > 4096:
        raise SeedError("not a path")
    clean = path.strip("/")
    if any(part in ("", ".", "..") for part in clean.split("/")) and clean:
        raise SeedError("name the path from the top of the repository, with no . or ..")
    return clean
