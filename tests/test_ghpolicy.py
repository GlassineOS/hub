# SPDX-License-Identifier: GPL-2.0-or-later
import asyncio
import json
import re
from pathlib import Path

import pytest

from hubd.ghpolicy import _COMMANDS, Refused, check
from hubd.ghrun import Gh

R = ["-R", "GlassineOS/boot"]

ALLOWED = [
    # a persona's review, its text on stdin
    ["pr", "review", "1", *R, "--approve", "--body-file", "-"],
    ["pr", "review", "1", *R, "--request-changes", "--body-file", "-"],
    # a conditional read of an allowed path
    ["api", "--include", "repos/GlassineOS/boot/actions/runs?per_page=30"],
    ["api", "--include", "-H", 'If-None-Match: W/"914762e12363bbcc1e5612190e65cceb"', "repos/GlassineOS/boot/actions/runs?per_page=30"],
    ["issue", "list", *R, "--state", "open", "--json", "number,title", "--search", "epic in:title"],
    ["issue", "create", *R, "--title", "t", "--body-file", "-"],
    ["issue", "comment", "12", *R, "--body-file", "-"],
    ["issue", "close", "12", *R, "--reason", "not planned", "--comment", "see the repo: docs"],
    # the Steward's edits: a title as one argument, a body on stdin, and the REST reads that guard them
    ["issue", "edit", "5", *R, "--title=-x a title", "--body-file", "-"],
    ["issue", "edit", "5", *R, "--body-file", "-"],
    ["api", "repos/GlassineOS/hub/issues/5"],
    ["api", "repos/GlassineOS/hub/issues/comments/77"],
    ["pr", "merge", "5", *R, "--squash", "--delete-branch", "--match-head-commit", "abc123"],
    ["pr", "merge", "5", *R, "--squash", "--match-head-commit", "abc123"],
    ["pr", "view", "https://github.com/GlassineOS/boot/pull/5", *R],
    ["pr", "update-branch", "5", "--repo=GlassineOS/boot"],
    ["run", "rerun", "123", *R, "--failed"],
    ["workflow", "run", "docs.yml", "-R", "GlassineOS/docs", "--ref", "main", "-F", "a=b", "--field", "c=d"],
    ["api", "repos/GlassineOS/docs/commits/main"],
    ["api", "repos/GlassineOS/docs/actions/runs?per_page=5"],
    ["api", "-X", "GET", "/orgs/GlassineOS/repos", "--paginate"],
    ["api", "rate_limit"],
]

