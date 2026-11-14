# SPDX-License-Identifier: GPL-2.0-or-later
"""The Steward's edits to issues: edit_issue, tick_item and edit_comment (issue #13)."""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

pytest.importorskip("starlette")
from starlette.testclient import TestClient  # noqa: E402

from hub import main, tools  # noqa: E402
from hub.github import BadRequest, GitHub, _boxes, _version  # noqa: E402
from hub.hubd_client import INSTANCE, SESSION, HubdError  # noqa: E402
from hub.workstore import WorkStore  # noqa: E402
from hubd.ghpolicy import Refused, check  # noqa: E402
from hubd.agents import Library  # noqa: E402
from hubd.server import _edit_problem  # noqa: E402
from test_app import CONFIG, FakeDocs, FakeHubd, signed_in, ORIGIN  # noqa: E402

ACTIONS = Path(__file__).resolve().parents[1] / "agents" / "actions"
LIBRARY = Library(ACTIONS.parent)
BODY = "## Plan\n\n- [ ] write the parser\n- [x] write the lexer\n- [ ] ship it\n\nNotes stay as they are.\n"
LEXER = "write the lexer"


class EditHubd(FakeHubd):
    """Answers the REST reads of an issue and a comment, and keeps what the app writes."""

    def __init__(self):
        super().__init__()
        self.issue = {"number": 5, "title": "Parser", "body": BODY, "state": "open", "updated_at": "2026-11-05T10:00:00Z",
                      "html_url": "https://github.com/GlassineOS/hub/issues/5", "user": {"login": "Biont"}, "author_association": "MEMBER"}
        self.comment = {"id": 77, "node_id": "IC_77", "issue_url": "https://api.github.com/repos/GlassineOS/hub/issues/5",
                        "body": "status: old", "html_url": "https://github.com/GlassineOS/hub/issues/5#issuecomment-77"}
        self.edited = []
        self.rest_down = False

    async def gh(self, *argv, stdin=None, timeout=None, login=None):
        try:
            check(list(argv))  # whatever the app builds has to pass hubd's policy
        except Refused as e:
            raise HubdError(str(e), refused=True) from e
        if self.rest_down and argv[0] == "api":
            raise HubdError("GitHub is not answering")
        if list(argv[:2]) == ["api", "repos/GlassineOS/hub/issues/5"]:
            self.commands.append((list(argv), stdin))
            return json.dumps(self.issue)
        if list(argv[:2]) == ["api", "repos/GlassineOS/hub/issues/comments/77"]:
            self.commands.append((list(argv), stdin))
            return json.dumps(self.comment)
        if argv[:2] == ("issue", "comment"):
            self.commands.append((list(argv), stdin))
            return "https://github.com/GlassineOS/hub/issues/5#issuecomment-77\n"
        return await super().gh(*argv, stdin=stdin, timeout=timeout, login=login)

    async def graphql(self, name, **variables):
        if name == "comment_edit":
            self.commands.append(([name], variables))
            self.edited.append(variables)
            return {"updateIssueComment": {"issueComment": {"url": self.comment["html_url"]}}}
        if name == "org_item":
            return {"repository": {"issueOrPullRequest": None}}
        return await super().graphql(name, **variables)

    def writes(self):
        return [c for c in self.commands if c[0][:2] == ["issue", "edit"] or c[0] == ["comment_edit"]]


@pytest.fixture
def hubd():
    return EditHubd()


@pytest.fixture
def github(hubd):
    return GitHub(hubd, CONFIG)


def run(coro):
    return asyncio.run(coro)


def version(hubd):
    return _version(hubd.issue["title"], hubd.issue["body"])


# --- edit_issue -------------------------------------------------------------------------
def test_edit_issue_replaces_the_body_on_stdin_and_returns_the_old_text(github, hubd):
    result = run(github.edit_issue("hub", 5, version(hubd), body="## Plan\n\nA different plan.\n"))
    [(argv, stdin)] = hubd.writes()
    assert argv == ["issue", "edit", "5", "-R", "GlassineOS/hub", "--body-file", "-"] and stdin == "## Plan\n\nA different plan.\n"
    assert result["changed"] is True and result["previous_body"] == BODY and result["previous_title"] == "Parser"
    assert result["version"] == _version("Parser", "## Plan\n\nA different plan.\n")


