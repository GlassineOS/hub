# SPDX-License-Identifier: GPL-2.0-or-later
"""Project management: one service, used by the web API and the tool server alike."""
from __future__ import annotations

import asyncio
import base64
import binascii
import difflib
import hashlib
import json
import logging
import re
import time
import tomllib
from pathlib import Path
from urllib.parse import quote

from . import diffbudget
from . import mergequeue
from . import workflowfile
from .workstore import part_of
from .hubd_client import ALL_REPOS, CALLER, INSTANCE, SESSION, GhError, Hubd, HubdError

ORG = "GlassineOS"
_REPO_RE = re.compile(r"[A-Za-z0-9._-]+")
_HEAD_RE = re.compile(r"[0-9a-f]{40}")
_ISSUE_FIELDS = "number,title,state,labels,assignees,author,createdAt,updatedAt,url,comments"
_PR_FIELDS = ("number,title,state,isDraft,labels,author,createdAt,updatedAt,url,headRefName,baseRefName,"
              "reviewDecision,mergeable,statusCheckRollup")
_PR_LIST_FIELDS = _PR_FIELDS + ",additions,deletions"  # a list row's size (006 FR-006)
_WORKFLOW_FILE_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,99}\.ya?ml")
_GIT_REF_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._/-]{0,199}")
_PART_OF_REF_RE = re.compile(r"(?:GlassineOS/)?[A-Za-z0-9._-]+#[1-9][0-9]{0,9}")
_RUN_FIELDS = "databaseId,displayTitle,workflowName,status,conclusion,event,headBranch,headSha,createdAt,updatedAt,url"
OVERVIEW_TTL = 60.0
BOARD_TTL = 120
WORKFLOWS_TTL = 3600
MAX_KEPT = 4 * 1024 * 1024  # a longer log or diff isn't worth keeping
MAX_TITLE = 256
MAX_TEXT = 65536  # GitHub's own limit for a body or a comment
MAX_KNOWN = 64  # bodies kept to say what changed, when an edit finds the issue has moved on
SHRUNK_FROM = 100  # a body shorter than this can lose most of its text without it meaning much
# Who wrote an issue the Steward may edit: the organization's own. Everyone else's it leaves alone.
OUR_AUTHORS = ("OWNER", "MEMBER")
_VERSION_RE = re.compile(r"[0-9a-f]{16}")
_COMMENT_AT_RE = re.compile(r"#issuecomment-([0-9]{1,15})\s*$")
_BOX_RE = re.compile(r"^(?P<lead>[ \t]*(?:[-*+]|[0-9]{1,9}[.)])[ \t]+\[)(?P<mark>[ xX])(?P<mid>\][ \t]+)(?P<text>.*?)[ \t]*$")
_FENCE_RE = re.compile(r"^ {0,3}(?P<run>`{3,}|~{3,})(?P<rest>.*)$")
log = logging.getLogger("hub.github")


class BadRequest(ValueError):
    pass


def _full(repo) -> str:
    if not isinstance(repo, str) or not _REPO_RE.fullmatch(repo) or ".." in repo:
        raise BadRequest(f"not a repository name: {repo}")
    return f"{ORG}/{repo}"


def _file_or_refuse(fn, diff, path, **kw) -> str:
    if not isinstance(path, str) or not path:
        raise BadRequest("path must be a file path from the pull request's file list")
    try:
        return fn(diff, path, **kw)
    except diffbudget.Missing:
        raise BadRequest("this pull request's diff has no file with that path; the file list in get_pr has the paths") from None


def _num(value) -> str:
    # Strictly: int() would read True as 1, 5.9 as 5 and "1_5" as 15.
    if not (type(value) is int or (isinstance(value, str) and re.fullmatch(r"[0-9]+", value))) or int(value) <= 0:
        raise BadRequest(f"not a number: {value}")
    return str(int(value))


def _thread(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_=-]{1,200}", value):
        raise BadRequest("not a review thread")
    return value


def _limit(value, default=30, top=200) -> str:
    return str(max(1, min(int(value or default), top)))


def _rollup(pr: dict) -> str:
    """One word for a pull request's checks."""
    checks = pr.pop("statusCheckRollup", None) or []
    states = [(c.get("conclusion") or c.get("state") or c.get("status") or "").upper() for c in checks]
    if not states:
        return "none"
    if any(s in ("FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED") for s in states):
        return "failing"
    if any(s in ("IN_PROGRESS", "QUEUED", "PENDING", "EXPECTED", "WAITING", "") for s in states):
        return "pending"
    return "passing"


LARGE_FILE = 400  # changed lines past which Files changed asks before showing a file's diff
_ERROR_LINE_RE = re.compile(r"##\[error\]|\berror\b|\bfatal:|\bFAILED\b|\bFAIL\b|Traceback|exit code [1-9]", re.I)
# Colour codes, as the escape byte or as gh writes it out (a caret and a bracket), and the BOM a log starts with.
_LOG_NOISE_RE = re.compile(r"(?:\x1b|\^\[)\[[0-9;]*m|\ufeff")
_LOG_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ?")
MAX_STEP_LINES = 2000


def _json_pages(text: str) -> list:
    """`gh api --paginate` prints one JSON array per page, joined however it happens to: read them all into one list."""
    decoder, at, found, text = json.JSONDecoder(), 0, [], text.strip()
    while at < len(text):
        page, at = decoder.raw_decode(text, at)
        found.extend(page if isinstance(page, list) else [page])
        while at < len(text) and text[at].isspace():
            at += 1
    return found


def attention_key(row: dict, waiting: int = 0):
    """007 FR-004: failing runs, then sessions waiting for you, then open pull requests, then the latest activity.
    The page adds the waiting sessions it knows of and sorts again by the same order."""
    a = row["attention"]
    last = a["last_activity"] or ""
    return (-a["failing_runs"], -waiting, -a["open_prs"], 0 if last else 1, _negated(last))


def _negated(text: str) -> tuple:
    """Newest first, for an ISO time, inside an ascending sort."""
    return tuple(-ord(c) for c in text)


def merge_blockers(pr: dict, open_threads) -> list[dict]:
    """Why Merge… is off for an open pull request, in words (006 FR-031). Empty: nothing stops it."""
    out = []
    if pr.get("checks") == "pending":
        out.append({"why": "checks are still running"})
    elif pr.get("checks") == "failing":
        # `_rollup` says failing before pending, so a failed check hides one still running: both block, under this reason.
        out.append({"why": "checks have failed"})
    decision = pr.get("reviewDecision") or ""
    if decision == "CHANGES_REQUESTED":
        out.append({"why": "changes were requested"})
    elif decision != "APPROVED":
        out.append({"why": "not approved yet"})
    if open_threads:
        out.append({"why": f"{open_threads} review thread{'s' if open_threads != 1 else ''} open"})
    return out


def failed_step_lines(log_text: str, job: str | None, step: str | None) -> list[dict]:
    """The failed step's lines from `gh run view --log-failed` (job, step, time and text, tab-separated), numbered,
    each marked when it reads like an error. Lines of other steps are dropped when the step can be told apart."""
    rows = []
    for line in log_text.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            rows.append((parts[0], parts[1], _LOG_TIME_RE.sub("", _LOG_NOISE_RE.sub("", parts[2]))))
        else:
            rows.append((None, None, _LOG_NOISE_RE.sub("", line)))
    picked = [r for r in rows if r[0] == job and r[1] == step] if job and step else []
    texts = [r[2] for r in (picked or rows)][-MAX_STEP_LINES:]
    return [{"n": i + 1, "text": t, "error": bool(_ERROR_LINE_RE.search(t))} for i, t in enumerate(texts)]


def _same_lines(text) -> str:
    """GitHub keeps the line endings a page wrote, so a body read two ways can differ by them alone."""
    return (text or "").replace("\r\n", "\n")


def _version(title, body) -> str:
    """What an edit is guarded by: the text of an issue as it was read, short enough to copy."""
    return hashlib.sha256(f"{_same_lines(title)}\0{_same_lines(body)}".encode()).hexdigest()[:16]


def _text(value, what, top=MAX_TEXT) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BadRequest(f"{what} can't be blank. This tool replaces text and never deletes it")
    if "\0" in value or len(value) > top:
        raise BadRequest(f"{what} is over {top} characters or holds a NUL")
    return value


def _title(value) -> str:
    value = _text(value, "a title", MAX_TITLE)
    if re.search(r"[\x00-\x1f\x7f]", value):
        raise BadRequest("a title is one line")
    return value.strip()


def _expected(value) -> str:
    if not isinstance(value, str) or not _VERSION_RE.fullmatch(value):
        raise BadRequest("expected is the `version` that get_issue gave you for this issue: 16 hex characters. Read it again")
    return value