REFUSED = [
    # conditional reads: only that one header, only an ETag, only allowed paths
    ["api", "--include", "-H", "Authorization: token x", "repos/GlassineOS/boot"],
    ["api", "--include", "-H", 'If-None-Match: "x\nAuthorization: y"', "repos/GlassineOS/boot"],
    ["api", "--include", "-H", 'If-None-Match: W/"914762e12363bbcc1e5612190e65cceb"', "repos/other/boot"],
    ["api", "--include", "-H"],
    ["api", "-H", 'If-None-Match: W/"914762e12363bbcc1e5612190e65cceb"', "repos/GlassineOS/boot"],
    ["api", "--include", "-X", "DELETE", "repos/GlassineOS/boot"],
    # the things the user excluded by name
    ["auth", "token"],
    ["auth", "status"],
    ["repo", "delete", "GlassineOS/boot", "--yes"],
    ["api", "-X", "DELETE", "repos/GlassineOS/boot"],
    ["api", "--method=DELETE", "repos/GlassineOS/boot"],
    # other groups and subcommands: nothing in the app runs these
    ["config", "get", "oauth_token"],
    ["extension", "install", "evil/ext"],
    ["alias", "set", "x", "!sh"],
    ["secret", "list", *R],
    ["ssh-key", "list"],
    ["gist", "create", "/etc/passwd"],
    ["search", "repos", "x"],
    ["repo", "clone", "GlassineOS/boot"],
    ["repo", "list", "GlassineOS"],
    ["project", "item-edit", "--owner", "GlassineOS", "--id", "x", "--project-id", "y", "--field-id", "z", "--text", "t"],
    ["project", "list", "--owner", "GlassineOS"],
    ["label", "create", "x", *R],
    ["pr", "checkout", "5", *R],
    ["pr", "create", *R, "--title", "t"],
    ["run", "download", "1", *R],
    ["run", "watch", "1", *R],
    ["release", "download", "x", *R],
    ["workflow", "disable", "safety.yml", *R],
    ["issue", "transfer", "1", "other/repo", *R],
    # other owners, every way of naming them
    ["issue", "list"],
    ["issue", "list", "-R", "torvalds/linux"],
    ["issue", "list", "-R", "GlassineOSx/boot"],
    ["issue", "list", "--repo=other/boot"],
    ["issue", "view", "https://github.com/other/repo/issues/1", *R],
    ["issue", "view", "http://evil.example/x", *R],
    ["pr", "view", "other/repo#1", *R],
    ["pr", "list", "-R", "GlassineOS/boot", "-R", "other/repo"],
    ["issue", "create", *R, "--title", "t", "--parent=https://github.com/other/r/issues/1"],
    ["issue", "create", *R, "--title", "t", "--parent", "https://github.com/other/r/issues/1"],
    # search qualifiers cross repositories
    ["issue", "list", *R, "--search", "repo:someone/private"],
    ["issue", "list", *R, "--search=REPO:someone/private"],
    ["pr", "list", *R, "-S", "NOT org:someone"],
    ["issue", "list", *R, "--search", "x user:someone"],
    ["issue", "list", *R, "--search", "owner: someone"],
    # reading host files
    ["issue", "create", *R, "--title", "t", "--body-file", "/etc/passwd"],
    ["issue", "comment", "1", *R, "-F", "/root/.ssh/id_ed25519"],
    ["issue", "comment", "1", *R, "--body-file=/etc/passwd"],
    ["workflow", "run", "x.yml", *R, "-F", "a=@/etc/passwd"],
    ["workflow", "run", "x.yml", *R, "--field", "a=@/etc/passwd"],
    ["workflow", "run", "x.yml", *R, "--field=a=@/etc/passwd"],
    ["issue", "create", *R, "--title", "t", "--recover", "/etc/passwd"],
    ["issue", "edit", "1", *R, "--editor"],
    # an edit can't read a file, name a URL outside, skip the repository, or be a delete
    ["issue", "edit", "5", *R, "--body-file", "/etc/passwd"],
    ["issue", "edit", "5", *R, "--body-file=/etc/passwd"],
    ["issue", "edit", "5", *R, "-F", "/etc/hostname"],
    ["issue", "edit", "5", *R, "--title=https://evil.example/x"],
    ["issue", "edit", "5", "--title=t", "--body-file", "-"],
    ["issue", "edit", "5", "-R", "other/repo", "--body-file", "-"],
    ["issue", "delete", "5", *R, "--yes"],
    ["issue", "comment", "1", *R, "--edit-last", "--body-file", "-"],
    # a comment is edited by the GraphQL document, never by gh api
    ["api", "-X", "PATCH", "repos/GlassineOS/hub/issues/comments/77", "-f", "body=x"],
    ["api", "--method", "PATCH", "repos/GlassineOS/hub/issues/comments/77", "--input", "-"],
    ["api", "repos/GlassineOS/hub/issues/comments/77", "-f", "body=x"],
    ["api", "-X", "DELETE", "repos/GlassineOS/hub/issues/comments/77"],
    ["api", "repos/GlassineOS/hub/issues/5", "-f", "body="],
    ["api", "repos/other/hub/issues/comments/77"],
    # short flags glued to their value
    ["issue", "list", *R, "-Rother/repo"],
    ["issue", "comment", "1", *R, "-F/etc/passwd"],
    # leaving gh, or bypassing and rewriting
    ["issue", "view", "1", *R, "--web"],
    ["pr", "list", *R, "--hostname", "evil.example"],
    ["pr", "merge", "1", *R, "--admin"],
    ["pr", "merge", "5", *R, "--squash"],
    ["pr", "merge", "5", *R, "--squash", "--delete-branch"],
    ["pr", "merge", "5", *R, "--match-head-commit="],
    ["issue", "comment", "1", *R, "--delete-last", "--yes"],
    ["pr", "comment", "1", *R, "--edit-last"],
    ["pr", "review", "1", *R, "--approve", "--body-file", "/etc/passwd"],
    ["pr", "review", "1", "--approve", "--body-file", "-"],
    ["pr", "review", "1", "-R", "other/repo", "--approve"],
    # gh api: other paths
    ["api", "user"],
    ["api", "repos/other/repo"],
    ["api", "https://evil.example/x"],
    ["api", "https://api.github.com/repos/other/repo"],
    ["api", "repos/GlassineOS/../other/repo"],
    ["api", "repos/GlassineOS/%2e%2e/other/repo"],
    ["api", "repos/{owner}/{repo}"],
    ["api", "orgs/other"],
    ["api", "graphql", "-f", "query=mutation{x}"],
    ["api", "graphql"],
    # gh api: options, and every write
    ["api", "--hostname", "evil.example", "repos/GlassineOS/boot"],
    ["api", "--verbose", "repos/GlassineOS/boot"],
    ["api", "-H", "Authorization: token x", "repos/GlassineOS/boot"],
    ["api", "repos/GlassineOS/boot", "--jq", "env"],
    ["api", "repos/GlassineOS/boot", "--template", "{{.}}"],
    ["api", "repos/GlassineOS/boot", "repos/other/repo"],
    ["api", "repos/GlassineOS/boot/issues", "-F", "body=@/etc/passwd"],
    ["api", "repos/GlassineOS/boot/issues", "--input", "-"],
    ["api", "repos/GlassineOS/boot", "-f", "visibility=public"],
    ["api", "-X", "PATCH", "repos/GlassineOS/boot", "-f", "visibility=public"],
    ["api", "-X", "PUT", "repos/GlassineOS/boot/pulls/1/merge"],
    ["api", "-X", "POST", "repos/GlassineOS/boot/actions/runs/9/rerun"],
    ["api", "-XDELETE", "repos/GlassineOS/boot"],
    ["api"],
    # nonsense
    [],
    "auth token",
    [1, 2],
    ["nonsense"],
    ["issue"],
]