def test_a_title_goes_as_one_argument_even_if_it_starts_with_a_dash(github, hubd):
    result = run(github.edit_issue("hub", 5, version(hubd), title="--web the parser"))
    [(argv, stdin)] = hubd.writes()
    assert argv[-1] == "--title=--web the parser" and "--body-file" not in argv and stdin is None
    assert result["previous_title"] == "Parser"


@pytest.mark.parametrize("title", ["", "  ", "two\nlines", "x" * 257, 7])
def test_edit_issue_refuses_a_bad_title(github, hubd, title):
    with pytest.raises(BadRequest):
        run(github.edit_issue("hub", 5, version(hubd), title=title))
    assert hubd.writes() == []


def test_a_stale_expected_is_refused_and_says_what_changed(github, hubd):
    hubd.answers["issue view 5"] = json.dumps({**hubd.issue, "comments": []})  # the Steward reads it with get_issue
    read = run(github.agent_issue("hub", 5))
    assert read["version"] == version(hubd)
    # the person ticks a box on the page while the Steward thinks
    hubd.issue["body"] = BODY.replace("- [ ] ship it", "- [x] ship it")
    with pytest.raises(BadRequest) as e:
        run(github.edit_issue("hub", 5, read["version"], body="## Plan\n\nReplaced.\n"))
    said = str(e.value)
    assert "has changed since you read it" in said
    assert "-- [ ] ship it" in said and "+- [x] ship it" in said
    assert hubd.writes() == []


def test_a_stale_expected_the_hub_never_gave_out_is_refused_too(github, hubd):
    with pytest.raises(BadRequest, match="Read it again with get_issue"):
        run(github.edit_issue("hub", 5, "0" * 16, body="x"))
    assert hubd.writes() == []


@pytest.mark.parametrize("expected", [None, "", "abc", "g" * 16, "A" * 16, "0" * 17, 5, ["0" * 16]])
def test_expected_has_to_be_a_version(github, hubd, expected):
    with pytest.raises(BadRequest):
        run(github.edit_issue("hub", 5, expected, body="x"))
    with pytest.raises(BadRequest):
        run(github.tick_item("hub", 5, LEXER, expected))
    assert hubd.writes() == []


def test_a_body_cant_be_blanked(github, hubd):
    for body in ("", "  \n ", None):
        with pytest.raises(BadRequest):
            run(github.edit_issue("hub", 5, version(hubd), body=body))
    assert hubd.writes() == []


def test_a_body_that_loses_most_of_its_text_needs_a_reason(github, hubd):
    hubd.issue["body"] = "long text. " * 40
    with pytest.raises(BadRequest, match="more than half"):
        run(github.edit_issue("hub", 5, version(hubd), body="short"))
    for reason in ("", "   ", None):
        with pytest.raises(BadRequest, match="more than half"):
            run(github.edit_issue("hub", 5, version(hubd), body="short", reason=reason))
    assert hubd.writes() == []
    result = run(github.edit_issue("hub", 5, version(hubd), body="short", reason="the plan was replaced by #9"))
    assert result["changed"] and result["previous_body"] == "long text. " * 40


def test_a_short_body_may_be_rewritten_without_a_reason(github, hubd):
    hubd.issue["body"] = "TODO: describe this"
    assert run(github.edit_issue("hub", 5, version(hubd), body="x"))["changed"]


def test_nothing_to_change_writes_nothing(github, hubd):
    result = run(github.edit_issue("hub", 5, version(hubd), body=BODY.replace("\n", "\r\n")))
    assert result["changed"] is False and hubd.writes() == []
    with pytest.raises(BadRequest, match="title or a body"):
        run(github.edit_issue("hub", 5, version(hubd)))


# --- whose issues -----------------------------------------------------------------------
@pytest.mark.parametrize("association", ["NONE", "CONTRIBUTOR", "FIRST_TIMER", "COLLABORATOR", None])
def test_an_outsiders_issue_is_not_rewritten(github, hubd, association):
    hubd.issue["author_association"] = association
    hubd.issue["user"] = {"login": "stranger"}
    for call in (lambda: github.edit_issue("hub", 5, version(hubd), body="x"),
                 lambda: github.tick_item("hub", 5, LEXER, version(hubd), False)):
        with pytest.raises(BadRequest, match="stranger.*isn't a member"):
            run(call())
    assert hubd.writes() == []


