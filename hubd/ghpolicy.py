# SPDX-License-Identifier: GPL-2.0-or-later
"""What the app may ask the host's gh to do.

The policy is an allowlist of what the app actually runs, and fails closed: a command is
refused unless it is recognised and everything it names is inside the organization. It
runs on the host because the container is what it guards against. To add a command, add
the app's caller with it.

Beyond "which repository", three things matter here:

- gh reads local files for some flags (--body-file, --field x=@file), which would let
  the app read the host. Only stdin ("-") is accepted.
- GitHub search crosses repositories: a repo: qualifier in --search adds to the -R given.
- `gh api` takes any path, host or GraphQL document, so here it is read-only, without
  options, on paths matched after rejecting traversal and placeholders. GraphQL runs
  only from the documents in graphql/.
"""
from __future__ import annotations

import re

ORG = "GlassineOS"


class Refused(Exception):
    """The command is outside the policy. The message goes back to the caller."""


_COMMANDS = {
    "issue": {"list", "view", "create", "comment", "close", "reopen", "edit"},
    "pr": {"list", "view", "diff", "comment", "review", "merge", "close", "reopen", "ready", "update-branch", "edit"},
    "run": {"list", "view", "rerun", "cancel"},
    "workflow": {"list", "run"},
}

# Flags that read a file. "-" (stdin) stays allowed where the value is a path.
_FILE_FLAGS = {"--body-file", "-F", "--field", "--notes-file"}
# --recover reads a host file, --editor runs a program, --admin bypasses branch protection.
_FORBIDDEN_FLAGS = {"--web", "-w", "--hostname", "--recover", "--editor", "-e", "--admin",
                    "--delete-last", "--edit-last"}

# Commands that take only the flags listed here, besides -R. `pr edit` changes labels and nothing else: its title,
# body, base and reviewers stay the author's. `pr reopen` takes no comment, so it reads no file.
_ONLY_FLAGS = {
    ("pr", "edit"): {"--add-label", "--remove-label"},
    ("pr", "reopen"): set(),
}

_REPO_NAME = r"[A-Za-z0-9._-]+"
_REPO_RE = re.compile(rf"{ORG}/{_REPO_NAME}", re.I)
_URL_RE = re.compile(r"https?://", re.I)
_GH_URL_RE = re.compile(rf"^https://github\.com/{ORG}/{_REPO_NAME}(?:/[^\s]*)?$", re.I)
_SEARCH_SCOPE_RE = re.compile(r"\b(repo|org|user|owner)\s*:", re.I)

_ETAG_RE = re.compile(r'If-None-Match: (?:W/)?"[0-9a-f]{16,128}"')
_TIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")

# compare/<base>...<head>: the one path where three dots aren't traversal. Neither ref may hold two dots of its own.
_COMPARE_RE = re.compile(rf"repos/{ORG}/{_REPO_NAME}/compare/([A-Za-z0-9_][A-Za-z0-9_./-]*)\.\.\.([A-Za-z0-9_][A-Za-z0-9_./-]*)", re.I)

_API_PATHS = [
    rf"orgs/{ORG}(/.*)?",
    rf"repos/{ORG}/{_REPO_NAME}(/.*)?",
    "rate_limit",
]


def changes_query(scope, since=None) -> str:
    """The search behind org_changes. Built here: the app names a scope and a time, never a query."""
    if scope == "open-prs" and since is None:
        return f"org:{ORG} is:pr is:open archived:false"
    if scope != "changed":
        raise Refused(f"org_changes: bad scope: {scope}")
    if since is None:
        return f"org:{ORG} archived:false sort:updated-asc"
    if not isinstance(since, str) or not _TIME_RE.fullmatch(since):
        raise Refused("org_changes: bad time")
    return f"org:{ORG} updated:>={since} archived:false sort:updated-asc"


def _check_api(args: list[str]) -> None:
    rest = list(args)
    # A conditional read: the headers are wanted to see the ETag, and the only header sent is its answer.
    if rest[:1] == ["--include"]:
        rest = rest[1:]
        if rest[:1] == ["-H"]:
            if len(rest) < 2 or not _ETAG_RE.fullmatch(rest[1]):
                raise Refused("gh api: the only header allowed is If-None-Match with an ETag")
            rest = rest[2:]
    if rest[:2] == ["-X", "GET"]:
        rest = rest[2:]
    if "--paginate" in rest:
        rest.remove("--paginate")
    if len(rest) != 1 or rest[0].startswith("-"):
        raise Refused("gh api: only a path, read-only, is allowed")
    path = rest[0]
    if _URL_RE.match(path):
        raise Refused("gh api: full URLs are not allowed, use a path")
    clean = path.lstrip("/")
    bare = clean.split("?", 1)[0]
    compare = _COMPARE_RE.fullmatch(bare)
    if compare and not any(".." in ref or ref.endswith(".") for ref in compare.groups()):
        clean = bare = bare.replace("...", "/", 1)
    if ".." in clean or "%" in bare or "{" in clean or "}" in clean or "\\" in clean or "//" in bare:
        raise Refused("gh api: traversal, escapes and placeholders are not allowed in the path")
    if not any(re.fullmatch(p, bare, re.I) for p in _API_PATHS):
        raise Refused(f"gh api: {bare} is not allowed")


