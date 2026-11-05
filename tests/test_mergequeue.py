# SPDX-License-Identifier: GPL-2.0-or-later
"""The queue view: sets, order, what was tested, your approval, GitHub's reviews apart, blockers."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from hub import mergequeue  # noqa: E402
from hub.mergequeue import arrange, declared_set, links  # noqa: E402

HEAD, OTHER = "a" * 40, "b" * 40


def pr(repo="hub", number=1, body="", branch="task", state="OPEN", **more):
    return {"repo": repo, "number": number, "title": f"PR {number}", "body": body, "state": state, "headRefName": branch, "baseRefName": "main",
            "headRefOid": HEAD, "isDraft": False, "author": {"login": "someone"}, "url": "u", "checks": "passing", "mergeable": "MERGEABLE",
            "reviewDecision": None, "labels": [], "createdAt": "2026-11-01T00:00:00Z", "updatedAt": "2026-11-02T00:00:00Z", **more}


def merge_decision(state="current", head=HEAD, number=1, base="main", **more):
    return {"id": "d-1", "kind": "merge", "state": state, "words": "yes", "scope": {"repo": "hub", "number": number, "head": head, "base": base, "session": "any"}, **more}


def only(rows):
    return arrange(rows, [], [], [])["alone"][0]


@pytest.mark.parametrize("body, want", [
    ("Set: gpu-fix, 2 of 3", ("gpu-fix", 2, 3)),
    ("words\n\nSet: gpu-fix, 1 of 1\r\nmore", ("gpu-fix", 1, 1)),
    ("- Set: a/b.c, 1 of 2", ("a/b.c", 1, 2)),
    ("Set: x, 3 of 2", None), ("Set: x, 0 of 2", None), ("Set: x", None), ("Reset: x, 1 of 2", None), ("the Set: x, 1 of 2 line", None), (None, None)])
def test_a_sets_line(body, want):
    assert declared_set(body) == want


def test_what_was_tested_is_what_it_says():
    assert mergequeue.tested_says("Tested: device on e4ffb6ec\r\n") == "It says: device on e4ffb6ec"
    assert mergequeue.tested_says("no such line") == "It doesn't say"
    assert mergequeue.tested_says(None) == "It doesn't say"
    assert mergequeue.tested_says("Tested: " + "x" * 300).endswith("x…")


def test_links():
    body = "Fixes #3, see boot#4, GlassineOS/linux#5 and https://github.com/GlassineOS/docs/issues/6, not a/b#7 or page#/x or &#8; or C#9x."
    assert links(body, "Hub") == {("hub", 3), ("boot", 4), ("linux", 5), ("docs", 6)}


def test_a_set_comes_in_order_across_repositories_with_the_next_marked():
    rows = [pr("linux", 9, "Set: fix, 2 of 3"), pr("boot", 8, "Set: fix, 3 of 3"), pr("hub", 7, "Set: fix, 1 of 3", branch="other-name")]
    out = arrange(rows, [], [], [])
    assert not out["alone"] and [s["name"] for s in out["sets"]] == ["fix"]
    got = out["sets"][0]["rows"]
    assert [(r["repo"], r["order"]["n"]) for r in got] == [("hub", 1), ("linux", 2), ("boot", 3)]
    assert [r["next"] for r in got] == [True, False, False]
    assert out["sets"][0]["problems"] == []


def test_a_merged_member_stays_in_the_order_and_moves_next_on():
    out = arrange([pr("linux", 9, "Set: fix, 2 of 2")], [pr("hub", 7, "Set: fix, 1 of 2", state="MERGED"), pr("hub", 6, "Set: else, 1 of 2", state="MERGED")], [], [])
    got = out["sets"][0]["rows"]
    assert [(r["number"], r["state"], r["next"]) for r in got] == [(7, "MERGED", False), (9, "OPEN", True)]
    assert got[0]["approval"] is None and got[1]["approval"]["state"] == "none"
    assert out["sets"][0]["problems"] == []


def test_a_set_with_only_merged_members_isnt_shown():
    assert arrange([], [pr("hub", 7, "Set: fix, 1 of 1", state="MERGED")], [], []) == {"sets": [], "alone": [], "blockers": []}


def test_what_the_lines_dont_agree_on_is_said_and_nothing_is_called_next():
    missing = arrange([pr("hub", 2, "Set: fix, 2 of 3"), pr("boot", 3, "Set: fix, 3 of 3")], [], [], [])["sets"][0]
    assert "number 1 of 3" in missing["problems"][0] and not any(r["next"] for r in missing["rows"])
    twice = arrange([pr("hub", 2, "Set: fix, 1 of 2"), pr("boot", 3, "Set: fix, 1 of 2")], [], [], [])["sets"][0]
    assert any("More than one" in p for p in twice["problems"]) and not any(r["next"] for r in twice["rows"])
    sizes = arrange([pr("hub", 2, "Set: fix, 1 of 2"), pr("boot", 3, "Set: fix, 2 of 3")], [], [], [])["sets"][0]
    assert any("2 or 3" in p for p in sizes["problems"]) and not any(r["next"] for r in sizes["rows"])


def test_the_same_branch_in_two_repositories_is_a_set_with_no_order():
    out = arrange([pr("hub", 2, branch="fix"), pr("boot", 3, branch="fix"), pr("hub", 4, branch="solo"), pr("hub", 5, branch="two-here"), pr("hub", 6, branch="two-here")], [], [], [])
    assert [s["name"] for s in out["sets"]] == ["fix"]
    assert "No pull request says its place" in out["sets"][0]["problems"][0]
    assert [r["number"] for r in out["alone"]] == [4, 5, 6], "the same branch in one repository isn't a set"


def test_a_branch_joins_the_set_named_for_it():
    out = arrange([pr("hub", 2, "Set: fix, 1 of 2", branch="fix"), pr("boot", 3, branch="fix")], [], [], [])
    assert [(r["repo"], r["order"]) for r in out["sets"][0]["rows"]] == [("hub", {"n": 1, "m": 2}), ("boot", None)]
    assert any("don't say their place" in p for p in out["sets"][0]["problems"])
    assert not any(r["next"] for r in out["sets"][0]["rows"])


def test_your_approval_and_githubs_reviews_stay_apart():
    row = only([pr(reviewDecision="APPROVED")])
    assert row["reviews"] == "Approved by a reviewer"
    assert row["approval"]["state"] == "none" and "haven't approved" in row["approval"]["says"]
    row = arrange([pr(reviewDecision="CHANGES_REQUESTED")], [], [], [merge_decision()])["alone"][0]
    assert row["reviews"] == "Changes requested"
    assert row["approval"]["state"] == "approved" and row["approval"]["id"] == "d-1" and "yes" in row["approval"]["says"]


@pytest.mark.parametrize("decision, says", [
    (merge_decision(head=OTHER), "doesn't count"),
    (merge_decision(base="develop"), "now targets main"),
    (merge_decision("requested", head=OTHER, asked_by="a0"), "a0 asked for head"),
    (merge_decision("ended", why_ended="the head moved"), "ended: the head moved")])
def test_what_doesnt_count_is_said_and_it_can_be_approved_afresh(decision, says):
    approval = arrange([pr()], [], [], [decision])["alone"][0]["approval"]
    assert approval["state"] == "none" and says in " ".join(approval["notes"]) and not approval.get("asked")


def test_a_decision_on_another_pull_request_isnt_this_ones():
    approval = arrange([pr()], [], [], [merge_decision(number=2), {"id": "d-2", "kind": "go", "state": "current", "scope": {"actions": ["reboot"]}}])["alone"][0]["approval"]
    assert approval["state"] == "none" and not approval["notes"]


def test_a_sessions_request_is_its_words_not_yours():
    approval = arrange([pr()], [], [], [merge_decision("requested", asked_by="a0", why="trust me", words=None)])["alone"][0]["approval"]
    assert approval["state"] == "none" and approval["asked"] == "d-1"
    assert "a0" in approval["notes"][0] and "aren't yours" in approval["notes"][0] and "trust me" in approval["notes"][0]


def test_a_merge_running_on_it_is_said():
    assert arrange([pr()], [], [], [merge_decision("using")])["alone"][0]["approval"]["state"] == "using"


def test_blockers_come_from_the_pull_requests_own_links_and_all_are_listed():
    issues = [{"repo": "boot", "number": 4, "title": "Wait for the fix", "body": "Why.\n\nThe person clears it.", "url": "u", "labels": []},
              {"repo": "hub", "number": 9, "title": "Nothing links this", "body": "x" * 400, "url": "u", "labels": []}]
    out = arrange([pr(body="See boot#4"), pr(number=2, body="Not blocked, #4 is here", branch="b")], [], issues, [])
    assert [b["number"] for b in out["alone"][0]["blockers"]] == [4]
    assert out["alone"][1]["blockers"] == [], "#4 here means hub#4, not boot#4"
    assert [(b["number"], b["linked"]) for b in out["blockers"]] == [(4, True), (9, False)]
    assert out["blockers"][0]["why"] == "Why. The person clears it."
    assert out["blockers"][1]["why"].endswith("…") and len(out["blockers"][1]["why"]) == mergequeue.MAX_WHY + 1


def test_every_field_is_in_words():
    row = only([pr(checks=None, mergeable=None, reviewDecision=None, author=None)])
    assert (row["checks"], row["mergeable"], row["reviews"], row["author"]) == ("Not known", "Not known", "No review decision", "unknown")


# --- from the review ---------------------------------------------------------------------------
def test_a_merged_member_from_an_old_set_with_that_name_doesnt_count():
    old = pr("hub", 7, "Set: fix, 1 of 2", state="MERGED", mergedAt="2026-01-01T00:00:00Z", updatedAt="2026-10-30T00:00:00Z")
    the_set = arrange([pr("hub", 9, "Set: fix, 2 of 2")], [old], [], [])["sets"][0]
    assert [(r["number"], r["next"]) for r in the_set["rows"]] == [(9, False)], "nothing says part 1 of this one is in"
    assert any("number 1 of 2" in p for p in the_set["problems"])
    assert any("hub#7" in p and "don't count" in p for p in the_set["problems"])


@pytest.mark.parametrize("merged, joins", [
    ({"mergedAt": "2026-10-20T00:00:00Z"}, True),
    ({"mergedAt": "2026-11-03T00:00:00Z"}, True),
    ({"mergedAt": "2026-10-10T00:00:00Z"}, False),
    ({"mergedAt": None, "updatedAt": "2026-10-20T00:00:00Z"}, True),
    ({"mergedAt": "not a date", "updatedAt": None}, False)])
def test_a_merged_member_counts_around_when_the_set_began(merged, joins):
    rows = arrange([pr("hub", 9, "Set: fix, 2 of 2")], [pr("hub", 7, "Set: fix, 1 of 2", state="MERGED", **merged)], [], [])["sets"][0]["rows"]
    assert (7 in [r["number"] for r in rows]) is joins and rows[-1]["next"] is joins


def test_a_merged_member_says_when():
    rows = arrange([pr("hub", 9, "Set: fix, 2 of 2")], [pr("hub", 7, "Set: fix, 1 of 2", state="MERGED", mergedAt="2026-11-01T10:00:00Z")], [], [])["sets"][0]["rows"]
    assert (rows[0]["merged_on"], rows[1]["merged_on"]) == ("2026-11-01", None)


def test_the_set_began_with_its_oldest_open_member():
    members = [pr("hub", 8, "Set: fix, 3 of 3", createdAt="2026-11-04T00:00:00Z"), pr("hub", 9, "Set: fix, 2 of 3", createdAt="2026-10-20T00:00:00Z")]
    rows = arrange(members, [pr("hub", 7, "Set: fix, 1 of 3", state="MERGED", mergedAt="2026-10-10T00:00:00Z")], [], [])["sets"][0]["rows"]
    assert [r["number"] for r in rows] == [7, 9, 8]


@pytest.mark.parametrize("body, fixes", [
    ("Fixes #4", True), ("fixes: #4", True), ("Closes GlassineOS/hub#4", True), ("resolved https://github.com/GlassineOS/hub/issues/4", True),
    ("See #4", False), ("prefixes #4", False), ("Fixes #5, and #4", False), ("Fixes\n#4", False)])
def test_a_link_with_a_closing_word_isnt_a_block(body, fixes):
    issue = {"repo": "hub", "number": 4, "title": "Wait", "body": "Why", "url": "u", "labels": []}
    out = arrange([pr(body=body)], [], [issue], [])
    row = out["alone"][0]
    assert ([b["number"] for b in row["fixes"]], [b["number"] for b in row["blockers"]]) == (([4], []) if fixes else ([], [4]))
    assert out["blockers"][0]["linked"], "it stays listed, and linked, either way"


def test_saying_it_fixes_wins_over_mentioning_it():
    issue = {"repo": "hub", "number": 4, "title": "Wait", "body": "Why", "url": "u", "labels": []}
    row = arrange([pr(body="See #4\n\nFixes #4")], [], [issue], [])["alone"][0]
    assert row["blockers"] == [] and [b["number"] for b in row["fixes"]] == [4]