@pytest.mark.parametrize("association", ["MEMBER", "OWNER"])
def test_the_organizations_own_issues_may_be_edited(github, hubd, association):
    hubd.issue["author_association"] = association
    assert run(github.edit_issue("hub", 5, version(hubd), body="## Plan\n\nNew.\n"))["changed"]


def test_a_pull_request_is_not_an_issue_here(github, hubd):
    hubd.issue["pull_request"] = {"url": "x"}
    with pytest.raises(BadRequest, match="pull request"):
        run(github.edit_issue("hub", 5, version(hubd), title="x"))
    assert hubd.writes() == []


# --- tick_item --------------------------------------------------------------------------
def test_tick_item_flips_one_box_and_nothing_else(github, hubd):
    result = run(github.tick_item("hub", 5, "write the parser", version(hubd)))
    [(argv, stdin)] = hubd.writes()
    assert argv == ["issue", "edit", "5", "-R", "GlassineOS/hub", "--body-file", "-"]
    assert stdin == BODY.replace("- [ ] write the parser", "- [x] write the parser")
    assert result["line"] == "- [x] write the parser" and result["previous_line"] == "- [ ] write the parser"
    assert result["previous_body"] == BODY and result["changed"] is True


def test_tick_item_unticks(github, hubd):
    run(github.tick_item("hub", 5, LEXER, version(hubd), checked=False))
    assert hubd.writes()[0][1] == BODY.replace("- [x] write the lexer", "- [ ] write the lexer")


def test_a_box_already_in_that_state_writes_nothing(github, hubd):
    result = run(github.tick_item("hub", 5, LEXER, version(hubd)))
    assert result["changed"] is False and "already ticked" in result["says"] and hubd.writes() == []


def test_a_second_box_with_the_same_text_is_refused(github, hubd):
    hubd.issue["body"] = BODY + "\n### Later\n\n* [x] write the parser\n"
    with pytest.raises(BadRequest, match=r"2 checkboxes have that text \(lines 3, 11\)"):
        run(github.tick_item("hub", 5, "write the parser", version(hubd)))
    assert hubd.writes() == []


def test_a_box_that_isnt_there_is_refused_and_the_boxes_are_listed(github, hubd):
    with pytest.raises(BadRequest, match="no checkbox has exactly that text.*write the parser; write the lexer; ship it"):
        run(github.tick_item("hub", 5, "write the", version(hubd)))
    with pytest.raises(BadRequest):
        run(github.tick_item("hub", 5, "Notes stay as they are.", version(hubd)))
    assert hubd.writes() == []


@pytest.mark.parametrize("item", ["", "  ", "two\nlines", "x" * 501, None, 5])
def test_the_item_is_one_line_of_text(github, hubd, item):
    with pytest.raises(BadRequest):
        run(github.tick_item("hub", 5, item, version(hubd)))


def test_a_box_in_a_code_block_is_not_a_box(github, hubd):
    hubd.issue["body"] = "```md\n- [ ] example\n```\n\n- [ ] example\n~~~\n- [ ] other\n~~~\n"
    run(github.tick_item("hub", 5, "example", version(hubd)))
    assert hubd.writes()[0][1] == "```md\n- [ ] example\n```\n\n- [x] example\n~~~\n- [ ] other\n~~~\n"
    with pytest.raises(BadRequest):
        run(github.tick_item("hub", 5, "other", version(hubd)))


def test_line_endings_the_page_wrote_are_kept(github, hubd):
    hubd.issue["body"] = BODY.replace("\n", "\r\n")
    run(github.tick_item("hub", 5, "ship it", version(hubd)))
    assert hubd.writes()[0][1] == hubd.issue["body"].replace("- [ ] ship it", "- [x] ship it")


def test_tick_item_is_refused_on_a_stale_version(github, hubd):
    stale = version(hubd)
    hubd.issue["body"] += "A line the person added.\n"
    with pytest.raises(BadRequest, match="has changed since you read it"):
        run(github.tick_item("hub", 5, "ship it", stale))
    assert hubd.writes() == []