def _check_flags(group: str, args: list[str]) -> None:
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            for rest in args[i + 1 :]:
                _check_value(rest)
            return
        name, eq, inline = a.partition("=")
        if a.startswith("-") and a != "-":
            # pflag reads -Rother/repo as -R other/repo, which every check here would miss.
            if not a.startswith("--") and len(name) > 2:
                raise Refused(f"gh {group}: write short flags apart from their value: {a}")
            if name in _FORBIDDEN_FLAGS:
                raise Refused(f"gh {group}: flag {name} is not allowed")
            if name in _FILE_FLAGS:
                value = inline if eq else (args[i + 1] if i + 1 < len(args) else "")
                # In `workflow run` these are fields, where @ would read a file. Elsewhere a path.
                if group == "workflow":
                    if "=@" in value:
                        raise Refused("gh workflow run: a field with @file reads host files")
                elif value != "-":
                    raise Refused(f"gh {group}: {name} accepts only stdin (-)")
                i += 1 if eq else 2
                continue
            if eq:
                _check_value(inline)
        else:
            _check_value(a)
        i += 1


def _check_value(a: str) -> None:
    if _URL_RE.match(a) and not _GH_URL_RE.match(a):
        raise Refused(f"URL outside {ORG}: {a}")
    # OWNER/REPO#123 and OWNER/REPO arguments
    m = re.match(rf"^({_REPO_NAME})/({_REPO_NAME})(#\d+)?$", a)
    if m and m.group(1).lower() != ORG.lower():
        raise Refused(f"repository outside {ORG}: {a}")


def _value_of(args: list[str], *names: str) -> str | None:
    found = None
    for i, a in enumerate(args):
        name, eq, inline = a.partition("=")
        if name in names:
            value = inline if eq else (args[i + 1] if i + 1 < len(args) else "")
            if found is not None and value != found:
                raise Refused(f"{names[0]} given twice")
            found = value
    return found


def _check_shape(group: str, command: str, args: list[str]) -> None:
    """The commands whose flags are listed, and the assignee an issue edit may name: only you, added."""
    if group == "issue" and command == "edit":
        for i, a in enumerate(args):
            name, eq, inline = a.partition("=")
            if name == "--remove-assignee":
                raise Refused("gh issue edit: assignees are only added, by the person, as @me")
            if name == "--add-assignee" and (inline if eq else (args[i + 1] if i + 1 < len(args) else "")) != "@me":
                raise Refused("gh issue edit: --add-assignee takes only @me")
    allowed = _ONLY_FLAGS.get((group, command))
    if allowed is None:
        return
    numbers, flags, i = [], 0, 0
    while i < len(args):
        name, eq, _ = args[i].partition("=")
        if name in ("-R", "--repo"):
            i += 1 if eq else 2
        elif name in allowed:
            flags += 1
            i += 1 if eq else 2
        elif args[i].startswith("-"):
            raise Refused(f"gh {group} {command}: {name} is not allowed")
        else:
            numbers.append(args[i])
            i += 1
    if len(numbers) != 1 or not re.fullmatch(r"[1-9][0-9]{0,9}", numbers[0]):
        raise Refused(f"gh {group} {command}: name the pull request by its number")
    if allowed and not flags:
        raise Refused(f"gh {group} {command}: nothing to change")


def is_merge(argv) -> bool:
    return isinstance(argv, list) and argv[:2] == ["pr", "merge"]


def merge_request(argv: list[str]) -> tuple[str, int, str]:
    """The repository, number and head of a `pr merge`, in only the form the app builds. hubd decides by these, so
    anything it can't read for certain is refused: --auto, say, would merge later, with nobody checking then."""
    args = argv[2:]
    number = args.pop(0) if args else ""
    if not re.fullmatch(r"[1-9][0-9]{0,9}", number):
        raise Refused("gh pr merge: name the pull request by its number")
    repo = head = method = None
    while args:
        flag = args.pop(0)
        if flag in ("--squash", "--merge", "--rebase") and method is None:
            method = flag
        elif flag == "--delete-branch":
            pass
        elif flag == "--match-head-commit" and head is None and args:
            head = args.pop(0)
        elif flag == "-R" and repo is None and args:
            repo = args.pop(0)
        else:
            raise Refused(f"gh pr merge: {flag} isn't something a merge here takes")
    if not repo or not _REPO_RE.fullmatch(repo):
        raise Refused(f"gh pr merge: -R {ORG}/<repo> is required")
    if method is None:
        raise Refused("gh pr merge: --squash, --merge or --rebase is required")
    if not head or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise Refused("gh pr merge: --match-head-commit with the head commit in full is required")
    return repo.split("/", 1)[1], int(number), head


def check(argv: list[str]) -> None:
    """Raise Refused unless `gh <argv>` is allowed. Nothing here runs anything."""
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        raise Refused("no command")
    if any("\0" in a for a in argv):
        raise Refused("control characters in the command")
    group = argv[0]
    if group == "api":
        _check_api(argv[1:])
        return
    if group not in _COMMANDS:
        raise Refused(f"gh {group}: not allowed")
    if len(argv) < 2 or argv[1] not in _COMMANDS[group]:
        raise Refused(f"gh {group} {' '.join(argv[1:2])}: not allowed")
    repo = _value_of(argv[2:], "-R", "--repo")
    if not repo or not _REPO_RE.fullmatch(repo):
        raise Refused(f"gh {group}: -R {ORG}/<repo> is required")
    if argv[1] == "list" and any(_SEARCH_SCOPE_RE.search(a) for a in argv[2:]):
        raise Refused(f"gh {group} list: searches stay inside the repository given with -R")
    _check_flags(group, argv[2:])
    _check_shape(group, argv[1], argv[2:])
    if is_merge(argv) and not _value_of(argv[2:], "--match-head-commit"):
        raise Refused("gh pr merge: --match-head-commit is required, so a decision for one head can't merge another")