@pytest.mark.parametrize("argv", ALLOWED, ids=" ".join)
def test_allowed(argv):
    check(argv)


@pytest.mark.parametrize("argv", REFUSED, ids=lambda a: " ".join(map(str, a)) or "empty")
def test_refused(argv):
    with pytest.raises(Refused):
        check(argv)


def test_the_allowlist_is_what_the_app_runs():
    """Nothing allowed without a caller: an unused command is only attack surface."""
    source = (Path(__file__).parents[1] / "app" / "hub" / "github.py").read_text()
    for group, subcommands in _COMMANDS.items():
        for sub in subcommands:
            assert re.search(rf'"{group}", "{sub}"', source) or (
                group in ("issue", "pr") and sub == "comment" and "kind, \"comment\"" in source
            ), f"gh {group} {sub} has no caller in github.py"


def test_changes_query_stays_in_the_org():
    from hubd.ghpolicy import changes_query
    assert changes_query("changed") == "org:GlassineOS archived:false sort:updated-asc"
    assert changes_query("changed", "2026-11-01T10:00:00Z") == "org:GlassineOS updated:>=2026-11-01T10:00:00Z archived:false sort:updated-asc"
    assert changes_query("open-prs") == "org:GlassineOS is:pr is:open archived:false"
    for scope, since in (("changed", "2026-11-01 org:other"), ("changed", "x"), ("evil", None), (None, None),
                         ("open-prs", "2026-11-01T10:00:00Z"), ("changed", 5)):
        with pytest.raises(Refused):
            changes_query(scope, since)