def test_get_issue_gives_the_version_an_edit_asks_for(github, hubd):
    hubd.answers["issue view 5"] = json.dumps({**hubd.issue, "comments": []})
    assert run(github.agent_issue("hub", 5))["version"] == version(hubd)


class Synced:
    """A work sync that has run: the store serves reads."""
    def ready(self):
        return True

    def wake(self):
        pass


def served(hubd, tmp_path, **row):
    """A GitHub whose store holds the issue as of the last sync, which is behind hubd.issue."""
    store = WorkStore(tmp_path / "work.db")
    store.upsert({"__typename": "Issue", "repository": {"name": "hub"}, "number": 5, "title": "Parser", "body": BODY, "state": "OPEN",
                  "updatedAt": "2026-11-05T09:00:00Z", "url": hubd.issue["html_url"], "labels": {"nodes": []}, "assignees": {"nodes": []},
                  "comments": {"totalCount": 0, "nodes": []}, "author": {"login": "Biont"}, **row})
    github = GitHub(hubd, CONFIG, store=store)
    github.sync = Synced()
    assert github._serving()
    return github


def test_with_the_store_serving_a_person_edit_after_the_last_sync_doesnt_lock_the_steward_out(hubd, tmp_path):
    """The store is a sync behind. The version and the text get_issue gives are GitHub's, so the next edit can use them."""
    github = served(hubd, tmp_path)
    hubd.issue["body"] = BODY + "A line the person added on the page.\n"  # after the last sync
    read = run(github.agent_issue("hub", 5))
    assert read["version"] == version(hubd) and read["body"] == hubd.issue["body"], "the text and its version are from the same read"
    assert run(github.agent_issue("hub", 5))["version"] == read["version"]
    result = run(github.tick_item("hub", 5, "ship it", read["version"]))
    assert result["changed"] and hubd.writes()[0][1] == hubd.issue["body"].replace("- [ ] ship it", "- [x] ship it")
    assert result["previous_body"] == hubd.issue["body"], "what's put back is what the person had, not the store's older text"


def test_the_dashboards_view_of_an_issue_still_asks_github_nothing_and_has_no_version(hubd, tmp_path):
    """Only the read made for editing goes to GitHub: a view is the store's, as the work store's contract says."""
    github = served(hubd, tmp_path)
    hubd.issue["body"] = BODY + "Changed after the last sync.\n"
    seen = run(github.issue("hub", 5))
    assert seen["body"] == BODY and "version" not in seen
    assert hubd.commands == [], "no call to GitHub for a view"


def test_the_get_issue_tool_gives_the_version_of_githubs_text(hubd, tmp_path):
    github = served(hubd, tmp_path)
    hubd.issue["body"] = BODY + "Changed after the last sync.\n"
    result = run(tools.build(github, FakeDocs())._tool_manager.call_tool("get_issue", {"repo": "hub", "number": 5}, None))
    assert result["version"] == version(hubd) and result["body"] == hubd.issue["body"]


def test_a_change_after_the_steward_read_is_still_refused_and_reading_again_fixes_it(hubd, tmp_path):
    github = served(hubd, tmp_path)
    read = run(github.agent_issue("hub", 5))
    assert read["version"] == version(hubd)
    hubd.issue["body"] = BODY.replace("- [ ] ship it", "- [ ] ship it, soon")  # the person, while the Steward thinks
    with pytest.raises(BadRequest, match=r"(?s)has changed since you read it.*\+- \[ \] ship it, soon"):
        run(github.tick_item("hub", 5, "write the parser", read["version"]))
    again = run(github.agent_issue("hub", 5))  # the store still has the old row: nothing in it is what the retry rests on
    assert again["version"] != read["version"] and again["version"] == version(hubd)
    assert run(github.tick_item("hub", 5, "write the parser", again["version"]))["changed"]


def test_with_the_store_serving_and_github_not_answering_there_is_no_version_to_edit_by(hubd, tmp_path):
    github = served(hubd, tmp_path)
    hubd.rest_down = True
    read = run(github.agent_issue("hub", 5))
    assert read["body"] == BODY and "version" not in read
    with pytest.raises(HubdError):
        run(github.tick_item("hub", 5, "ship it", version(hubd)))
    assert hubd.writes() == []