def _boxes(body: str) -> list[tuple[int, re.Match]]:
    """The checkboxes of a Markdown body, as (line, match), without those in a fenced code block.

    A fence closes as CommonMark has it: the same character, a run at least as long as the opener's, and nothing after it.
    A fence indented four or more spaces, as in a list item, isn't seen, so a box in one is counted."""
    found, fence = [], None
    for i, line in enumerate(body.split("\n")):
        line = line.rstrip("\r")
        mark = _FENCE_RE.match(line)
        if fence is not None:
            if mark and mark["run"][0] == fence[0] and len(mark["run"]) >= len(fence) and not mark["rest"].strip():
                fence = None
            continue
        if mark and not (mark["run"][0] == "`" and "`" in mark["rest"]):  # a backtick fence's info string has no backtick
            fence = mark["run"]
            continue
        box = _BOX_RE.match(line)
        if box:
            found.append((i, box))
    return found


def _ticked(body: str, item: str, checked: bool) -> tuple[str | None, str, str]:
    """The body with the one box named by `item` set, that box's line as it was, and as it is now.
    None for the body if the box is set already."""
    wanted = item.strip()
    boxes = _boxes(body)
    hits = [(i, b) for i, b in boxes if b.group("text") == wanted]
    if not hits:
        shown = "; ".join(b.group("text")[:80] for _, b in boxes[:15]) or "there are none"
        raise BadRequest(f"no checkbox has exactly that text. The boxes in it: {shown}")
    if len(hits) > 1:
        raise BadRequest(f"{len(hits)} checkboxes have that text (lines {', '.join(str(i + 1) for i, _ in hits)}). "
                         "This tool won't guess which: change the text on one of them first, with edit_issue")
    line_no, box = hits[0]
    lines = body.split("\n")
    was = lines[line_no]
    if (box.group("mark") in "xX") == checked:
        return None, was, was
    at = box.start("mark")
    lines[line_no] = was[:at] + ("x" if checked else " ") + was[at + 1:]
    return "\n".join(lines), was, lines[line_no]