# --- pr_review_add (005 FR-017): by name, its pull request checked, its notes closed --------------------
def _recording_gh(tmp_path):
    """A gh that logs what it's given and says only PR_ours belongs to the organization."""
    log = tmp_path / "calls.jsonl"
    program = tmp_path / "gh"
    program.write_text("#!/usr/bin/env python3\nimport json, sys\n"
                       "data = sys.stdin.read()\n"
                       f"open({str(log)!r}, 'a').write(json.dumps({{'argv': sys.argv[1:], 'stdin': data}}) + '\\n')\n"
                       "body = json.loads(data) if data else {}\n"
                       "owner = 'GlassineOS' if body.get('variables', {}).get('id') == 'PR_ours' else 'someone'\n"
                       "print(json.dumps({'data': {'node': {'repository': {'owner': {'login': owner}}}}}))\n")
    program.chmod(0o755)
    return Gh(str(program), workdir=str(tmp_path)), log


def test_a_review_with_notes_goes_by_its_document_with_the_text_on_stdin(tmp_path):
    gh, log = _recording_gh(tmp_path)
    notes = [{"path": "epd/fifo.c", "line": 12, "side": "RIGHT", "body": "Read once here."}]
    asyncio.run(gh.graphql("pr_review_add", {"pullRequestId": "PR_ours", "body": "--secret-looking text", "event": "COMMENT", "threads": notes}))
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    sent = calls[-1]
    assert sent["argv"] == ["api", "graphql", "--input", "-"]
    body = json.loads(sent["stdin"])
    assert body["query"] == gh.documents["pr_review_add"] and body["query"].lstrip().startswith("mutation")
    assert body["variables"]["threads"] == notes and body["variables"]["body"] == "--secret-looking text"
    assert all("secret" not in " ".join(c["argv"]) for c in calls)


@pytest.mark.parametrize("variables,why", [
    ({"pullRequestId": "PR_theirs", "body": "x", "event": "COMMENT", "threads": []}, "not in the organization"),
    ({"pullRequestId": "PR_ours", "body": "x", "event": "COMMENT", "threads": [{"path": "a", "line": 1, "side": "RIGHT", "body": "x", "extra": 1}]}, "a thread is"),
    ({"pullRequestId": "PR_ours", "body": "x", "event": "COMMENT", "threads": [{"path": "a", "line": "1", "side": "RIGHT", "body": "x"}]}, "a thread is"),
    ({"pullRequestId": "PR_ours", "body": "x", "event": "COMMENT", "threads": [{"path": "a", "line": 1, "side": "UP", "body": "x"}]}, "a thread is"),
    ({"pullRequestId": "PR_ours", "body": "x", "event": "COMMENT", "threads": "notes"}, "at most"),
    ({"pullRequestId": "PR_ours", "body": "x", "event": "COMMENT", "threads": [{"path": "a", "line": 1, "side": "RIGHT", "body": "x"}] * 51}, "at most"),
])
def test_a_review_document_refuses_others_and_odd_notes(tmp_path, variables, why):
    gh, log = _recording_gh(tmp_path)
    with pytest.raises(Refused, match=why):
        asyncio.run(gh.graphql("pr_review_add", variables))
    assert not log.exists() or all(json.loads(line)["argv"] != ["api", "graphql", "--input", "-"] or "addPullRequestReview" not in line
                                   for line in log.read_text().splitlines())


def test_only_the_review_document_takes_a_list_and_a_raw_mutation_stays_refused(tmp_path):
    gh, _log = _recording_gh(tmp_path)
    with pytest.raises(Refused, match="bad GraphQL variable: threads"):
        asyncio.run(gh.graphql("thread_reply", {"threadId": "PR_ours", "body": "x", "threads": []}))
    with pytest.raises(Refused, match="unknown GraphQL document"):
        asyncio.run(gh.graphql("mutation { addPullRequestReview(input: {}) { clientMutationId } }"))
    with pytest.raises(Refused):
        check(["api", "graphql", "-f", "query=mutation{addPullRequestReview(input:{pullRequestId:\"x\"}){clientMutationId}}"])
    assert gh.is_mutation("pr_review_add")