# --- fenced code ------------------------------------------------------------------------
@pytest.mark.parametrize("body,boxes", [
    # a longer fence isn't closed by a shorter run inside it
    ("````\n```\n- [ ] in the example\n```\n````\n- [ ] real\n", ["real"]),
    # a run with an info string doesn't close a fence
    ("```\n```python\n- [ ] inside\n```\n- [ ] real\n", ["real"]),
    # a closer may be longer, and may have trailing spaces; tildes are their own
    ("```\n- [ ] a\n`````  \n- [ ] b\n~~~\n- [ ] c\n```\n- [ ] d\n~~~\n- [ ] e\n", ["b", "e"]),
    # a different character doesn't close it
    ("~~~\n- [ ] a\n```\n- [ ] b\n~~~\n- [ ] c\n", ["c"]),
    # a backtick can't be in a backtick fence's info string, so that line opens nothing
    ("``` `x`\n- [ ] a\n", ["a"]),
    # an unclosed fence runs to the end
    ("- [ ] a\n```\n- [ ] b\n", ["a"]),
])
def test_boxes_in_fenced_code_are_found_as_commonmark_closes_it(body, boxes):
    assert [b["text"] for _, b in _boxes(body)] == boxes


def test_a_box_in_an_example_cant_be_ticked_or_make_a_real_one_a_duplicate(github, hubd):
    hubd.issue["body"] = "````\n```\n- [ ] ship it\n```\n````\n\n- [ ] ship it\n"
    run(github.tick_item("hub", 5, "ship it", version(hubd)))
    assert hubd.writes()[0][1] == "````\n```\n- [ ] ship it\n```\n````\n\n- [x] ship it\n"


# --- a title hubd's policy would refuse -------------------------------------------------
@pytest.mark.parametrize("title", ["docs/search", "https://evil.example/x is the plan", "other/repo#12"])
def test_a_title_the_command_policy_refuses_is_said_to_be_one_and_asked_to_be_reworded(github, hubd, title):
    with pytest.raises(BadRequest, match="can't go through as written.*Reword it"):
        run(github.edit_issue("hub", 5, version(hubd), title=title))
    assert hubd.writes() == []
    assert _edit_problem("edit_issue", {"expected": GOOD, "title": title}), "and hubd says so before the card"


def test_other_titles_go_through(github, hubd):
    for title in ("docs: search", "Parser (see https://github.com/GlassineOS/hub/issues/5)", "a/b/c"):
        assert _edit_problem("edit_issue", {"expected": GOOD, "title": title}) is None, title
    assert run(github.edit_issue("hub", 5, version(hubd), title="docs: search"))["changed"]



# --- edit_comment -----------------------------------------------------------------------
def as_session(session, instance, call):
    """The tool server sets who is calling from the scope hubd gives its token. None, None is the page or the shared token."""
    tokens = SESSION.set(session), INSTANCE.set(instance)
    try:
        return run(call())
    finally:
        INSTANCE.reset(tokens[1])
        SESSION.reset(tokens[0])


def post(github, session="steward", instance="i-1"):
    return as_session(session, instance, lambda: github.comment_issue("hub", 5, "status: old"))


def edit(github, body="status: new", comment=77, number=5, session="steward", instance="i-1"):
    return as_session(session, instance, lambda: github.edit_comment("hub", number, comment, body))


def test_a_comment_the_session_posted_can_be_edited(github, hubd):
    post(github)
    result = edit(github)
    assert hubd.edited == [{"commentId": "IC_77", "body": "status: new"}]
    assert result == {"url": hubd.comment["html_url"], "changed": True, "previous_body": "status: old"}


def test_a_comment_nobody_posted_through_comment_issue_is_refused(github, hubd):
    with pytest.raises(BadRequest, match="isn't one you posted"):
        edit(github)
    assert hubd.edited == []


def test_a_comment_another_session_posted_is_refused(github, hubd):
    post(github, session="issue-triage-1")
    with pytest.raises(BadRequest, match="isn't one you posted"):
        edit(github, session="steward")
    assert hubd.edited == []