class GitHub:
    def __init__(self, hubd: Hubd, config_path: Path, clock=time.monotonic, store=None):
        self.hubd = hubd
        # The work store and its sync. Without them, or before the first sync, everything asks gh.
        self.store = store
        self.sync = None
        self._dirty = False
        self.config = tomllib.loads(Path(config_path).read_text())
        self._clock = clock
        self._overview = None
        self._overview_at = -OVERVIEW_TTL
        self._overview_lock = asyncio.Lock()
        self._strips = None
        self._strips_at = -OVERVIEW_TTL
        self._strips_lock = asyncio.Lock()
        # Text of issues as the tools gave it out, by version, so a refused edit can say what changed. Lost on a restart.
        self._known: dict[tuple, tuple[str, str]] = {}
        # The comments this hub posted, if there's no store to keep them in.
        self._posted: dict[str, dict] = {}

    # --- the whole organization ------------------------------------------------
    async def overview(self, fresh: bool = False) -> dict:
        async with self._overview_lock:
            if self._overview is None and self.store:
                self._overview = self.store.answer("overview", "")
            # With a sync running it refreshes this every tick, so a view never has to.
            expired = not self._serving() and self._clock() - self._overview_at > OVERVIEW_TTL
            if fresh or self._overview is None or self._dirty or expired:
                data = await self.hubd.graphql("org_overview")
                self._overview = self._arrange(data["organization"]["repositories"]["nodes"])
                self._overview_at = self._clock()
                self._dirty = False
                if self.store:
                    self.store.keep("overview", "", self._overview)
            return self._overview

    async def overview_page(self, fresh: bool = False) -> dict:
        """The overview with what Overview sorts by (007 FR-004, FR-007): each repository's failing workflows, open pull
        requests, last commit and last activity, and how many open pull requests fail. From the work store while it
        serves, so the page asks GitHub nothing (001 SC-002); before that, the default branch's checks stand in."""
        view = await self.overview(fresh=fresh)
        serving = self._serving()
        branches = {r["name"]: r.get("branch") for g in view["groups"] for r in g["repos"]}
        activity = self.store.latest_activity() if serving else {}
        failing = self.store.failing_workflows(branches) if serving else None
        failing_prs = self.store.open_pr_checks() if serving else None

        def row(r):
            last = max([t for t in (r.get("pushed"), r.get("head_date"), activity.get(r["name"])) if t] or [None], key=lambda t: t or "")
            head_fails = int(r.get("ci") in ("failure", "error"))
            # The store holds a window of runs: a red head on the default branch counts as at least one, whatever the window saw.
            runs = max(failing[r["name"]], head_fails) if failing is not None else head_fails
            return {**r, "last_commit": {"title": r.get("head_title"), "date": r.get("head_date"), "oid": r.get("head")} if r.get("head") else None,
                    "last_activity": last, "failing_prs": (failing_prs or {}).get(r["name"], 0) if failing_prs is not None else None,
                    "attention": {"failing_runs": runs, "open_prs": r["prs"], "last_activity": last}}
        groups = [{**g, "repos": sorted((row(r) for r in g["repos"]), key=attention_key)} for g in view["groups"]]
        totals = {**view["totals"], "failing_prs": sum(failing_prs.values()) if failing_prs is not None else None}
        return {**view, "groups": groups, "totals": totals, "from_store": serving}

    def _serving(self) -> bool:
        return bool(self.store and self.sync and self.sync.ready())

    async def _wrote(self, repo=None, number=None) -> None:
        """After a write: what views read must show it now, not at the next tick."""
        self._overview_at = -OVERVIEW_TTL
        self._dirty = True
        if not self.store:
            return
        self.store.forget("roadmap")
        if number is not None:
            try:
                data = await self.hubd.graphql("org_item", repo=repo, number=int(_num(number)))
                node = data["repository"]["issueOrPullRequest"]
                if node:
                    self.store.upsert(node)
            except HubdError as e:
                log.warning("couldn't refresh %s#%s: %s", repo, number, e)
        if self.sync:
            self.sync.wake()

    # --- the queue view: from the work store, and it asks GitHub nothing ----------------------------
    def merge_queue(self, decisions: list[dict]) -> dict:
        if not self._serving():
            return {"ready": False, "says": "The work store hasn't synced yet, so there's no queue to show. Nothing is lost: pull requests are on the Work page."}
        blockers = [i for i in self.store.with_bodies("issue", "OPEN") if any(x["name"] == mergequeue.BLOCKER_LABEL for x in i["labels"])]
        return {"ready": True, "synced_at": self.sync.status()["synced_at"],
                **mergequeue.arrange(self.store.with_bodies("pr", "OPEN"), self.store.with_bodies("pr", "MERGED"), blockers, decisions)}

    def _kept(self, key: str, stamp: str):
        return self.store.answer(key, stamp) if self._serving() else None

    def _keep(self, key: str, stamp: str, value) -> None:
        if self.store:
            self.store.keep(key, stamp, value)

    # --- devices ----------------------------------------------------------------
    async def device_status(self, device=None) -> dict:
        """Sentences with an age. The hub never asks the device, and hubd has what it last reported."""
        reply = await self.hubd.call(op="device.status", agent_token=CALLER.get(), device=device)
        return {"says": reply["says"]}

    # --- decisions: the tools can ask about them and ask for them, and never make one -------------
    async def decision_check(self, kind, action=None, target=None) -> dict:
        reply = await self.hubd.call(op="decision.check", agent_token=CALLER.get(), kind=kind, actions=action, target=target)
        return {"answer": reply["answer"], "words": reply["words"]}

    async def decision_request(self, kind, scope, why, ends=None) -> dict:
        reply = await self.hubd.call(op="decision.request", agent_token=CALLER.get(), kind=kind, scope=scope, why=why, ends=ends)
        return {"id": reply["id"], "words": reply["words"]}

    async def decision_end(self, decision_id, why=None) -> dict:
        reply = await self.hubd.call(op="decision.end_go", agent_token=CALLER.get(), id=decision_id, why=why)
        return {"words": reply["words"]}

    # --- the work store's own answers -------------------------------------------
    def work_status(self) -> dict:
        return self.sync.status() if self.sync else {"enabled": False}

    async def work_sync_now(self) -> dict:
        if not self.sync:
            raise BadRequest("the work store isn't set up")
        return await self.sync.sync_now()

    async def _public_repos(self) -> set[str]:
        overview = await self.overview()
        return {r["name"] for g in overview["groups"] for r in g["repos"] if not r["private"]}

    async def _private_repos(self, fresh: bool = False) -> set[str]:
        overview = await self.overview(fresh=fresh)
        return {r["name"] for g in overview["groups"] for r in g["repos"] if r["private"]}

    async def work_search(self, query, kind=None, repo=None, state=None, k=8, for_agent=False) -> dict:
        """Issues, pull requests and their comments, by meaning and by words.

        For an agent, private repositories only when it names one: an agent may be acting on an
        outsider's text, and may be able to post in public."""
        if not self._serving():
            raise BadRequest("the work store isn't ready yet")
        if not query or not str(query).strip():
            raise BadRequest("a search needs a query")
        if kind not in (None, "issue", "pr"):
            raise BadRequest(f"bad kind: {kind}")
        if state not in (None, "open", "closed", "merged", "all"):
            raise BadRequest(f"bad state: {state}")
        if repo:
            _full(repo)
        whole_project = for_agent and ALL_REPOS.get()
        only = await self._public_repos() if for_agent and not repo and not whole_project else None
        found = await self.sync.search(str(query), kind=kind, repo=repo, state=state, k=max(1, min(int(k), 50)), only_repos=only)
        if whole_project:
            await self._say_private(found["results"])
        return found

    async def _say_private(self, rows: list[dict]) -> list[dict]:
        """A session that reads the whole project can't tell private rows apart by their names. A row is private when
        anything it names is: its repository, or one it covers (`repo#N`)."""
        public = await self._public_repos()
        for row in rows:
            named = [row.get("repo"), *(str(c).split("#", 1)[0] for c in row.get("covers") or ())]
            row["private"] = any(repo not in public for repo in named)
        return rows

    def _arrange(self, nodes: list[dict]) -> dict:
        repos = {n["name"]: self._repo_row(n) for n in nodes if not n["isArchived"]}
        groups, placed = [], set()
        for g in self.config["group"]:
            rows = [repos[name] for name in g["repos"] if name in repos]
            placed.update(r["name"] for r in rows)
            groups.append({"key": g["key"], "title": g["title"], "summary": g["summary"],
                           "repos": rows, "totals": _totals(rows)})
        rest = [r for name, r in sorted(repos.items()) if name not in placed]
        if rest:
            groups.append({"key": "unplaced", "title": "Unplaced",
                           "summary": "Not in config/repos.toml yet.", "repos": rest, "totals": _totals(rest)})
        return {"groups": groups, "totals": _totals(list(repos.values())), "fetched": time.time()}

    @staticmethod
    def _repo_row(n: dict) -> dict:
        ref = n.get("defaultBranchRef") or {}
        target = ref.get("target") or {}
        rollup = target.get("statusCheckRollup") or {}
        release = n.get("latestRelease") or {}
        return {
            "name": n["name"], "description": n.get("description") or "", "private": n["isPrivate"], "url": n["url"],
            "pushed": n.get("pushedAt"), "issues": n["issues"]["totalCount"], "prs": n["pullRequests"]["totalCount"],
            "branch": ref.get("name"), "commits": (target.get("history") or {}).get("totalCount"),
            "head": target.get("oid"), "head_title": target.get("messageHeadline"),
            "head_date": target.get("committedDate"),
            "ci": (rollup.get("state") or "NONE").lower(), "release": release.get("tagName"),
        }

    async def rate_limit(self) -> dict:
        """What's left of the host login's GitHub API budget."""
        core = (await self.hubd.gh_json("api", "rate_limit"))["resources"]["core"]
        return {"remaining": core["remaining"], "limit": core["limit"], "reset": core["reset"]}

    async def run_strips(self) -> dict:
        """The last 10 workflow runs on each default branch, oldest first: pass, fail or run."""
        if self._serving():
            view = await self.overview()
            return {r["name"]: [_run_mark(run) for run in reversed(self.store.runs(r["name"], branch=r["branch"], limit=10))]
                    for g in view["groups"] for r in g["repos"] if r.get("branch")}
        async with self._strips_lock:
            if self._strips is None or self._clock() - self._strips_at > OVERVIEW_TTL:
                view = await self.overview()
                repos = [r for g in view["groups"] for r in g["repos"] if r.get("branch")]

                async def one(repo):
                    path = f"repos/{ORG}/{repo['name']}/actions/runs?per_page=10&branch={quote(repo['branch'], safe='')}"
                    try:
                        runs = (await self.hubd.gh_json("api", path))["workflow_runs"]
                    except HubdError:
                        return repo["name"], None  # a repository's runs missing doesn't stop the rest
                    return repo["name"], [_run_mark(r) for r in reversed(runs)]
                self._strips = dict(await asyncio.gather(*(one(r) for r in repos)))
                self._strips_at = self._clock()
            return self._strips

    async def repo_names(self) -> list[str]:
        view = await self.overview()
        return [r["name"] for g in view["groups"] for r in g["repos"]]

    async def _across(self, repo, one) -> list[dict]:
        """`one(repo)` for one repository, or for all of them at once."""
        names = [repo] if repo else await self.repo_names()
        results = await asyncio.gather(*(one(n) for n in names), return_exceptions=True)
        rows = []
        for name, result in zip(names, results):
            if isinstance(result, Exception):
                if repo or not isinstance(result, GhError):
                    raise result
                continue  # e.g. issues disabled on one repository: the others still count
            rows.extend({**row, "repo": name} for row in result or [])
        return rows

    # --- issues ----------------------------------------------------------------
    async def issues(self, repo=None, state="open", label=None, assignee=None, search=None, limit=50) -> list[dict]:
        if state not in ("open", "closed", "all"):
            raise BadRequest(f"bad state: {state}")
        if repo:
            _full(repo)
        # A search with qualifiers (is:, author:…) is GitHub's to answer.
        if self._serving() and not (search and ":" in search):
            wanted = self.store.get("viewer") if assignee == "@me" else assignee
            return self.store.issues(repo, state, label, wanted, search, int(_limit(limit)))
        extra = []
        if label:
            extra += ["--label", label]
        if assignee == "none":
            search = f"{search or ''} no:assignee".strip()
        elif assignee:
            extra += ["--assignee", assignee]
        if search:
            extra += ["--search", search]

        async def one(name):
            return await self.hubd.gh_json("issue", "list", "-R", _full(name), "--state", state, "--limit",
                                           _limit(limit), "--json", _ISSUE_FIELDS, *extra)
        rows = await self._across(repo, one)
        for r in rows:
            r["comments"] = len(r.get("comments") or [])
        rows.sort(key=lambda r: r["updatedAt"], reverse=True)
        return rows

    async def issue(self, repo, number) -> dict:
        if self._serving():
            _full(repo)
            row = self.store.item("issue", repo, int(_num(number)))
            comments = self.store.comments("issue", repo, int(_num(number))) if row else []
            if row and len(comments) >= row["comments"]:
                return {**row, "comments": comments}
            # More comments than a sync carries: ask, once for each version of the issue.
            if row and (kept := self.store.answer(f"issue/{repo}/{_num(number)}", row["updatedAt"])):
                return kept
        row = await self.hubd.gh_json("issue", "view", _num(number), "-R", _full(repo), "--json",
                                      "number,title,state,body,labels,assignees,author,createdAt,updatedAt,url,comments,milestone")
        result = {**row, "repo": repo}
        if self._serving() and (known := self.store.item("issue", repo, int(_num(number)))):
            self.store.keep(f"issue/{repo}/{_num(number)}", known["updatedAt"], result)
        return result

    async def agent_issue(self, repo, number) -> dict:
        """One issue for a session that may edit it: its `version` is what edit_issue and tick_item take as expected.

        The view above is the store's and asks GitHub nothing. This one, while the store serves, also reads the title and body
        from GitHub, since the store can be a sync behind and an edit is checked against the text GitHub has: the text given and its
        version are then one read, and a version of text the person had already changed would be refused at every retry."""
        result = await self.issue(repo, number)
        if "body" not in result or "title" not in result:
            return result
        if self._serving():
            try:
                live = await self._issue_now(repo, number)
            except (BadRequest, HubdError) as e:
                log.warning("no version for %s#%s, as GitHub wasn't asked: %s", repo, number, e)
                return result  # what the store has, with nothing to edit by
            result = {**result, "title": live["title"], "body": live["body"]}
        version = _version(result["title"], result["body"])
        self._know(repo, number, version, result["title"], result["body"])
        return {**result, "version": version}

    async def create_issue(self, repo, title, body="", labels=None, roadmap=False, part_of=None) -> dict:
        if not title or not str(title).strip():
            raise BadRequest("an issue needs a title")
        if part_of:  # 006 FR-035: the body's first line, as filed drafts write it, so Roadmap counts it (007 FR-010)
            if not isinstance(part_of, str) or not _PART_OF_REF_RE.fullmatch(part_of):
                raise BadRequest("Part of is an item, as repo#N")
            ref = part_of if part_of.startswith(f"{ORG}/") else f"{ORG}/{part_of}"
            body = f"Part of {ref}\n\n{body or ''}".rstrip() + "\n"
        argv = ["issue", "create", "-R", _full(repo), "--title", str(title), "--body-file", "-"]
        for label in labels or []:
            argv += ["--label", str(label)]
        url = (await self.hubd.gh(*argv, stdin=str(body or ""))).strip()
        result = {"url": url, "repo": repo, "number": int(url.rsplit("/", 1)[-1])}
        await self._wrote(repo, result["number"])
        if roadmap:
            # The issue exists either way: report a failure here rather than lose it.
            try:
                await self.add_to_project(repo, result["number"])
                result["roadmap"] = True
            except (BadRequest, HubdError) as e:
                result["roadmap_error"] = str(e)
        return result

    async def comment_issue(self, repo, number, body) -> dict:
        url = (await self._comment("issue", repo, number, body)).strip()
        if found := _COMMENT_AT_RE.search(url):
            self._record_comment(repo, found.group(1), _num(number))
        await self._wrote(repo, number)
        return {"url": url}

    async def _comment(self, kind, repo, number, body) -> str:
        if not body or not str(body).strip():
            raise BadRequest("a comment needs text")
        return await self.hubd.gh(kind, "comment", _num(number), "-R", _full(repo), "--body-file", "-", stdin=str(body))

    async def close_issue(self, repo, number, reason="completed", comment=None) -> dict:
        if reason not in ("completed", "not planned"):
            raise BadRequest(f"bad reason: {reason}")
        argv = ["issue", "close", _num(number), "-R", _full(repo), "--reason", reason]
        if comment:
            argv += ["--comment", str(comment)]
        await self.hubd.gh(*argv)
        await self._wrote(repo, number)
        return {"state": "closed"}

    async def reopen_issue(self, repo, number) -> dict:
        await self.hubd.gh("issue", "reopen", _num(number), "-R", _full(repo))
        await self._wrote(repo, number)
        return {"state": "open"}

    async def label_issue(self, repo, number, add=None, remove=None, login=None) -> dict:
        argv = ["issue", "edit", _num(number), "-R", _full(repo)]
        for label in add or []:
            argv += ["--add-label", str(label)]
        for label in remove or []:
            argv += ["--remove-label", str(label)]
        if len(argv) == 5:
            raise BadRequest("no labels given")
        await self.hubd.gh(*argv, login=login)
        await self._wrote(repo, number)
        return {"ok": True}

    async def assign_me(self, repo, number, login=None) -> dict:
        """The person takes the issue: ghpolicy lets `issue edit` add only @me."""
        await self.hubd.gh("issue", "edit", _num(number), "-R", _full(repo), "--add-assignee", "@me", login=login)
        await self._wrote(repo, number)
        row = await self._issue_now(repo, number)
        return {"assignees": [a.get("login") for a in row.get("assignees") or []]}

    # --- editing: the title and body, one checkbox, and the comments this hub posted ----------------
    def _know(self, repo, number, version, title, body) -> None:
        self._known.pop((repo, str(number), version), None)
        self._known[(repo, str(number), version)] = (title, body)
        while len(self._known) > MAX_KNOWN:
            self._known.pop(next(iter(self._known)))

    def _record_comment(self, repo, comment_id, number) -> None:
        """Which session posted it, and which instance of that name: edit_comment is only for what the same one posted."""
        record = {"number": number, "session": SESSION.get() or "", "instance": INSTANCE.get() or ""}
        self._posted[f"{repo}/{comment_id}"] = record
        if self.store:
            self.store.put(f"posted/{repo}/{comment_id}", json.dumps(record))

    def _posted_comment(self, repo, comment_id) -> dict | None:
        if found := self._posted.get(f"{repo}/{comment_id}"):
            return found
        raw = self.store.get(f"posted/{repo}/{comment_id}") if self.store else None
        return json.loads(raw) if raw else None

    async def _issue_now(self, repo, number) -> dict:
        """The issue as GitHub has it this moment, never from the store: an edit is checked against the real text."""
        row = await self.hubd.gh_json("api", f"repos/{_full(repo)}/issues/{_num(number)}")
        if not isinstance(row, dict):
            raise BadRequest(f"GitHub returned nothing for {repo}#{number}")
        return {**row, "title": row.get("title") or "", "body": row.get("body") or ""}

    @staticmethod
    def _ours_to_edit(repo, number, row) -> None:
        if row.get("pull_request"):
            raise BadRequest(f"{repo}#{number} is a pull request. These tools edit issues, and pull requests are not part of them")
        author = (row.get("user") or {}).get("login") or "someone"
        if row.get("author_association") not in OUR_AUTHORS:
            raise BadRequest(f"{repo}#{number} was written by {author}, who isn't a member of the organization "
                             f"({str(row.get('author_association') or 'unknown').lower()}), so it isn't rewritten from here. "
                             "Say what's wrong in a comment, or ask the person to edit it")

    def _guard(self, repo, number, row, expected) -> None:
        self._ours_to_edit(repo, number, row)
        if _version(row["title"], row["body"]) == expected:
            return
        said = f"{repo}#{number} has changed since you read it (last updated {row.get('updated_at')}), so nothing was edited. "
        before = self._known.get((repo, str(number), expected))
        if before is None:
            raise BadRequest(said + "The hub no longer has the text you read, so it can't show what differs. Read it again with get_issue.")
        parts = []
        if _same_lines(before[0]) != _same_lines(row["title"]):
            parts.append(f"title: {before[0]!r} is now {row['title']!r}")
        changes = list(difflib.unified_diff(_same_lines(before[1]).split("\n"), _same_lines(row["body"]).split("\n"),
                                            "what you read", "now", lineterm="", n=1))
        if changes:
            shown = "\n".join(changes)
            parts.append("body:\n" + (shown[:3000] + "\n…" if len(shown) > 3000 else shown))
        raise BadRequest(said + "What changed:\n" + "\n".join(parts) + "\nRead it again with get_issue before editing.")

    async def _edit(self, repo, number, row, title, body) -> dict:
        """One `gh issue edit` for what differs. The text goes on stdin or in an argument gh takes as a value."""
        argv = ["issue", "edit", _num(number), "-R", _full(repo)]
        if title is not None and _same_lines(title) != _same_lines(row["title"]):
            argv.append(f"--title={title}")  # one argument: a title that starts with - isn't a flag
        sent = None
        if body is not None and _same_lines(body) != _same_lines(row["body"]):
            argv += ["--body-file", "-"]
            sent = body
        if len(argv) == 5:
            return {"changed": False}
        try:
            await self.hubd.gh(*argv, stdin=sent)
        except HubdError as e:
            if e.refused and title is not None:  # the text of a title is all hubd's policy reads, so that's what it refused
                raise BadRequest("the title can't go through as written: one shaped like owner/repo (\"docs/search\") or starting "
                                 f"with a link outside the organization is refused ({e}). Reword it") from e
            raise
        await self._wrote(repo, number)
        new_title, new_body = (title if title is not None else row["title"]), (body if body is not None else row["body"])
        version = _version(new_title, new_body)
        self._know(repo, number, version, new_title, new_body)
        return {"changed": True, "version": version}

    async def edit_issue(self, repo, number, expected, title=None, body=None, reason=None) -> dict:
        """Replaces the title or body of an issue of the organization's own, if nobody changed it since `expected`."""
        if title is None and body is None:
            raise BadRequest("give a title or a body to replace")
        expected = _expected(expected)
        title = None if title is None else _title(title)
        body = None if body is None else _text(body, "a body")
        row = await self._issue_now(repo, number)
        self._guard(repo, number, row, expected)
        old = _same_lines(row["body"]).strip()
        if body is not None and len(old) >= SHRUNK_FROM and len(_same_lines(body).strip()) * 2 < len(old) \
                and not (isinstance(reason, str) and reason.strip()):
            raise BadRequest("this takes out more than half of the body. Say why in reason, which the person reads on the card, "
                             "or keep what's still true")
        done = await self._edit(repo, number, row, title, body)
        return {"url": row.get("html_url"), **done, "previous_title": row["title"], "previous_body": row["body"]}

    async def tick_item(self, repo, number, item, expected, checked=True) -> dict:
        """Ticks or unticks the one checkbox with exactly this text, and changes nothing else."""
        if not isinstance(item, str) or not item.strip() or "\n" in item or len(item) > 500:
            raise BadRequest("name the box by its text: one line, as it reads after the [ ]")
        if not isinstance(checked, bool):
            raise BadRequest("checked is true or false")
        expected = _expected(expected)
        row = await self._issue_now(repo, number)
        self._guard(repo, number, row, expected)
        new_body, was, now = _ticked(row["body"], item, checked)
        if new_body is None:
            return {"url": row.get("html_url"), "changed": False, "line": was,
                    "says": f"That box is already {'ticked' if checked else 'unticked'}; nothing was written."}
        done = await self._edit(repo, number, row, None, new_body)
        return {"url": row.get("html_url"), **done, "line": now, "previous_line": was, "previous_body": row["body"]}

    async def edit_comment(self, repo, number, comment_id, body) -> dict:
        """Replaces a comment this hub posted through comment_issue for the same session instance. Any other is refused.

        A tool call from a named session must match both its name and its instance, and one with no instance is refused.
        A call with no session at all is the page (the person's login) or a hub shell's shared token: both are the person's own
        rights, and for them any comment the hub recorded will do."""
        body = _text(body, "a comment")
        n, cid = _num(number), _num(comment_id)
        posted = self._posted_comment(repo, cid)
        session, instance = SESSION.get(), INSTANCE.get()
        theirs = session is not None and (not instance or posted is None or posted.get("session") != session
                                          or posted.get("instance") != instance)
        if not posted or posted["number"] != n or theirs:
            raise BadRequest(f"comment {cid} on {repo}#{n} isn't one you posted with comment_issue. Only those can be edited here")
        row = await self.hubd.gh_json("api", f"repos/{_full(repo)}/issues/comments/{cid}")
        if not isinstance(row, dict) or not str(row.get("issue_url", "")).endswith(f"/{ORG}/{repo}/issues/{n}") \
                or not isinstance(row.get("node_id"), str):
            raise BadRequest(f"comment {cid} isn't on {repo}#{n}")
        if _same_lines(row.get("body")) == _same_lines(body):
            return {"url": row.get("html_url"), "changed": False, "previous_body": row.get("body") or ""}
        data = await self.hubd.graphql("comment_edit", commentId=row["node_id"], body=body)
        await self._wrote(repo, n)
        return {"url": data["updateIssueComment"]["issueComment"]["url"], "changed": True, "previous_body": row.get("body") or ""}

    # --- pull requests ---------------------------------------------------------
    async def prs(self, repo=None, state="open", limit=50) -> list[dict]:
        if state not in ("open", "closed", "merged", "all"):
            raise BadRequest(f"bad state: {state}")
        if repo:
            _full(repo)
        if self._serving():
            return self.store.prs(repo, state, int(_limit(limit)))

        async def one(name):
            return await self.hubd.gh_json("pr", "list", "-R", _full(name), "--state", state, "--limit",
                                           _limit(limit), "--json", _PR_LIST_FIELDS)
        rows = await self._across(repo, one)
        for r in rows:
            r["checks"] = _rollup(r)
        rows.sort(key=lambda r: r["updatedAt"], reverse=True)
        return rows

    def _pr_stamp(self, repo, number) -> str | None:
        """What a pull request's kept answers depend on: its own changes and its repository's runs."""
        row = self.store.item("pr", repo, int(number)) if self._serving() else None
        return f"{row['updatedAt']}/{self.store.get(f'ci/{repo}')}" if row else None

    async def pr_page(self, repo, number) -> dict:
        """The pull request for its page: `pr`, and for an open one the facts its merge button needs. Tools keep `pr`,
        which the work store serves without asking GitHub."""
        row = await self.pr(repo, number)
        if row.get("state") != "OPEN":
            return row
        return {**row, **await self._open_facts(repo, row)}

    async def _open_facts(self, repo, row) -> dict:
        """How far behind its base an open pull request is, and what stops a merge. Asked each time: the base moves,
        and threads aren't in a sync. A read that fails leaves its fact unknown (None), never a guess."""
        behind = threads = None
        if row.get("headRefOid") and row.get("baseRefName"):
            try:
                compared = await self.hubd.gh_json("api", f"repos/{_full(repo)}/compare/{row['baseRefName']}...{row['headRefOid']}")
                behind = int(compared["behind_by"]) if isinstance(compared, dict) and "behind_by" in compared else None
            except (HubdError, GhError, ValueError, TypeError) as e:
                log.warning("no behind count for %s#%s: %s", repo, row.get("number"), e)
        try:
            threads = sum(1 for t in await self.pr_threads(repo, row["number"]) if not t["resolved"])
        except (HubdError, GhError, KeyError, TypeError) as e:
            log.warning("no thread count for %s#%s: %s", repo, row.get("number"), e)
        return {"behind_by": behind, "open_threads": threads, "merge_blockers": merge_blockers(row, threads)}

    async def pr_files(self, repo, number) -> list[dict]:
        """The changed files with their counts. `large`: over LARGE_FILE changed lines. A file with no counted lines (a rename,
        a mode change, an empty or a binary file) is not guessed to be binary: its diff is short, and the page shows it."""
        row = await self.pr(repo, number)
        out = []
        for f in row.get("files") or []:
            added, removed = int(f.get("additions") or 0), int(f.get("deletions") or 0)
            out.append({"path": f.get("path"), "additions": added, "deletions": removed, "large": added + removed > LARGE_FILE})
        return out

    async def pr(self, repo, number) -> dict:
        _full(repo)
        key, stamp = f"pr/{repo}/{_num(number)}", self._pr_stamp(repo, _num(number))
        if stamp and (kept := self.store.answer(key, stamp)):
            if kept.get("state") != "OPEN":
                return kept
            # Merging another pull request changes this one's merge state, and not its stamp.
            return {**kept, **await self.hubd.gh_json("pr", "view", _num(number), "-R", _full(repo), "--json",
                                                      "mergeable,mergeStateStatus,headRefOid")}
        row = await self.hubd.gh_json(
            "pr", "view", _num(number), "-R", _full(repo), "--json",
            _PR_FIELDS + ",headRefOid,body,comments,reviews,files,additions,deletions,mergeStateStatus,mergedAt,mergedBy,assignees")
        checks = [{"name": c.get("name") or c.get("context"), "workflow": c.get("workflowName"),
                   "state": (c.get("conclusion") or c.get("state") or c.get("status") or "").lower(),
                   "url": c.get("detailsUrl") or c.get("targetUrl")}
                  for c in row.get("statusCheckRollup") or []]
        row["checks"] = _rollup(row)
        result = {**row, "check_list": checks, "repo": repo}
        if stamp:
            self.store.keep(key, stamp, result)
        return result

    async def pr_diff(self, repo, number, path=None) -> str:
        """The whole diff, or with `path` the full diff of that one file."""
        diff = await self._pr_diff(repo, number)
        return diff if path is None else _file_or_refuse(diffbudget.one_file, diff, path)

    async def pr_diff_summary(self, repo, number, path=None) -> str:
        """The diff cut to a token budget, saying what was cut; with `path`, that one file, cut the same way."""
        diff = await self._pr_diff(repo, number)
        more = 'get_pr_diff_summary(repo, number, path="...") shows one file, cut to the same size.'
        if path is None:
            return diffbudget.compress(diff, more=more)
        return _file_or_refuse(diffbudget.one_file_short, diff, path, more="This view cannot show the rest of the file.")

    async def _pr_diff(self, repo, number) -> str:
        row = self.store.item("pr", repo, int(_num(number))) if self._serving() else None
        # Against the base too: retargeting a pull request changes its diff, and not its head.
        key, stamp = f"diff/{repo}/{_num(number)}", row and f"{row.get('headRefOid')}/{row.get('baseRefName')}"
        if stamp and (kept := self.store.answer(key, stamp)) is not None:
            return kept
        diff = await self.hubd.gh("pr", "diff", _num(number), "-R", _full(repo))
        if stamp and len(diff) <= MAX_KEPT:
            self.store.keep(key, stamp, diff)
        return diff

    async def review_pr(self, repo, number, event, body) -> dict:
        """A review of a pull request: approve, comment or request-changes."""
        if event not in ("approve", "comment", "request-changes"):
            raise BadRequest(f"bad review: {event}")
        if event != "approve" and (not body or not str(body).strip()):
            raise BadRequest("this review needs text")
        await self.hubd.gh("pr", "review", _num(number), "-R", _full(repo), f"--{event}", "--body-file", "-", stdin=str(body or ""))
        await self._wrote(repo, number)
        return {"ok": True, "review": event}

    async def comment_pr(self, repo, number, body) -> dict:
        url = (await self._comment("pr", repo, number, body)).strip()
        await self._wrote(repo, number)
        return {"url": url}

    async def spawn_session(self, action, repo, number) -> dict:
        """Under the calling session's token: hubd decides whether it may."""
        started = await self.hubd.call(op="started.spawn", agent_token=CALLER.get(), action=action, repo=repo, number=number)
        return {"started": started["name"]}

    async def message_session(self, op, name, text) -> dict:
        """Under the calling session's token: hubd decides whether it may."""
        reply = await self.hubd.call(op=op, agent_token=CALLER.get(), name=name, text=text)
        return {"sent": reply["sent"], "waiting": reply["queued"]}

    async def plan_work(self, action, repo, why, notes="", describe="", paths="") -> dict:
        """Under the calling session's token: a suggestion, which waits for the person."""
        reply = await self.hubd.call(op="work.offer", agent_token=CALLER.get(), action=action, repo=repo, why=why,
                                     notes=notes, describe=describe, paths=paths)
        return {"waiting_for_the_person": reply["id"]}

    async def suggest_session(self, action, repo, number, why, notes="", also_numbers=None, covers=None) -> dict:
        """Under the calling session's token: a full session the person may start. It starts nothing. covers: repo#N, hubd checks them."""
        reply = await self.hubd.call(op="work.suggest", agent_token=CALLER.get(), action=action, repo=repo, number=number, why=why,
                                     notes=notes, also_numbers=also_numbers or [], **({"covers": covers} if covers is not None else {}))
        return {"waiting_for_the_person": reply["id"]}

    async def submit_drafts(self, drafts) -> dict:
        reply = await self.hubd.call(op="work.submit", agent_token=CALLER.get(), drafts=drafts)
        return {"handed_in": reply["handed_in"]}

    async def submit_result(self, kind, payload) -> dict:
        """Under the calling session's token: hubd holds it to its action's result type. Applying is the person's."""
        reply = await self.hubd.call(op="result.submit", agent_token=CALLER.get(), type=kind, payload=payload)
        return {"handed_in": reply["id"], "waits_for": "the person, who applies it"}

    async def new_work_drafts(self) -> list[dict]:
        return (await self.hubd.call(op="work.handed", agent_token=CALLER.get()))["work"]

    async def file_drafts(self, token, work_id, indexes) -> dict:
        """Under your login. One at a time and each on record, so a failure halfway leaves the rest to retry."""
        record = (await self.hubd.call(op="work.claim", token=token, id=work_id, indexes=indexes))["work"]
        drafts = record["drafts"]
        titles = {}
        for i, d in enumerate(drafts):
            titles.setdefault(d["title"], i)

        def depth(i):  # a child after its parent, however deep; a loop just ends here and is held below
            seen = {i}
            while (i := titles.get(drafts[i]["parent"])) is not None and i not in seen:
                seen.add(i)
            return len(seen)

        def held(i):
            """Why this one can't go yet, in words that say what you can do about it."""
            name = drafts[i]["parent"]
            seen = {i}
            while (at := titles.get(name)) is not None:
                if at in seen:
                    return f"Not filed: its parent line, {drafts[i]['parent']}, leads back to itself, so this can't be filed from here. Editing a draft changes its title and body, not its parent: set it aside, or file it by hand."
                seen.add(at)
                name = drafts[at]["parent"]
            parent = drafts[i]["parent"]
            if parent not in titles or parent in urls:
                return None
            if drafts[titles[parent]]["state"] == "handed":
                return f"Not filed: its parent, {parent}, is with the Steward. Send this one to the Steward too."
            return f"Not filed: its parent, {parent}, isn't filed yet. File that first."

        urls = {d["title"]: d["url"] for d in drafts if d["url"]}
        errors, warnings = [], []
        left = sorted(indexes, key=depth)

        async def settle(i, url, note):
            nonlocal record
            record = (await self.hubd.call(op="work.filed", token=token, id=work_id, index=i, url=url, note=note))["work"]
            left.remove(i)

        try:
            for i in list(left):
                draft = drafts[i]
                note = held(i)
                if note:
                    errors.append(note)
                    await settle(i, None, note)
                    continue
                parent = urls.get(draft["parent"], draft["parent"])
                body = f"Part of {parent}\n\n{draft['body']}" if parent else draft["body"]
                roadmap = record["roadmap"] and not draft["parent"]
                url, notes = None, []
                try:
                    try:
                        made = await self.create_issue(draft["target"], draft["title"], body, draft["labels"], roadmap)
                    except (BadRequest, HubdError) as e:
                        if not draft["labels"] or "label" not in str(e).lower():
                            raise
                        made = await self.create_issue(draft["target"], draft["title"], body, None, roadmap)
                        notes.append("Filed without its labels: the repository doesn't have them all.")
                    url = made["url"]
                    urls[draft["title"]] = url
                    if made.get("roadmap_error"):
                        notes.append(f"Filed, but it didn't reach the board: {made['roadmap_error']}")
                        warnings.append(notes[-1])
                except (BadRequest, HubdError) as e:
                    notes.append(f"Not filed: {e}")
                    errors.append(notes[-1])
                await settle(i, url, " ".join(notes) or None)
        except Exception:  # or they'd stay in filing, and look filed
            for i in list(left):
                await settle(i, None, "Filing stopped on an error: check GitHub before filing this again.")
            raise
        return {"work": record, "errors": errors, "warnings": warnings}

    async def changes_since(self, cursor=None, limit=100, login=None) -> dict:
        """What changed in the project after a cursor, as facts from hubd's feed: item, what, old and new state and head commit,
        when, who, a link. A session's own cursor is kept by hubd, so it moves forward when this is read. Under a login it
        moves nobody's. What the caller may read is hubd's to decide, for the rows and the counts alike."""
        if cursor is not None and not isinstance(cursor, (str, int)):
            raise BadRequest("a cursor is the one a previous answer gave")
        reply = await self.hubd.call(op="feed.changes", agent_token=CALLER.get(), token=login,
                                     cursor=None if cursor in (None, "") else str(cursor), limit=int(_limit(limit, 100, 500)))
        reply.pop("ok", None)
        return reply

    async def started_sessions(self) -> list[dict]:
        return (await self.hubd.call(op="started.list", agent_token=CALLER.get()))["sessions"]

    async def running_sessions(self) -> list[dict]:
        return await self._say_private((await self.hubd.call(op="started.running", agent_token=CALLER.get()))["sessions"])

    async def started_summary(self, name) -> dict:
        reply = await self.hubd.call(op="started.summary", agent_token=CALLER.get(), name=name)
        reply.pop("ok", None)
        return reply

    async def repo_files(self, repo, path="", recursive=False) -> dict:
        reply = await self.hubd.call(op="repos.files", agent_token=CALLER.get(), repo=repo, path=path, recursive=recursive)
        reply.pop("ok", None)
        return reply

    async def repo_read(self, repo, path, start_line=1, max_lines=None) -> dict:
        reply = await self.hubd.call(op="repos.read", agent_token=CALLER.get(), repo=repo, path=path, start_line=start_line, max_lines=max_lines)
        reply.pop("ok", None)
        return reply

    async def repo_map(self, tool, **args) -> dict:
        reply = await self.hubd.call(op=f"repos.map_{tool}", agent_token=CALLER.get(), **args)
        reply.pop("ok", None)
        return reply

    async def code_search(self, query, **args) -> dict:
        reply = await self.hubd.call(op="repos.search", agent_token=CALLER.get(), query=query, **args)
        reply.pop("ok", None)
        return reply

    async def request_repository(self, repo) -> dict:
        reply = await self.hubd.call(op="repos.request", agent_token=CALLER.get(), repo=repo)
        reply.pop("ok", None)
        return reply

    async def pr_threads(self, repo, number) -> list[dict]:
        """Asked of GitHub each time: gh has no view of these, and whether one is resolved has to be current."""
        _full(repo)
        data = await self.hubd.graphql("pr_threads", repo=repo, number=int(_num(number)))
        pull = (data.get("repository") or {}).get("pullRequest") or {}
        return [{"id": t["id"], "resolved": t["isResolved"], "outdated": t["isOutdated"], "path": t["path"], "line": t["line"],
                 "side": t.get("diffSide") or "RIGHT",
                 "comments": [{"author": (c.get("author") or {}).get("login"), "body": c["body"], "createdAt": c["createdAt"],
                               "url": c["url"], "hunk": c.get("diffHunk") or ""} for c in t["comments"]["nodes"]]}
                for t in pull["reviewThreads"]["nodes"]] if pull else []

    async def resolve_thread(self, repo, number, thread, resolved=True) -> dict:
        _full(repo)
        await self.hubd.graphql("thread_resolve" if resolved else "thread_unresolve", threadId=_thread(thread))
        await self._wrote(repo, number)
        return {"resolved": resolved}

    async def reply_thread(self, repo, number, thread, body) -> dict:
        _full(repo)
        if not isinstance(body, str) or not body.strip():
            raise BadRequest("a reply needs text")
        data = await self.hubd.graphql("thread_reply", threadId=_thread(thread), body=body)
        await self._wrote(repo, number)
        return {"url": data["addPullRequestReviewThreadReply"]["comment"]["url"]}

    async def merge_pr(self, repo, number, method="squash", delete_branch=False, head=None, login=None) -> dict:
        """hubd holds this to a login, or to a tool token with a decision for this head. Without a head it refuses both."""
        if method not in ("merge", "squash", "rebase"):
            raise BadRequest(f"bad merge method: {method}")
        if not isinstance(head, str) or not _HEAD_RE.fullmatch(head):
            raise BadRequest("name the head commit in full. If you pressed Merge, reload the page: it has to show the head it merges")
        argv = ["pr", "merge", _num(number), "-R", _full(repo), f"--{method}"]
        if delete_branch:
            argv.append("--delete-branch")
        argv += ["--match-head-commit", head]
        await self.hubd.gh(*argv, timeout=120, login=login)
        await self._wrote(repo, number)
        return {"state": "merged"}

    async def close_pr(self, repo, number, comment=None) -> dict:
        argv = ["pr", "close", _num(number), "-R", _full(repo)]
        if comment:
            argv += ["--comment", str(comment)]
        await self.hubd.gh(*argv)
        await self._wrote(repo, number)
        return {"state": "closed"}

    async def reopen_pr(self, repo, number, login=None) -> dict:
        await self.hubd.gh("pr", "reopen", _num(number), "-R", _full(repo), login=login)
        await self._wrote(repo, number)
        return {"state": "open"}

    async def label_pr(self, repo, number, add=None, remove=None, login=None) -> dict:
        """Labels only: ghpolicy refuses `pr edit` with anything else."""
        argv = ["pr", "edit", _num(number), "-R", _full(repo)]
        for label in add or []:
            argv += ["--add-label", str(label)]
        for label in remove or []:
            argv += ["--remove-label", str(label)]
        if len(argv) == 5:
            raise BadRequest("no labels given")
        await self.hubd.gh(*argv, login=login)
        await self._wrote(repo, number)
        row = await self.hubd.gh_json("pr", "view", _num(number), "-R", _full(repo), "--json", "labels") or {}
        return {"labels": [label["name"] for label in row.get("labels") or []]}

    async def labels(self, repo) -> list[dict]:
        """The repository's labels, for Labels… and New issue…"""
        rows = _json_pages(await self.hubd.gh("api", "--paginate", f"repos/{_full(repo)}/labels?per_page=100"))
        return [{"name": r.get("name"), "color": r.get("color"), "description": r.get("description") or ""} for r in rows]

    async def ready_pr(self, repo, number) -> dict:
        await self.hubd.gh("pr", "ready", _num(number), "-R", _full(repo))
        await self._wrote(repo, number)
        return {"ok": True}

    async def update_pr_branch(self, repo, number) -> dict:
        await self.hubd.gh("pr", "update-branch", _num(number), "-R", _full(repo))
        await self._wrote(repo, number)
        return {"ok": True}

    # --- actions ---------------------------------------------------------------
    async def agent_runs(self, repo=None, status=None, workflow=None, branch=None, limit=20) -> list[dict]:
        """Runs for an agent: like work_search, private repositories only when it names one."""
        rows = await self.runs(repo, status, workflow, branch, limit)
        if ALL_REPOS.get():
            return (await self._say_private(rows))[:int(_limit(limit))]
        if repo:
            return rows
        public = await self._public_repos()
        return [r for r in rows if r.get("repo") in public]

    async def _agent_listing(self, repo, limit, listing) -> list[dict]:
        """Like work_search, private repositories only when the agent names one. Asks repository by
        repository, so private rows can't use up the limit."""
        wanted = int(_limit(limit))
        if ALL_REPOS.get():
            rows = await listing(repo)
            rows = sorted(rows, key=lambda r: r["updatedAt"], reverse=True)[:wanted]
            return await self._say_private(rows)
        if repo:
            return await listing(repo)
        results = await asyncio.gather(*(listing(name) for name in sorted(await self._public_repos())))
        rows = [row for result in results for row in result]
        rows.sort(key=lambda r: r["updatedAt"], reverse=True)
        return rows[:wanted]

    async def agent_issues(self, repo=None, state="open", label=None, assignee=None, search=None, limit=50) -> list[dict]:
        return await self._agent_listing(repo, limit, lambda name: self.issues(name, state, label, assignee, search, limit))

    async def agent_prs(self, repo=None, state="open", limit=50) -> list[dict]:
        return await self._agent_listing(repo, limit, lambda name: self.prs(name, state, limit))

    async def runs(self, repo=None, status=None, workflow=None, branch=None, limit=20) -> list[dict]:
        if repo:
            _full(repo)
        # A workflow's file name is gh's to resolve: the store knows runs by the workflow's name.
        by_file = str(workflow or "").endswith((".yml", ".yaml"))
        if self._serving() and not by_file:
            return self.store.runs(repo, status, workflow, branch, int(_limit(limit)))
        extra = []
        if status:
            extra += ["--status", status]
        if workflow:
            extra += ["--workflow", workflow]
        if branch:
            extra += ["--branch", branch]

        async def one(name):
            return await self.hubd.gh_json("run", "list", "-R", _full(name), "--limit", _limit(limit),
                                           "--json", _RUN_FIELDS, *extra)
        rows = await self._across(repo, one)
        rows.sort(key=lambda r: r["createdAt"], reverse=True)
        return rows

    async def run(self, repo, run_id, fresh=False) -> dict:
        key = f"run/{repo}/{_num(run_id)}"
        # A finished run stays as it is, until someone re-runs it.
        known = self.store.item("run", repo, int(run_id)) if self._serving() else None
        if not fresh and known and known["status"] == "completed" and (kept := self.store.answer(key, known["updatedAt"])):
            return kept
        row = await self.hubd.gh_json("run", "view", _num(run_id), "-R", _full(repo), "--json", _RUN_FIELDS + ",jobs")
        result = {**row, "repo": repo}
        if self.store:
            self.store.upsert_run({k: result.get(k) for k in (*_RUN_FIELDS.split(","), "repo")})
            if row["status"] == "completed":
                self.store.keep(key, row["updatedAt"], result)
        return result

    async def run_log(self, repo, run_id, failed_only=True) -> str:
        flag = "--log-failed" if failed_only else "--log"
        known = self.store.item("run", repo, int(run_id)) if self._serving() else None
        finished = known["updatedAt"] if known and known["status"] == "completed" else None
        key = f"log/{repo}/{_num(run_id)}/{flag}"
        if finished and (kept := self.store.answer(key, finished)) is not None:
            return kept
        log_text = await self.hubd.gh("run", "view", _num(run_id), "-R", _full(repo), flag, timeout=120)
        if finished and len(log_text) <= MAX_KEPT:
            self.store.keep(key, finished, log_text)
        return log_text

    async def failed_step(self, repo, run_id) -> dict:
        """The first failed step of the first failed job, its log lines with the errors marked (006 FR-022)."""
        data = await self.hubd.gh_json("api", f"repos/{_full(repo)}/actions/runs/{_num(run_id)}/jobs") or {}
        jobs = data.get("jobs") or []
        job = next((j for j in jobs if j.get("conclusion") == "failure"), None)
        if job is None:
            return {"job": None, "step": None, "lines": [], "log_url": None}
        step = next((s for s in job.get("steps") or [] if s.get("conclusion") == "failure"), None)
        text = await self.run_log(repo, run_id, True)
        return {"job": job.get("name"), "step": step and step.get("name"),
                "lines": failed_step_lines(text, job.get("name"), step and step.get("name")), "log_url": job.get("html_url")}

    async def rerun(self, repo, run_id, failed_only=True) -> dict:
        argv = ["run", "rerun", _num(run_id), "-R", _full(repo)]
        if failed_only:
            argv.append("--failed")
        await self.hubd.gh(*argv)
        await self._run_wrote(repo, run_id)
        return {"ok": True}

    async def cancel_run(self, repo, run_id) -> dict:
        await self.hubd.gh("run", "cancel", _num(run_id), "-R", _full(repo))
        await self._run_wrote(repo, run_id)
        return {"ok": True}

    async def _run_wrote(self, repo, run_id) -> None:
        if not self.store:
            return
        try:
            await self.run(repo, run_id, fresh=True)
        except HubdError as e:
            log.warning("couldn't refresh run %s of %s: %s", run_id, repo, e)
        if self.sync:
            self.sync.wake()

    async def workflows(self, repo) -> list[dict]:
        """The repository's workflows, each saying whether it can be started by hand (`dispatchable`, None when its
        file couldn't be read, with `inputs_error` saying why). Read once an hour."""
        # dispatch/: rows kept before they said whether they can be started by hand are left to expire.
        key, stamp = f"workflows/dispatch/{repo}", str(int(time.time() // WORKFLOWS_TTL))
        if (kept := self._kept(key, stamp)) is not None:
            return kept
        rows = await self.hubd.gh_json("workflow", "list", "-R", _full(repo), "--json", "id,name,path,state") or []
        failed = []  # files GitHub couldn't be asked for just now: tried again next time, not kept for the hour

        async def one(row):
            file = str(row.get("path") or "")
            if row.get("state") != "active" or not file.startswith(".github/workflows/"):
                return {**row, "dispatchable": False}
            name = file.rsplit("/", 1)[-1]
            try:
                read = await self._read_workflow(repo, name, None, failed)
            except BadRequest:  # a file name the form can't ask for: this one workflow is unread, the rest of the list stays
                return {**row, "dispatchable": None, "inputs_error": f"couldn't read {name[:60]}: not a file name this can ask for"}
            return {**row, "dispatchable": read["dispatchable"], **({"inputs_error": read["error"]} if read["error"] else {})}
        rows = list(await asyncio.gather(*(one(r) for r in rows)))
        if not failed:
            self._keep(key, stamp, rows)
        return rows

    async def workflow_inputs(self, repo, file, ref=None) -> dict:
        """006 FR-036: what a workflow file asks for when started by hand, at a branch or tag (the default branch without one)."""
        return await self._read_workflow(repo, file, ref, [])

    async def _read_workflow(self, repo, file, ref, failed: list) -> dict:
        if not isinstance(file, str) or not _WORKFLOW_FILE_RE.fullmatch(file):
            raise BadRequest("name the workflow file, e.g. docs.yml")
        if ref is not None and (not isinstance(ref, str) or not _GIT_REF_RE.fullmatch(ref) or ".." in ref or ref.endswith((".", "/", ".lock"))):
            raise BadRequest(f"not a branch or tag: {ref}")
        path = f"repos/{_full(repo)}/contents/.github/workflows/{file}" + (f"?ref={quote(ref, safe='')}" if ref else "")
        out = {"file": file, "ref": ref, "dispatchable": None, "inputs": [], "error": None}
        try:
            reply = await self.hubd.gh_json("api", path) or {}
            if not isinstance(reply, dict) or reply.get("encoding") != "base64":
                raise workflowfile.Unreadable("GitHub didn't send the file's text")
            text = base64.b64decode(reply.get("content") or "").decode("utf-8")
            out["dispatchable"], out["inputs"] = workflowfile.dispatch_inputs(text)
        except HubdError as e:
            failed.append(file)
            out["error"] = f"couldn't read {file}{f' at {ref}' if ref else ''}: {e}"
        except (workflowfile.Unreadable, binascii.Error, UnicodeDecodeError) as e:
            out["error"] = f"couldn't read {file}{f' at {ref}' if ref else ''}: {e}"
        return out

    async def dispatch(self, repo, workflow, ref="main", inputs=None) -> dict:
        if not workflow or "/" in str(workflow):
            raise BadRequest("name the workflow file, e.g. docs.yml")
        argv = ["workflow", "run", str(workflow), "-R", _full(repo), "--ref", str(ref)]
        for key, value in (inputs or {}).items():
            argv += ["-f", f"{key}={value}"]
        await self.hubd.gh(*argv)
        return {"ok": True}

    # --- the strategic board ---------------------------------------------------
    async def project(self) -> dict:
        """The roadmap project's items in the Roadmap's four columns, each with its progress per repository (007 FR-009,
        FR-010). Search doesn't see boards, so the board has a timer; progress is worked out on each read, from the store."""
        board = await self._board()
        if "columns" not in board:
            return board
        issues = (self.store.with_bodies("issue", "OPEN") + self.store.with_bodies("issue", "CLOSED")) if self.store else []
        index = part_index(issues)  # once per read: each issue's body is searched once, not once per item
        columns = [{**c, "items": [{**i, "progress": progress(i, index) if i.get("kind") == "Issue" else []} for i in c["items"]]} for c in board["columns"]]
        if ALL_REPOS.get():  # a session that reads the whole project can't tell private repositories apart by name
            public = await self._public_repos()
            items = [i for c in columns for i in c["items"]]
            await self._say_private([p for i in items for p in i["progress"]])
            for i in items:  # private when anything the item names is: its repository, a sub-issue's, or a repository with progress
                i["private"] = (bool(i.get("repo")) and i["repo"] not in public) or any(p["private"] for p in i["progress"]) or any(
                    s.get("repo") not in public for s in i.get("subs") or ())
        return {**board, "from_store": bool(self.store), "columns": columns}

    async def _board(self) -> dict:
        stamp = str(int(time.time() // BOARD_TTL))
        if kept := self._kept("roadmap", stamp):
            return kept
        try:
            data = await self.hubd.graphql("org_projects")
        except GhError as e:
            if "read:project" in str(e) or "scope" in str(e).lower():
                return {"needs_scope": True, "command": "gh auth refresh -h github.com -s project"}
            raise
        nodes = data["organization"]["projectsV2"]["nodes"]
        wanted = self.config.get("project")
        match = next((n for n in nodes if n["title"] == wanted and not n["closed"]), None)
        if match is None:
            return {"missing": True, "title": wanted, "projects": nodes}
        data = await self.hubd.graphql("project_items", number=match["number"])
        board = _board(data["organization"]["projectV2"], stage_map(self.config.get("roadmap")))
        self._keep("roadmap", stamp, board)
        return board

    async def add_to_project(self, repo, number) -> dict:
        """Put an issue or pull request of the organization on the roadmap."""
        _full(repo)
        wanted = self.config.get("project")
        projects = (await self.hubd.graphql("org_projects"))["organization"]["projectsV2"]["nodes"]
        project = next((n for n in projects if n["title"] == wanted and not n["closed"]), None)
        if project is None:
            raise BadRequest(f'the organization has no open project called "{wanted}"')
        data = await self.hubd.graphql("content_id", repo=repo, number=int(_num(number)))
        content = data["repository"]["issueOrPullRequest"]
        added = await self.hubd.graphql("project_add_item", projectId=project["id"], contentId=content["id"])
        if self.store:
            self.store.forget("roadmap")
        return {"item": added["addProjectV2ItemById"]["item"]["id"]}

    async def move_item(self, project_id, item_id, field_id, option_id) -> dict:
        await self.hubd.graphql("project_set_option", projectId=project_id, itemId=item_id,
                                fieldId=field_id, optionId=option_id)
        if self.store:
            self.store.forget("roadmap")
        return {"ok": True}


def _run_mark(run: dict) -> str:
    if run.get("status") != "completed":
        return "run"
    return "pass" if run.get("conclusion") in ("success", "skipped", "neutral") else "fail"


def _totals(rows: list[dict]) -> dict:
    ci = [r["ci"] for r in rows]
    return {"repos": len(rows), "issues": sum(r["issues"] for r in rows), "prs": sum(r["prs"] for r in rows),
            "failing": sum(1 for s in ci if s in ("failure", "error"))}


def _rollup_subs(nodes: list[dict]) -> list[dict]:
    """Sub-issues closed and total, per repository."""
    repos: dict[str, dict] = {}
    for node in nodes:
        row = repos.setdefault((node.get("repository") or {}).get("name") or "?", {"done": 0, "total": 0})
        row["total"] += 1
        row["done"] += node.get("state") == "CLOSED"
    return [{"repo": name, **row} for name, row in repos.items()]


# 007 FR-009: the Roadmap's columns, in order, and the Status option names each takes by default (R2).
STAGES = (("planned", "Planned", ("Todo", "Planned", "Backlog")), ("in_progress", "In progress", ("In progress",)),
          ("in_review", "In review", ("In review",)), ("done", "Done", ("Done",)))


def stage_map(config: dict | None) -> dict[str, str]:
    """Status option name (lower case) to column key, from [roadmap] in config/repos.toml, else the defaults."""
    config = config or {}
    out = {}
    for key, _name, names in STAGES:
        for name in config.get(key, names):
            out.setdefault(str(name).strip().lower(), key)
    return out


def _board(project: dict, stages: dict[str, str] | None = None) -> dict:
    """The project's items in the four columns. Each card keeps its own Status option; one the map doesn't name, or
    none, goes to Planned with a note. A column lists the options it takes, so a move can pick one."""
    stages = stages if stages is not None else stage_map(None)
    status = next((f for f in project["fields"]["nodes"] if f and f.get("name") == "Status"), None)
    options = (status or {}).get("options") or []
    columns = {key: {"key": key, "name": name, "options": [], "items": []} for key, name, _ in STAGES}
    by_option, unmapped = {}, []
    for o in options:
        key = stages.get(o["name"].strip().lower())
        if key is None:
            unmapped.append(o["name"])
        columns[key or "planned"]["options"].append({"id": o["id"], "name": o["name"], "mapped": key is not None})
        by_option[o["id"]] = (key or "planned", o["name"], key is not None)
    for node in project["items"]["nodes"]:
        content = node.get("content") or {}
        option = next((v.get("optionId") for v in node["fieldValues"]["nodes"]
                       if v and (v.get("field") or {}).get("name") == "Status"), None)
        item = {"id": node["id"], "kind": content.get("__typename"), "title": content.get("title") or "(no title)",
                "number": content.get("number"), "url": content.get("url"), "state": content.get("state"),
                "repo": (content.get("repository") or {}).get("name"),
                "labels": [x["name"] for x in (content.get("labels") or {}).get("nodes", [])],
                "assignees": [x["login"] for x in (content.get("assignees") or {}).get("nodes", [])],
                "sub_issues": _rollup_subs((content.get("subIssues") or {}).get("nodes", [])),
                "subs": [{"repo": (s.get("repository") or {}).get("name"), "number": s.get("number"), "closed": s.get("state") == "CLOSED"}
                         for s in (content.get("subIssues") or {}).get("nodes", [])]}
        key, name, mapped = by_option.get(option, ("planned", None, False))
        item["status"] = name
        if not mapped:
            item["note"] = f"Its status “{name}” has no column: shown under Planned." if name else "No status: shown under Planned."
        columns[key]["items"].append(item)
    return {"id": project["id"], "title": project["title"], "url": project["url"],
            "status_field": status["id"] if status else None, "columns": list(columns.values()), "unmapped": unmapped}


def part_index(issues: list[dict]) -> dict:
    """Store issues (open and closed) indexed once for `progress`: each one's state by (repository, number), and the issues
    whose body says "Part of" an item, by that item as a lower-case repo#N (GitHub names are case-blind, as the pattern is)."""
    state: dict[tuple, bool] = {}
    parts: dict[str, list[tuple]] = {}
    for row in issues:
        key = (row["repo"], int(row["number"]))
        state[key] = row.get("state") == "CLOSED"
        if ref := part_of(row.get("body"), row["repo"]):
            parts.setdefault(ref.lower(), []).append(key)
    return {"state": state, "parts": parts}


def progress(item: dict, index: dict) -> list[dict]:
    """007 FR-010: a roadmap item's progress per repository: its sub-issues and the issues whose body says "Part of" it
    (the index of store rows), each issue counted once. The store's state wins over the board's, which can be older."""
    ref = f"{item.get('repo')}#{item.get('number')}".lower()
    closed: dict[tuple, bool] = {(s["repo"], int(s["number"])): s["closed"] for s in item.get("subs") or [] if s.get("repo") and s.get("number")}
    for key in [*closed, *index["parts"].get(ref, ())]:
        if key in index["state"]:
            closed[key] = index["state"][key]
    repos: dict[str, dict] = {}
    for (repo, _number), done in closed.items():
        r = repos.setdefault(repo, {"repo": repo, "done": 0, "total": 0})
        r["total"] += 1
        r["done"] += done
    return sorted(repos.values(), key=lambda r: r["repo"])