def test_a_new_session_under_the_same_name_cant_edit_what_the_old_one_posted(github, hubd):
    """The Steward is always called steward: what tells one from the next is its instance."""
    post(github, session="steward", instance="i-1")
    with pytest.raises(BadRequest, match="isn't one you posted"):
        edit(github, session="steward", instance="i-2")
    assert hubd.edited == []
    assert edit(github, session="steward", instance="i-1")["changed"]


def test_a_new_session_with_a_store_that_remembers_cant_either(hubd, tmp_path):
    post(GitHub(hubd, CONFIG, store=WorkStore(tmp_path / "work.db")), instance="i-1")
    with pytest.raises(BadRequest, match="isn't one you posted"):
        edit(GitHub(hubd, CONFIG, store=WorkStore(tmp_path / "work.db")), instance="i-2")
    assert hubd.edited == []


@pytest.mark.parametrize("instance", [None, ""])
def test_a_named_session_with_no_instance_is_refused(github, hubd, instance):
    """Fail closed: a hubd that doesn't say which instance it is can't be matched to anything."""
    post(github, instance="i-1")
    with pytest.raises(BadRequest, match="isn't one you posted"):
        edit(github, instance=instance)
    post(github, instance=instance)  # recorded with none either, which never matches
    with pytest.raises(BadRequest, match="isn't one you posted"):
        edit(github, instance=instance)
    assert hubd.edited == []


def test_a_comment_recorded_without_an_instance_is_not_a_sessions(github, hubd):
    github._posted["hub/77"] = {"number": "5", "session": "steward"}  # as before instances were recorded
    with pytest.raises(BadRequest, match="isn't one you posted"):
        edit(github)
    assert hubd.edited == []


def test_with_no_session_any_comment_the_hub_recorded_can_be_edited(github, hubd):
    """Pins who is not held to a session: the page, and the shared agent token that a hub shell holds (tools is None, no card).
    Both are the person's own rights. If SESSION's default ever changes, this is what widens or narrows."""
    post(github, session="issue-triage-4", instance="i-9")
    assert edit(github, session=None, instance=None)["changed"] is True
    assert hubd.edited == [{"commentId": "IC_77", "body": "status: new"}]
    # what the hub never recorded stays out of reach for them too
    hubd.comment.update(id=78, node_id="IC_78")
    with pytest.raises(BadRequest, match="isn't one you posted"):
        edit(github, comment=78, session=None, instance=None)


def test_a_comment_posted_on_another_issue_is_refused(github, hubd):
    post(github)
    with pytest.raises(BadRequest, match="isn't one you posted"):
        edit(github, number=6)
    hubd.comment["issue_url"] = "https://api.github.com/repos/GlassineOS/hub/issues/9"
    with pytest.raises(BadRequest, match="isn't on hub#5"):
        edit(github)
    assert hubd.edited == []


def test_the_record_survives_a_restart(hubd, tmp_path):
    post(GitHub(hubd, CONFIG, store=WorkStore(tmp_path / "work.db")))
    again = GitHub(hubd, CONFIG, store=WorkStore(tmp_path / "work.db"))
    assert edit(again)["changed"]
    with pytest.raises(BadRequest):
        edit(GitHub(hubd, CONFIG, store=WorkStore(tmp_path / "other.db")))


@pytest.mark.parametrize("body", ["", "  \n", None])
def test_a_comment_cant_be_blanked(github, hubd, body):
    post(github)
    with pytest.raises(BadRequest):
        edit(github, body=body)
    assert hubd.edited == []


def test_an_unchanged_comment_writes_nothing(github, hubd):
    post(github)
    assert edit(github, body="status: old")["changed"] is False and hubd.edited == []


# --- the web API takes the same capabilities --------------------------------------------
def test_the_web_api_edits_too(hubd, github):
    from hub import web
    client = signed_in(TestClient(web.build(hubd, github, FakeDocs(), secure_cookie=False, allowed_hosts={"testserver"})))
    hubd.answers["issue view 5"] = json.dumps({**hubd.issue, "comments": []})
    assert "version" not in client.get("/api/issues/hub/5").json()
    assert client.get("/api/issues/hub/5?for=edit").json()["version"] == version(hubd)
    reply = client.post("/api/issues/hub/5/tick", json={"item": "ship it", "expected": version(hubd)}, headers=ORIGIN)
    assert reply.status_code == 200 and reply.json()["line"] == "- [x] ship it"
    reply = client.post("/api/issues/hub/5/edit", json={"expected": "0" * 16, "body": "x"}, headers=ORIGIN)
    assert reply.status_code == 400 and "Read it again" in json.dumps(reply.json())
    reply = client.post("/api/issues/hub/5/edit-comment", json={"comment_id": 77, "body": "x"}, headers=ORIGIN)
    assert reply.status_code == 400


# --- who gets the tools -----------------------------------------------------------------
EDITS = ("edit_issue", "tick_item", "edit_comment")


def test_the_steward_asks_first_and_no_other_action_has_these_tools():
    for path in sorted(ACTIONS.glob("*.toml")):
        action = LIBRARY.action(path.stem)
        listed = {t for t in EDITS if t in action["grant"].hub_tools or t in action["grant"].asks_first}
        if path.stem == "project-steward":
            assert listed == set(EDITS) and not set(EDITS) & set(action["grant"].hub_tools), "asks first: never on its allowed list"
        else:
            assert not listed, f"{path.name} lists {listed}"


def test_the_edit_tools_are_hard_to_undo_and_say_so(github):
    listed = {t.name: t for t in run(tools.build(github, FakeDocs()).list_tools())}
    for name in EDITS:
        assert listed[name].annotations.destructive_hint is True and listed[name].annotations.read_only_hint is False, name
    assert listed["get_issue"].annotations.read_only_hint is True


def steward_call(name, arguments, granted, then=(), instance="i-1"):
    """The tool server with the Steward's own scope: a call has to have your yes, or there's no token for it.
    `then`: more (name, arguments) calls to the same server, each with your yes, whose replies come last."""
    action = LIBRARY.action("project-steward")
    plain = EditHubd()

    async def call(**request):
        if request["op"] == "ask.grant_use":
            return {"ok": True} if granted else {"ok": False, "refused": True, "error": "you weren't allowed"}
        if request["op"] == "auth.check_agent":
            if request.get("token") != "steward-token":
                return {"ok": False}
            return {"ok": True, "scope": {"session": "steward", "instance": instance, "tools": [*action["grant"].hub_tools, *action["grant"].asks_first],
                                          "persona": "steward", "asks_first": action["grant"].asks_first}}
        raise AssertionError(request["op"])
    plain.call = call
    headers = {"accept": "application/json, text/event-stream"}
    message = lambda i, n, a: {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": n, "arguments": a}}
    with TestClient(main.agent_app(plain, GitHub(plain, CONFIG), FakeDocs(), 9095), base_url="http://127.0.0.1:9095") as client:
        none = client.post("/mcp", json=message(1, name, arguments), headers=headers)
        reply = client.post("/mcp", json=message(1, name, arguments), headers={**headers, "authorization": "Bearer steward-token"})
        later = [client.post("/mcp", json=message(i + 2, n, a), headers={**headers, "authorization": "Bearer steward-token"})
                 for i, (n, a) in enumerate(then)]
    return (none, reply, plain) if not then else (none, reply, plain, later)


@pytest.mark.parametrize("name,arguments", [
    ("edit_issue", {"repo": "hub", "number": 5, "expected": _version("Parser", BODY), "body": "## Plan\n\nNew.\n"}),
    ("tick_item", {"repo": "hub", "number": 5, "item": "ship it", "expected": _version("Parser", BODY)}),
    ("edit_comment", {"repo": "hub", "number": 5, "comment_id": 77, "body": "x"}),
])
def test_without_a_token_or_your_yes_nothing_is_written(name, arguments):
    none, reply, hubd = steward_call(name, arguments, granted=False)
    assert none.status_code == 401
    assert "you weren't allowed" in reply.json()["error"]["message"]
    assert hubd.writes() == []


def test_with_your_yes_the_steward_ticks_a_box_through_the_tool_server():
    arguments = {"repo": "hub", "number": 5, "item": "ship it", "expected": _version("Parser", BODY)}
    _none, reply, hubd = steward_call("tick_item", arguments, granted=True)
    result = reply.json()["result"]
    assert not result.get("isError"), reply.text
    said = json.loads(result["content"][0]["text"])
    assert said["previous_body"] == BODY and said["line"] == "- [x] ship it"
    assert hubd.writes()[0][1] == BODY.replace("- [ ] ship it", "- [x] ship it")


def test_the_instance_hubd_names_in_the_scope_is_what_edit_comment_is_held_to():
    """End to end through the auth layer: the comment is posted as one instance of the Steward and edited as it, and a new Steward can't."""
    post_it = ("comment_issue", {"repo": "hub", "number": 5, "body": "status: old"})
    edit_it = ("edit_comment", {"repo": "hub", "number": 5, "comment_id": 77, "body": "status: new"})
    _none, _reply, hubd, (edited,) = steward_call(*post_it, granted=True, then=[edit_it], instance="i-1")
    assert json.loads(edited.json()["result"]["content"][0]["text"])["changed"] is True and len(hubd.edited) == 1
    # a new Steward (the name is the same) with the same store would be refused: here its server never recorded the comment
    _none, _reply, hubd, (refused,) = steward_call(*edit_it, granted=True, then=[edit_it], instance="i-2")
    assert refused.json()["result"]["isError"] is True and "isn't one you posted" in refused.text and hubd.edited == []


# --- hubd's side: said before it asks you -----------------------------------------------
GOOD = "0" * 16


@pytest.mark.parametrize("name,arguments", [
    ("edit_issue", {"repo": "hub", "number": 5, "body": "x"}),
    ("edit_issue", {"repo": "hub", "number": 5, "expected": "latest", "body": "x"}),
    ("edit_issue", {"repo": "hub", "number": 5, "expected": GOOD}),
    ("edit_issue", {"repo": "hub", "number": 5, "expected": GOOD, "body": "  "}),
    ("edit_issue", {"repo": "hub", "number": 5, "expected": GOOD, "title": ""}),
    ("tick_item", {"repo": "hub", "number": 5, "item": "x"}),
    ("tick_item", {"repo": "hub", "number": 5, "item": " ", "expected": GOOD}),
    ("tick_item", {"repo": "hub", "number": 5, "item": "x", "expected": GOOD, "checked": "false"}),
    ("tick_item", {"repo": "hub", "number": 5, "item": "x", "expected": GOOD, "checked": 0}),
    ("tick_item", {"repo": "hub", "number": 5, "item": "x", "expected": GOOD, "checked": None}),
    ("edit_issue", {"repo": "hub", "number": 5, "expected": GOOD, "title": "docs/search"}),
    ("edit_comment", {"repo": "hub", "number": 5, "comment_id": 1, "body": ""}),
    ("edit_comment", {"repo": "hub", "number": 5, "comment_id": 1}),
])
def test_an_edit_that_would_be_refused_anyway_doesnt_ask_you(name, arguments):
    assert _edit_problem(name, arguments)


@pytest.mark.parametrize("name,arguments", [
    ("edit_issue", {"repo": "hub", "number": 5, "expected": GOOD, "body": "x"}),
    ("edit_issue", {"repo": "hub", "number": 5, "expected": GOOD, "title": "t"}),
    ("tick_item", {"repo": "hub", "number": 5, "item": "x", "expected": GOOD}),
    ("tick_item", {"repo": "hub", "number": 5, "item": "x", "expected": GOOD, "checked": False}),
    ("edit_comment", {"repo": "hub", "number": 5, "comment_id": 1, "body": "x"}),
])
def test_a_well_formed_edit_asks_you(name, arguments):
    assert _edit_problem(name, arguments) is None



def test_the_mark_ready_tool_marks_a_draft_ready_through_hubds_policy(hubd, tmp_path):
    """The one way a session without a shell (merge-ready) takes a draft out of draft: a draft doesn't merge."""
    github = served(hubd, tmp_path)
    result = run(tools.build(github, FakeDocs())._tool_manager.call_tool("mark_ready", {"repo": "hub", "number": 5}, None))
    assert result == {"ok": True}
    assert [argv for argv, _stdin in hubd.commands if argv[:2] == ["pr", "ready"]] == [["pr", "ready", "5", "-R", "GlassineOS/hub"]]
