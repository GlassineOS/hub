# SPDX-License-Identifier: GPL-2.0-or-later
"""The person's decisions: what a login records, and what a token can only ask. Through Hubd.request where it counts."""
import asyncio
import json

import pytest

from hubd import auth, decisions
from hubd.decisions import DecisionError, Decisions
from hubd.ghrun import Gh
from hubd.server import Hubd
from hubd.shells import Shells

HEAD, OTHER = "a" * 40, "b" * 40


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


class Agents:
    """Three session tokens: a full session, a locked one, and another full one."""
    SCOPES = {"full-token": {"session": "full", "tools": None, "persona": None},
              "other-token": {"session": "other", "tools": None, "persona": None},
              "locked-token": {"session": "locked", "tools": ["get_pr"], "persona": None}}

    def scope(self, token):
        return self.SCOPES.get(token)

    def session_id_of(self, name):
        return {"full": "conversation-1", "other": "conversation-2", "locked": "conversation-3", "steward": "conversation-4"}.get(name)


@pytest.fixture
def fake_pr(tmp_path):
    """A gh whose `pr view` answers with the file it reads, so a test can move a pull request's head."""
    now = tmp_path / "pr.json"
    now.write_text(json.dumps({"state": "OPEN", "headRefOid": HEAD, "baseRefName": "main"}))
    script = tmp_path / "gh"
    script.write_text(f'#!/bin/sh\necho "$@" >> {tmp_path}/gh.log\nif [ "$1 $2" = "pr view" ]; then cat {now}; else echo merged; fi\n')
    script.chmod(0o755)
    return script, now


@pytest.fixture
def world(tmp_path, fake_pr):
    clock = Clock()
    store = Decisions(tmp_path / "decisions", clock=clock)
    sessions = auth.Sessions()
    hubd = Hubd(Gh(str(fake_pr[0]), workdir=str(tmp_path)), Shells(), sessions, "general-token", agents=Agents(), decision_store=store)
    return hubd, store, clock, sessions.create()


def call(hubd, **req):
    return asyncio.run(hubd.request(req))


GO = {"actions": ["reboot", "suspend"]}


def test_a_token_cant_add_or_approve(world):
    hubd, store, _clock, _login = world
    for token in ("full-token", "general-token", "locked-token", "wrong", None):
        for op in ("decision.add", "decision.approve", "decision.deny", "decision.end", "decision.list", "decision.have_device", "decision.done"):
            for field in ("agent_token", "token"):
                reply = call(hubd, op=op, kind="go", words="x", scope=GO, ends={"runs": 1}, **{field: token})
                assert reply["ok"] is False and reply["denied"], (op, field, token)
    assert store.list() == []


def test_a_request_is_no_use_until_a_login_approves_it(world):
    hubd, store, _clock, login = world
    asked = call(hubd, op="decision.request", agent_token="full-token", kind="go", scope=GO, why="testing suspend")
    assert asked["ok"] and "Needs you" in asked["words"] and "Decisions page" not in asked["words"]
    no = call(hubd, op="decision.check", agent_token="full-token", kind="go", actions="reboot")
    assert no["answer"] == "no"
    by_id = call(hubd, op="decision.check", agent_token="full-token", kind="go", actions="reboot", id=asked["id"])
    assert by_id["answer"] == "no" and "waiting" in by_id["words"]
    assert call(hubd, op="decision.approve", agent_token="full-token", id=asked["id"])["denied"]
    assert call(hubd, op="decision.use", agent_token="full-token", kind="go", actions="reboot", id=asked["id"])["answer"] == "no"
    assert store.list()[0]["state"] == "requested"
    made = call(hubd, op="decision.approve", token=login, id=asked["id"], words="go on")["decision"]
    assert made["state"] == "current" and made["words"] == "go on" and made["asked_by"] == "full"
    yes = call(hubd, op="decision.check", agent_token="full-token", kind="go", actions="reboot,suspend")
    assert yes["answer"] == "yes" and yes["id"] == asked["id"] and "Go for reboot, suspend" in yes["words"]


def test_a_card_can_be_narrowed_and_not_widened(world):
    hubd, _store, _clock, login = world
    asked = call(hubd, op="decision.request", agent_token="full-token", kind="go", scope=GO, why="why")["id"]
    assert "adds actions" in call(hubd, op="decision.approve", token=login, id=asked, scope={"actions": ["reboot", "load-test"]})["error"]
    assert call(hubd, op="decision.approve", token=login, id=asked, scope={"actions": ["reboot"]})["ok"]
    assert call(hubd, op="decision.check", agent_token="full-token", kind="go", actions="suspend")["answer"] == "no"
    assert call(hubd, op="decision.check", agent_token="full-token", kind="go", actions="reboot")["answer"] == "yes"
    assert call(hubd, op="decision.approve", token=login, id=asked)["ok"] is False, "once"


def test_a_session_cant_bury_the_page(world):
    hubd, _store, _clock, _login = world
    for _ in range(decisions.MAX_REQUESTS):
        assert call(hubd, op="decision.request", agent_token="full-token", kind="go", scope=GO, why="why")["ok"]
    assert "waiting already" in call(hubd, op="decision.request", agent_token="full-token", kind="go", scope=GO, why="why")["error"]
    assert call(hubd, op="decision.request", agent_token="other-token", kind="go", scope=GO, why="why")["ok"]


def test_an_unanswered_request_goes_stale(world):
    hubd, _store, clock, login = world
    asked = call(hubd, op="decision.request", agent_token="full-token", kind="go", scope=GO, why="why")["id"]
    clock.now += decisions.REQUEST_LIFE + 1
    assert call(hubd, op="decision.approve", token=login, id=asked)["ok"] is False


def go(hubd, login, **over):
    return call(hubd, op="decision.add", token=login, kind="go", words="you may", scope=over.pop("scope", GO), ends=over.pop("ends", {"runs": 1}))["decision"]


def test_a_go_must_have_an_end_and_a_short_one(world):
    hubd, _store, _clock, login = world
    for ends in (None, {}, {"runs": 0}, {"runs": decisions.MAX_RUNS + 1}, {"hours": 0}, {"hours": decisions.MAX_GO_HOURS + 1}, {"runs": True}, {"until": 9e12}):
        reply = call(hubd, op="decision.add", token=login, kind="go", words="w", scope=GO, ends=ends)
        assert reply["ok"] is False, ends
    assert call(hubd, op="decision.add", token=login, kind="go", words=" ", scope=GO, ends={"runs": 1})["ok"] is False, "your words"
    assert call(hubd, op="decision.add", token=login, kind="merged", words="w", scope={})["ok"] is False


def test_an_ended_go_answers_no(world):
    hubd, _store, clock, login = world
    made = go(hubd, login)
    check = lambda **kw: call(hubd, op="decision.check", agent_token="full-token", kind="go", actions="reboot", **kw)
    assert check()["answer"] == "yes"
    assert call(hubd, op="decision.end_go", agent_token="other-token", id=made["id"], why="the bench is over")["ok"], "any session may"
    assert check()["answer"] == "no" and "bench is over" in check(id=made["id"])["words"]
    assert call(hubd, op="decision.end_go", agent_token="full-token", id=made["id"])["ok"] is False

    timed = go(hubd, login, ends={"hours": 1})
    assert check(id=timed["id"])["answer"] == "yes"
    clock.now += 3601
    assert check(id=timed["id"])["answer"] == "no" and "time ran out" in check(id=timed["id"])["words"]
    assert all(r["state"] == "ended" for r in call(hubd, op="decision.list", token=login)["decisions"])


def test_only_a_take_that_got_through_spends_a_run(world):
    hubd, _store, _clock, login = world
    made = go(hubd, login, ends={"runs": 2})
    use = lambda actions="reboot": call(hubd, op="decision.use", agent_token="full-token", kind="go", actions=actions, target="na1", id=made["id"])
    assert call(hubd, op="decision.check", agent_token="full-token", kind="go", actions="reboot", id=made["id"])["answer"] == "yes"
    assert use("load-test")["answer"] == "no", "doesn't cover it, and spends nothing"
    assert use()["answer"] == "yes" and "1 run left" in call(hubd, op="decision.list", token=login)["decisions"][0]["says"]
    assert use()["answer"] == "yes"
    assert use()["answer"] == "no", "two runs"


def test_a_go_for_a_session_answers_only_to_its_token(world):
    hubd, store, _clock, login = world
    named = go(hubd, login, scope={**GO, "session": "full"})
    check = lambda token: call(hubd, op="decision.check", agent_token=token, kind="go", actions="reboot", id=named["id"])
    assert check("full-token")["answer"] == "yes"
    assert check("other-token")["answer"] == "no" and "another session" in check("other-token")["words"]
    assert check("general-token")["answer"] == "no", "a plain shell matches only any"
    assert check("nope").get("refused") and check(None).get("refused")
    anyone = go(hubd, login, scope={**GO, "session": "any"})
    assert call(hubd, op="decision.check", agent_token="general-token", kind="go", actions="reboot", id=anyone["id"])["answer"] == "yes"
    assert call(hubd, op="decision.check", agent_token="other-token", kind="go", actions="reboot")["answer"] == "yes", "any includes a named one"

    store.session_id_of = lambda _name: "another-conversation"
    assert check("full-token")["answer"] == "no", "the name came back, under a new conversation"


def test_a_go_can_be_for_one_device(world):
    hubd, _store, _clock, login = world
    made = go(hubd, login, scope={**GO, "device": "na1"})
    check = lambda target: call(hubd, op="decision.check", agent_token="full-token", kind="go", actions="reboot", target=target, id=made["id"])["answer"]
    assert check("na1") == "yes" and check("na2") == "no" and check(None) == "no"


def test_a_locked_session_has_none_of_it(world):
    hubd, _store, _clock, login = world
    go(hubd, login)
    for op in ("decision.check", "decision.use", "decision.request", "decision.end_go"):
        reply = call(hubd, op=op, agent_token="locked-token", kind="go", actions="reboot", scope=GO, why="w")
        assert reply.get("refused"), op


def test_ive_got_the_device(world):
    hubd, _store, _clock, login = world
    plain = go(hubd, login)
    eye = go(hubd, login, scope={"actions": ["eye-test"]}, ends={"hours": 1})
    held = lambda: call(hubd, op="decision.holding")
    assert held()["holding"] is False, "no token"
    assert call(hubd, op="decision.have_device", agent_token="full-token").get("denied")
    assert call(hubd, op="decision.have_device", token=login)["ended"] == 1
    assert held()["holding"] is True and "Done" in held()["words"]
    assert call(hubd, op="decision.check", agent_token="full-token", kind="go", actions="reboot", id=plain["id"])["answer"] == "no"
    assert call(hubd, op="decision.check", agent_token="full-token", kind="go", actions="eye-test", id=eye["id"])["answer"] == "yes", "an eye test goes on"

    fresh = go(hubd, login)
    refused = call(hubd, op="decision.check", agent_token="full-token", kind="go", actions="reboot", id=fresh["id"])
    assert refused["answer"] == "no" and "has the device" in refused["words"]
    assert call(hubd, op="decision.done", token=login)["holding"]["holding"] is False
    assert call(hubd, op="decision.check", agent_token="full-token", kind="go", actions="reboot", id=fresh["id"])["answer"] == "yes"


def test_a_restart_keeps_decisions_and_who_has_the_device(tmp_path):
    clock = Clock()
    store = Decisions(tmp_path / "d", clock=clock)
    made = store.add("go", "w", GO, {"runs": 2})
    store.have_device()
    store.done()
    made = store.add("go", "w", GO, {"runs": 2})
    store.spend(made)
    store.have_device()
    again = Decisions(tmp_path / "d", clock=clock)
    assert again.holding is not None and again.check_go("reboot", None, "s", None)[0]["answer"] == "no"
    again.done()
    fresh = again.add("go", "w", GO, {"runs": 2})
    third = Decisions(tmp_path / "d", clock=clock)
    assert third.holding is None and third.check_go("reboot", None, "s", None, fresh["id"])[0]["answer"] == "yes"
    assert not (tmp_path / "d" / f"{fresh['id']}.json").stat().st_mode & 0o077
    assert not (tmp_path / "d").stat().st_mode & 0o077


def test_a_decision_file_that_cant_be_read_answers_no(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "d-000000000000.json").write_text("{broken")
    (tmp_path / "d" / "d-111111111111.json").write_text(json.dumps({"id": "d-222222222222"}))
    store = Decisions(tmp_path / "d")
    assert store.list() == [] and store.check_go("reboot", None, None, None, "d-000000000000")[0]["answer"] == "no"


def test_if_its_not_clear_who_has_the_device_you_do(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "holding.json").write_text("nonsense")
    assert Decisions(tmp_path / "d").holding is not None


@pytest.mark.parametrize("kind,scope", [("retention", {"files": ["dumps/old.bin"]}), ("standing", {"subject": "scroll default"})])
def test_a_kind_nothing_reads_cant_be_recorded(world, kind, scope):
    hubd, store, _clock, login = world
    assert call(hubd, op="decision.add", token=login, kind=kind, words="w", scope=scope)["ok"] is False
    assert call(hubd, op="decision.request", agent_token="full-token", kind=kind, scope=scope, why="w")["ok"] is False
    assert call(hubd, op="decision.check", agent_token="full-token", kind=kind, target="x")["ok"] is False
    assert store.list() == []


# --- merge decisions, asked about ---------------------------------------------------------
def merge_decision(hubd, login, head=HEAD):
    return call(hubd, op="decision.add", token=login, kind="merge", words="merge it", scope={"repo": "hub", "number": 7, "head": head})


def test_a_merge_decision_binds_the_head_now_and_the_base(world):
    hubd, _store, _clock, login = world
    assert "isn't the head" in merge_decision(hubd, login, OTHER)["error"]
    made = merge_decision(hubd, login)["decision"]
    assert made["scope"]["base"] == "main" and made["scope"]["head"] == HEAD and "into main" in made["says"]
    for bad in ("abc", HEAD.upper(), HEAD[:39], "x" * 40, None):
        assert call(hubd, op="decision.add", token=login, kind="merge", words="w", scope={"repo": "hub", "number": 7, "head": bad})["ok"] is False


def test_the_queues_approval_binds_the_head_it_showed(world, fake_pr):
    """What the queue page posts. A stale page can't approve a head you didn't see, and no token can post it."""
    hubd, store, _clock, login = world
    form = dict(op="decision.add", kind="merge", words="Approved on the queue page.", scope={"repo": "hub", "number": 7, "head": HEAD})
    for token in ("full-token", "general-token", "locked-token", None):
        assert call(hubd, agent_token=token, **form)["denied"]
    fake_pr[1].write_text(json.dumps({"state": "OPEN", "headRefOid": OTHER, "baseRefName": "main"}))
    reply = call(hubd, token=login, **form)
    assert reply["ok"] is False and "isn't the head" in reply["error"]
    assert not store.list(), "nothing was recorded"
    fake_pr[1].write_text(json.dumps({"state": "OPEN", "headRefOid": HEAD, "baseRefName": "main"}))
    decision = call(hubd, token=login, **form)["decision"]
    assert decision["state"] == "current" and decision["scope"]["base"] == "main" and decision["scope"]["session"] == "any"
    assert "pr merge" not in (fake_pr[0].parent / "gh.log").read_text(), "approving merges nothing"


def test_a_moved_head_fails(world, fake_pr):
    hubd, store, _clock, login = world
    made = merge_decision(hubd, login)["decision"]
    check = lambda target="hub#7": call(hubd, op="decision.check", agent_token="full-token", kind="merge", target=target)
    assert check()["answer"] == "yes" and check(f"hub#7@{HEAD}")["answer"] == "yes"
    named = check(f"hub#7@{OTHER}")
    assert named["answer"] == "no" and "not " + OTHER[:12] in named["words"], "a decision for one head can't merge another"
    assert check("hub#8")["answer"] == "no" and check("boot#7")["answer"] == "no"
    fake_pr[1].write_text(json.dumps({"state": "OPEN", "headRefOid": OTHER, "baseRefName": "main"}))
    moved = check()
    assert moved["answer"] == "no" and "moved" in moved["words"]
    assert store._all[made["id"]]["state"] == "ended" and "head moved" in store._all[made["id"]]["why_ended"]
    assert check()["answer"] == "no"


def test_a_retarget_answers_no(world, fake_pr):
    hubd, store, _clock, login = world
    made = merge_decision(hubd, login)["decision"]
    fake_pr[1].write_text(json.dumps({"state": "OPEN", "headRefOid": HEAD, "baseRefName": "other"}))
    answer = call(hubd, op="decision.check", agent_token="full-token", kind="merge", target="hub#7")
    assert answer["answer"] == "no" and "other" in answer["words"]
    assert store._all[made["id"]]["state"] == "current", "it can be retargeted back"


def test_github_not_saying_answers_no(world, fake_pr):
    hubd, _store, _clock, login = world
    merge_decision(hubd, login)
    fake_pr[1].write_text("not json")
    assert call(hubd, op="decision.check", agent_token="full-token", kind="merge", target="hub#7")["answer"] == "no"


def test_a_merge_request_is_a_card_and_cant_be_spent(world, fake_pr):
    hubd, store, _clock, login = world
    assert "isn't the head" in call(hubd, op="decision.request", agent_token="full-token", kind="merge", scope={"repo": "hub", "number": 7, "head": OTHER}, why="w")["error"]
    asked = call(hubd, op="decision.request", agent_token="full-token", kind="merge", scope={"repo": "hub", "number": 7, "head": HEAD}, why="green")
    assert store._all[asked["id"]]["scope"]["session"] == "full" and store._all[asked["id"]]["scope"]["base"] == "main"
    assert call(hubd, op="decision.check", agent_token="full-token", kind="merge", target="hub#7")["answer"] == "no"
    fake_pr[1].write_text(json.dumps({"state": "OPEN", "headRefOid": OTHER, "baseRefName": "main"}))
    assert "isn't the head" in call(hubd, op="decision.approve", token=login, id=asked["id"])["error"], "it moved while the card was up"
    fake_pr[1].write_text(json.dumps({"state": "OPEN", "headRefOid": HEAD, "baseRefName": "main"}))
    assert call(hubd, op="decision.approve", token=login, id=asked["id"])["ok"]
    assert call(hubd, op="decision.check", agent_token="full-token", kind="merge", target="hub#7")["answer"] == "yes"
    assert call(hubd, op="decision.check", agent_token="other-token", kind="merge", target="hub#7")["answer"] == "no", "it answers to who asked"
    assert "spent by the merge" in call(hubd, op="decision.use", agent_token="full-token", kind="merge", target="hub#7")["error"]


def test_bad_arguments_are_said_not_raised(world):
    hubd, _store, _clock, login = world
    for reply in (call(hubd, op="decision.check", agent_token="full-token", kind="go"),
                  call(hubd, op="decision.check", agent_token="full-token", kind="nonsense"),
                  call(hubd, op="decision.check", agent_token="full-token", kind="merge", target="nonsense"),
                  call(hubd, op="decision.check", agent_token="full-token", kind="retention"),
                  call(hubd, op="decision.request", agent_token="full-token", kind="go", scope="all", why="w"),
                  call(hubd, op="decision.request", agent_token="full-token", kind="go", scope=GO, why=" "),
                  call(hubd, op="decision.request", agent_token="full-token", kind="merge", scope=None, why="w"),
                  call(hubd, op="decision.add", token=login, kind="merge", words="w", scope={"repo": "../x", "number": 1, "head": HEAD})):
        assert reply["ok"] is False and reply["error"]
    with pytest.raises(DecisionError):
        decisions.actions_of(["Rm -rf"])


def test_without_a_store_it_says_so(tmp_path):
    hubd = Hubd(Gh("gh", workdir=str(tmp_path)), Shells(), auth.Sessions(), "general-token")
    assert asyncio.run(hubd.request({"op": "decision.holding"}))["ok"] is False
    assert asyncio.run(hubd.request({"op": "decision.check", "agent_token": "general-token"}))["ok"] is False


# --- merges: every path through Hubd.request ------------------------------------------------
def merge_argv(head=HEAD, *more):
    return ["pr", "merge", "7", "-R", "GlassineOS/hub", "--squash", "--match-head-commit", head, *more]


def merges_run(tmp_path):
    log = tmp_path / "gh.log"
    return [line for line in (log.read_text().splitlines() if log.exists() else []) if line.startswith("pr merge")]


def gh_says(fake_pr, tmp_path, code, stderr=""):
    """The next merges exit with this."""
    script = fake_pr[0]
    script.write_text(f'#!/bin/sh\necho "$@" >> {tmp_path}/gh.log\nif [ "$1 $2" = "pr view" ]; then cat {fake_pr[1]}; else echo "{stderr}" >&2; exit {code}; fi\n')


def test_no_token_is_refused_a_merge(world, tmp_path):
    hubd, _store, _clock, login = world
    merge_decision(hubd, login)
    for req in ({}, {"agent_token": "nope"}, {"token": "nope"}, {"token": None, "agent_token": None}):
        reply = call(hubd, op="gh", argv=merge_argv(), **req)
        assert reply["ok"] is False and reply["refused"], req
    assert merges_run(tmp_path) == []


def test_a_login_merges_with_a_head_and_no_decision(world, tmp_path):
    hubd, _store, _clock, login = world
    reply = call(hubd, op="gh", argv=merge_argv(), token=login)
    assert reply["ok"] and reply["code"] == 0 and len(merges_run(tmp_path)) == 1
    assert HEAD in merges_run(tmp_path)[0]


@pytest.mark.parametrize("argv", [
    ["pr", "merge", "7", "-R", "GlassineOS/hub", "--squash"],
    ["pr", "merge", "7", "-R", "GlassineOS/hub", "--match-head-commit", "abc"],
    ["pr", "merge", "7", "-R", "GlassineOS/hub", "--match-head-commit", HEAD, "--auto"],
    ["pr", "merge", "7", "-R", "GlassineOS/hub", "--match-head-commit", HEAD, "--match-head-commit", OTHER],
    ["pr", "merge", "7", "-R", "GlassineOS/hub", f"--match-head-commit={HEAD}"],
    ["pr", "merge", "https://github.com/GlassineOS/hub/pull/8", "-R", "GlassineOS/hub", "--match-head-commit", HEAD],
    ["pr", "merge", "7", "-R", "GlassineOS/hub", "--match-head-commit", HEAD, "--subject", "x"],
    ["pr", "merge", "-R", "GlassineOS/hub", "--match-head-commit", HEAD],
    ["pr", "merge", "7", "-R", "GlassineOS/hub", "--match-head-commit", HEAD],
    ["pr", "merge", "7", "-R", "GlassineOS/hub\n", "--squash", "--match-head-commit", HEAD],
])
def test_even_a_login_merges_only_in_the_form_the_app_builds(world, tmp_path, argv):
    hubd, _store, _clock, login = world
    from hubd.ghpolicy import Refused
    with pytest.raises(Refused):
        call(hubd, op="gh", argv=argv, token=login)
    assert merges_run(tmp_path) == []


def test_an_agent_token_needs_a_matching_decision(world, tmp_path):
    hubd, store, _clock, login = world
    for token in ("full-token", "general-token"):
        reply = call(hubd, op="gh", argv=merge_argv(), agent_token=token)
        assert reply["refused"] and "no decision" in reply["error"], token
    made = merge_decision(hubd, login)["decision"]
    assert call(hubd, op="gh", argv=["pr", "merge", "8", "-R", "GlassineOS/hub", "--squash", "--match-head-commit", HEAD], agent_token="full-token")["refused"], "another pull request"
    assert call(hubd, op="gh", argv=["pr", "merge", "7", "-R", "GlassineOS/boot", "--squash", "--match-head-commit", HEAD], agent_token="full-token")["refused"], "another repository"
    assert merges_run(tmp_path) == []
    reply = call(hubd, op="gh", argv=merge_argv(), agent_token="full-token")
    assert reply["ok"] and reply["code"] == 0 and len(merges_run(tmp_path)) == 1
    assert store._all[made["id"]]["state"] == "ended" and "merged" in store._all[made["id"]]["why_ended"]
    assert call(hubd, op="gh", argv=merge_argv(), agent_token="full-token")["refused"], "once"
    assert len(merges_run(tmp_path)) == 1


def test_a_different_head_is_refused(world, tmp_path):
    hubd, store, _clock, login = world
    made = merge_decision(hubd, login)["decision"]
    reply = call(hubd, op="gh", argv=merge_argv(OTHER), agent_token="full-token")
    assert reply["refused"] and "not " + OTHER[:12] in reply["error"]
    assert merges_run(tmp_path) == [] and store._all[made["id"]]["state"] == "current", "that was someone naming the wrong head"


def test_a_moved_head_is_refused_and_ends_the_decision(world, tmp_path, fake_pr):
    hubd, store, _clock, login = world
    made = merge_decision(hubd, login)["decision"]
    fake_pr[1].write_text(json.dumps({"state": "OPEN", "headRefOid": OTHER, "baseRefName": "main"}))
    assert call(hubd, op="gh", argv=merge_argv(), agent_token="full-token")["refused"]
    assert merges_run(tmp_path) == [] and store._all[made["id"]]["state"] == "ended"


def test_a_retarget_is_refused_and_github_not_saying_refuses(world, tmp_path, fake_pr):
    hubd, _store, _clock, login = world
    merge_decision(hubd, login)
    fake_pr[1].write_text(json.dumps({"state": "OPEN", "headRefOid": HEAD, "baseRefName": "other"}))
    assert "other" in call(hubd, op="gh", argv=merge_argv(), agent_token="full-token")["error"]
    fake_pr[1].write_text("not json")
    assert "can't say" in call(hubd, op="gh", argv=merge_argv(), agent_token="full-token")["error"]
    assert merges_run(tmp_path) == []


def test_a_locked_token_cant_use_a_decision(world, tmp_path):
    hubd, _store, _clock, login = world
    merge_decision(hubd, login)
    assert call(hubd, op="gh", argv=merge_argv(), agent_token="locked-token")["refused"]
    assert merges_run(tmp_path) == []


def test_a_decision_for_one_session_doesnt_serve_another(world, tmp_path):
    hubd, _store, _clock, login = world
    asked = call(hubd, op="decision.request", agent_token="full-token", kind="merge", scope={"repo": "hub", "number": 7, "head": HEAD}, why="w")
    call(hubd, op="decision.approve", token=login, id=asked["id"])
    assert call(hubd, op="gh", argv=merge_argv(), agent_token="other-token")["refused"]
    assert call(hubd, op="gh", argv=merge_argv(), agent_token="general-token")["refused"]
    assert call(hubd, op="gh", argv=merge_argv(), agent_token="full-token")["code"] == 0


def test_a_merge_github_refuses_doesnt_spend_it(world, tmp_path, fake_pr):
    hubd, store, _clock, login = world
    made = merge_decision(hubd, login)["decision"]
    gh_says(fake_pr, tmp_path, 1, "GraphQL: Pull Request is not mergeable (mergePullRequest)")
    reply = call(hubd, op="gh", argv=merge_argv(), agent_token="full-token")
    assert reply["ok"] and reply["code"] == 1 and "still stands" in reply["stderr"]
    assert store._all[made["id"]]["state"] == "current"
    gh_says(fake_pr, tmp_path, 0)
    assert call(hubd, op="gh", argv=merge_argv(), agent_token="full-token")["code"] == 0
    assert store._all[made["id"]]["state"] == "ended"


def test_github_saying_the_head_moved_ends_it(world, tmp_path, fake_pr):
    hubd, store, _clock, login = world
    made = merge_decision(hubd, login)["decision"]
    gh_says(fake_pr, tmp_path, 1, "GraphQL: Head branch was modified. Review and try the merge again. (mergePullRequest)")
    call(hubd, op="gh", argv=merge_argv(), agent_token="full-token")
    assert store._all[made["id"]]["state"] == "ended" and "head moved" in store._all[made["id"]]["why_ended"]


@pytest.mark.parametrize("code, stderr", [(124, "gh: timed out"), (1, "HTTP 502: Bad Gateway"), (1, "error connecting to api.github.com"), (1, "GraphQL: Something went wrong while executing your query")])
def test_an_outcome_that_isnt_known_spends_it_and_says_so(world, tmp_path, fake_pr, code, stderr):
    hubd, store, _clock, login = world
    made = merge_decision(hubd, login)["decision"]
    gh_says(fake_pr, tmp_path, code, stderr)
    reply = call(hubd, op="gh", argv=merge_argv(), agent_token="full-token")
    assert "isn't known" in reply["stderr"] and "spent" in reply["stderr"]
    assert store._all[made["id"]]["state"] == "ended" and "isn't known" in store._all[made["id"]]["why_ended"]
    assert call(hubd, op="gh", argv=merge_argv(), agent_token="full-token")["refused"]


def test_gh_failing_after_the_merge_counts_as_merged(world, tmp_path, fake_pr):
    hubd, store, _clock, login = world
    made = merge_decision(hubd, login)["decision"]
    gh_says(fake_pr, tmp_path, 1, "failed to delete remote branch")
    fake_pr[1].write_text(json.dumps({"state": "OPEN", "headRefOid": HEAD, "baseRefName": "main"}))
    script = fake_pr[0].read_text().replace('exit 1; fi', f"""echo '{{"state": "MERGED"}}' > {fake_pr[1]}; exit 1; fi""")
    fake_pr[0].write_text(script)
    reply = call(hubd, op="gh", argv=merge_argv(), agent_token="full-token")
    assert "merged" in store._all[made["id"]]["why_ended"]
    assert reply["code"] == 0 and "It merged" in reply["stderr"], "or the page and the Steward take it for a failure, and try again"


def test_a_click_uses_up_a_decision_for_that_head(world, tmp_path):
    hubd, store, _clock, login = world
    made = merge_decision(hubd, login)["decision"]
    assert call(hubd, op="gh", argv=merge_argv(), token=login)["code"] == 0
    assert store._all[made["id"]]["state"] == "ended" and "used" in store._all[made["id"]]["why_ended"]


def test_a_click_at_another_head_that_merges_ends_the_decision_too(world):
    hubd, store, _clock, login = world
    made = merge_decision(hubd, login)["decision"]
    assert call(hubd, op="gh", argv=merge_argv(OTHER), token=login)["code"] == 0, "GitHub is what refuses a click on a moved head"
    assert store._all[made["id"]]["why_ended"] == "the pull request merged"


def test_hubd_stopping_during_a_merge_spends_it_and_says_so(tmp_path):
    clock = Clock()
    store = Decisions(tmp_path / "d", clock=clock)
    made = store.add("merge", "w", {"repo": "hub", "number": 7, "head": HEAD})
    store.claim(made)
    with pytest.raises(DecisionError):
        store.claim(made)
    again = Decisions(tmp_path / "d", clock=clock)
    assert again._all[made["id"]]["state"] == "ended" and "isn't known" in again._all[made["id"]]["why_ended"]
    assert again.merges("hub", 7, None) == []


def test_a_token_can_merge_only_once_even_at_the_same_moment(world, tmp_path):
    hubd, _store, _clock, login = world
    merge_decision(hubd, login)

    async def both():
        return await asyncio.gather(hubd.request({"op": "gh", "argv": merge_argv(), "agent_token": "full-token"}),
                                    hubd.request({"op": "gh", "argv": merge_argv(), "agent_token": "full-token"}))
    replies = asyncio.run(both())
    assert sorted(bool(r.get("refused")) for r in replies) == [False, True]
    assert len(merges_run(tmp_path)) == 1


# --- the Steward's card ---------------------------------------------------------------------
CARD = {"repo": "hub", "number": 7, "head": HEAD}
TOOL = "mcp__glassine-hub__merge_pr"


@pytest.fixture
def steward(world):
    Agents.SCOPES["steward-token"] = {"session": "steward", "tools": ["merge_pr"], "persona": None, "asks_first": ["merge_pr"]}
    yield world
    del Agents.SCOPES["steward-token"]


def card_again(hubd, login, verdict, tool_input=CARD):
    """A card has a future tied to the loop it was made on, so it all happens in one."""
    async def go():
        ask = hubd.asks.add("steward", "PreToolUse", TOOL, tool_input, None, None, 600)
        return ask, await hubd.request({"op": "ask.answer", "token": login, "id": ask.id, "verdict": verdict})
    return asyncio.run(go())


def test_allowing_the_merge_card_is_the_decision_for_that_head(steward, tmp_path):
    hubd, store, clock, login = steward
    assert call(hubd, op="gh", argv=merge_argv(), agent_token="steward-token")["refused"], "no card yet"
    _ask, reply = card_again(hubd, login, "allow")
    assert reply["ok"]
    made = next(r for r in store.list() if r["kind"] == "merge")
    assert made["state"] == "current" and made["scope"]["session"] == "steward" and made["scope"]["base"] == "main" and "card" in made["words"]
    assert call(hubd, op="gh", argv=merge_argv(OTHER), agent_token="steward-token")["refused"], "only that head"
    assert call(hubd, op="gh", argv=merge_argv(), agent_token="full-token")["refused"], "only that session"
    assert call(hubd, op="gh", argv=merge_argv(), agent_token="steward-token")["code"] == 0
    assert call(hubd, op="gh", argv=merge_argv(), agent_token="steward-token")["refused"], "once"


def test_a_yes_on_a_card_doesnt_last(steward, tmp_path):
    hubd, _store, clock, login = steward
    card_again(hubd, login, "allow")
    clock.now += 121
    assert call(hubd, op="gh", argv=merge_argv(), agent_token="steward-token")["refused"]
    assert merges_run(tmp_path) == []


def test_a_grant_kept_from_before_the_change_doesnt_merge(steward, tmp_path):
    """What an Allow left behind before this: a grant, with no decision. Nor does a yes the session remembers."""
    hubd, store, clock, _login = steward
    hubd.asks._grants.append(("steward", "merge_pr", json.dumps(CARD, sort_keys=True), clock.now + 100))
    reply = call(hubd, op="gh", argv=merge_argv(), agent_token="steward-token")
    assert reply["refused"] and "A yes from before" in reply["error"]
    assert merges_run(tmp_path) == [] and store.list() == []


def test_denying_a_card_records_nothing(steward):
    hubd, store, _clock, login = steward
    card_again(hubd, login, "deny")
    assert store.list() == []
    assert call(hubd, op="gh", argv=merge_argv(), agent_token="steward-token")["refused"]


def test_a_card_for_a_head_thats_gone_stays_up_to_say_no_to(steward, fake_pr):
    hubd, store, _clock, login = steward
    fake_pr[1].write_text(json.dumps({"state": "OPEN", "headRefOid": OTHER, "baseRefName": "main"}))
    ask, reply = card_again(hubd, login, "allow")
    assert reply["ok"] is False and "isn't the head" in reply["error"]
    assert hubd.asks.waiting(ask.id) is ask and store.list() == []


def test_a_token_cant_answer_a_merge_card(steward):
    hubd, store, _clock, _login = steward
    async def go():
        ask = hubd.asks.add("steward", "PreToolUse", TOOL, CARD, None, None, 600)
        return await hubd.request({"op": "ask.answer", "agent_token": "steward-token", "id": ask.id, "verdict": "allow"})
    assert asyncio.run(go())["denied"] and store.list() == []


def test_other_cards_make_no_decision(steward):
    hubd, store, _clock, login = steward
    async def go():
        ask = hubd.asks.add("steward", "PreToolUse", "mcp__glassine-hub__comment_pr", {"repo": "hub", "number": 7, "head": HEAD}, None, None, 600)
        return await hubd.request({"op": "ask.answer", "token": login, "id": ask.id, "verdict": "allow"})
    assert asyncio.run(go())["ok"] and store.list() == []
# --- the exact lines the workspace's `dev` sends (tools/devlib.py), over the socket. Any other reply counts as hub down there ---
def over_the_socket(hubd, tmp_path, line: bytes) -> dict:
    async def go():
        path = tmp_path / "s.sock"
        server = await asyncio.start_unix_server(hubd.connection, path=str(path))
        async with server:
            reader, writer = await asyncio.open_unix_connection(str(path))
            writer.write(line + b"\n")
            await writer.drain()
            reply = json.loads(await reader.readline())
            writer.close()
            return reply
    return asyncio.run(go())


def test_devs_go_check_gets_the_answer_it_reads(world, tmp_path):
    hubd, _store, _clock, login = world
    made = go(hubd, login, scope={"actions": ["reboot"]})
    line = {"op": "decision.check", "agent_token": "full-token", "kind": "go", "id": made["id"], "actions": ["reboot"], "target": "na1"}
    reply = over_the_socket(hubd, tmp_path, json.dumps(line).encode())
    assert reply["ok"] is True and reply["answer"] == "yes" and isinstance(reply["words"], str) and reply["words"]
    no = over_the_socket(hubd, tmp_path, json.dumps({**line, "actions": ["suspend"]}).encode())
    assert no["ok"] is True and no["answer"] == "no" and "suspend" in no["words"]


def test_devs_holding_read_needs_no_token(world, tmp_path):
    hubd, _store, _clock, login = world
    reply = over_the_socket(hubd, tmp_path, b'{"op": "decision.holding"}')
    assert reply["ok"] is True and reply["holding"] is False
    call(hubd, op="decision.have_device", token=login)
    assert over_the_socket(hubd, tmp_path, b'{"op": "decision.holding"}')["holding"] is True


def test_devs_report_is_kept_and_read_back(tmp_path, fake_pr):
    from hubd.devices import Devices
    hubd = Hubd(Gh(str(fake_pr[0]), workdir=str(tmp_path)), Shells(), auth.Sessions(), "general-token", device_reports=Devices(tmp_path / "devices"))
    report = {"device": "na1", "device_time": 1700000000, "lock": {"owner": "a6", "purpose": "bench", "since": "1700000000", "expected_end": "1700001800", "does": "reboot", "held": True},
              "queue": [{"file": "1700000000-a0", "who": "a0", "for": "x", "on": "y", "time": 1700000000, "until": 1700003600, "ready": False, "expired": False}],
              "base": None, "deployment": None, "boot_image": None, "renderer": "gpu",
              "overrides": {"epdd": {"owner": "a6", "survives_reboot": "yes"}}, "left": {}, "free_kb": 1024, "bases": None}
    assert over_the_socket(hubd, tmp_path, json.dumps({"op": "device.report", "report": report}).encode()) == {"ok": True}
    says = hubd.devices.status("na1")["says"]
    assert "Held by a6: bench" in says and "Override epdd by a6, survives a reboot" in says and "1.0 MiB" in says


# --- from the review --------------------------------------------------------------------------
def test_a_merge_decision_isnt_recorded_when_github_cant_say(world, fake_pr, tmp_path):
    hubd, store, _clock, login = world
    fake_pr[0].write_text('#!/bin/sh\nexit 1\n')
    assert "can't say" in merge_decision(hubd, login)["error"]
    assert "can't say" in call(hubd, op="decision.request", agent_token="full-token", kind="merge", scope={"repo": "hub", "number": 7, "head": HEAD}, why="w")["error"]
    assert store.list() == []


def test_a_merge_card_isnt_approved_when_github_cant_say_or_the_base_moved(world, fake_pr):
    hubd, store, _clock, login = world
    asked = call(hubd, op="decision.request", agent_token="full-token", kind="merge", scope={"repo": "hub", "number": 7, "head": HEAD}, why="w")["id"]
    script = fake_pr[0].read_text()
    fake_pr[0].write_text('#!/bin/sh\nexit 1\n')
    assert "can't say" in call(hubd, op="decision.approve", token=login, id=asked)["error"]
    fake_pr[0].write_text(script)
    fake_pr[1].write_text(json.dumps({"state": "OPEN", "headRefOid": HEAD, "baseRefName": "release"}))
    assert "now targets release" in call(hubd, op="decision.approve", token=login, id=asked)["error"]
    assert store._all[asked]["state"] == "requested", "it stays up, to say no to"
    fake_pr[1].write_text(json.dumps({"state": "OPEN", "headRefOid": HEAD, "baseRefName": "main"}))
    assert call(hubd, op="decision.approve", token=login, id=asked)["ok"]


def test_a_decision_with_no_base_answers_no(world, tmp_path):
    hubd, store, _clock, _login = world
    made = store.add("merge", "w", {"repo": "hub", "number": 7, "head": HEAD})
    assert made["scope"]["base"] is None
    assert call(hubd, op="decision.check", agent_token="full-token", kind="merge", target="hub#7")["answer"] == "no"


@pytest.mark.parametrize("asked", ["any", "other", "general"])
def test_a_session_cant_choose_who_its_card_is_for(world, asked):
    hubd, store, _clock, login = world
    for kind, scope in (("go", GO), ("merge", {"repo": "hub", "number": 7, "head": HEAD})):
        made = call(hubd, op="decision.request", agent_token="full-token", kind=kind, scope={**scope, "session": asked}, why="w")["id"]
        assert store._all[made]["scope"]["session"] == "full", kind


def test_a_card_stays_with_the_conversation_that_asked(world):
    hubd, store, _clock, login = world
    asked = call(hubd, op="decision.request", agent_token="full-token", kind="go", scope=GO, why="w")["id"]
    now_holding = store.session_id_of
    store.session_id_of = lambda _name: "the-name-moved"
    assert call(hubd, op="decision.approve", token=login, id=asked)["ok"]
    assert store._all[asked]["scope"]["session_id"] == "conversation-1"
    assert call(hubd, op="decision.check", agent_token="full-token", kind="go", actions="reboot", id=asked)["answer"] == "no"
    store.session_id_of = now_holding
    assert call(hubd, op="decision.check", agent_token="full-token", kind="go", actions="reboot", id=asked)["answer"] == "yes"


def test_a_merge_card_stays_with_the_conversation_too(world):
    hubd, store, _clock, login = world
    asked = call(hubd, op="decision.request", agent_token="full-token", kind="merge", scope={"repo": "hub", "number": 7, "head": HEAD}, why="w")["id"]
    assert call(hubd, op="decision.approve", token=login, id=asked)["ok"]
    assert call(hubd, op="decision.check", agent_token="full-token", kind="merge", target="hub#7")["answer"] == "yes"
    now_holding = store.session_id_of
    store.session_id_of = lambda _name: "the-name-moved"
    assert call(hubd, op="decision.check", agent_token="full-token", kind="merge", target="hub#7")["answer"] == "no"
    store.session_id_of = now_holding


def test_an_unknown_conversation_answers_to_nobody(world):
    hubd, store, _clock, login = world
    assert "doesn't know a conversation" in call(hubd, op="decision.add", token=login, kind="go", words="w", scope={**GO, "session": "gone"}, ends={"runs": 1})["error"]
    made = store.add("go", "w", {**GO, "session": "full"}, {"runs": 1})
    store._save({**made, "scope": {**made["scope"], "session_id": None}})
    assert call(hubd, op="decision.check", agent_token="full-token", kind="go", actions="reboot", id=made["id"])["answer"] == "no"


def test_a_cards_time_starts_when_its_approved(world):
    hubd, store, clock, login = world
    asked = call(hubd, op="decision.request", agent_token="full-token", kind="go", scope=GO, why="w", ends={"hours": 1})["id"]
    assert "until" not in store._all[asked]["ends"] and "1 hour from when it's approved" in store.view(store._all[asked])["says"]
    clock.now += 2 * 3600
    made = call(hubd, op="decision.approve", token=login, id=asked)["decision"]
    assert made["state"] == "current" and made["ends"]["until"] == clock.now + 3600
    assert call(hubd, op="decision.check", agent_token="full-token", kind="go", actions="reboot", id=asked)["answer"] == "yes"
    clock.now += 3601
    assert call(hubd, op="decision.check", agent_token="full-token", kind="go", actions="reboot", id=asked)["answer"] == "no"


def test_a_card_can_be_narrowed_only_by_its_actions(world):
    hubd, store, _clock, login = world
    asked = call(hubd, op="decision.request", agent_token="full-token", kind="go", scope=GO, why="w")["id"]
    assert "narrowed" in call(hubd, op="decision.approve", token=login, id=asked, scope={"session": "any"})["error"]
    merge = call(hubd, op="decision.request", agent_token="full-token", kind="merge", scope={"repo": "hub", "number": 7, "head": HEAD}, why="w")["id"]
    assert "narrowed" in call(hubd, op="decision.approve", token=login, id=merge, scope={"head": OTHER})["error"]
    assert "narrowed" in call(hubd, op="decision.approve", token=login, id=merge, scope={"base": None})["error"]


def test_a_decision_ended_during_githubs_answer_answers_no(world):
    hubd, store, _clock, login = world
    made = merge_decision(hubd, login)["decision"]
    stale = store._all[made["id"]]
    store.end(made["id"], None)
    assert store.merge_answer(stale, {"state": "OPEN", "headRefOid": HEAD, "baseRefName": "main"})["answer"] == "no"
    assert "ended" == store._all[made["id"]]["state"]


@pytest.mark.parametrize("kept", [
    {"id": "d-111111111111"},
    {"id": "d-111111111111", "kind": "standing", "state": "current", "scope": {"subject": "x"}, "ends": {}, "made": 1, "asked_by": None, "why": None, "why_ended": None, "words": "w", "ended": None},
    {"id": "d-111111111111", "kind": "go", "state": "current", "scope": {}, "ends": {}, "made": 1, "asked_by": None, "why": None, "why_ended": None, "words": "w", "ended": None},
    {"id": "d-111111111111", "kind": "go", "state": "soon", "scope": {"actions": ["reboot"], "device": "any", "session": "any"}, "ends": {}, "made": 1, "asked_by": None, "why": None, "why_ended": None, "words": "w", "ended": None},
])
def test_a_file_missing_what_answers_read_is_left_out(tmp_path, kept):
    good = Decisions(tmp_path)
    made = good.add("go", "w", GO, {"runs": 1})
    (tmp_path / "d-111111111111.json").write_text(json.dumps(kept))
    again = Decisions(tmp_path)
    assert [r["id"] for r in again.list()] == [made["id"]]
    assert again.have_device() == 1


def test_using_a_go_says_whats_left_now(world):
    hubd, _store, _clock, login = world
    made = go(hubd, login, ends={"runs": 2})
    use = lambda: call(hubd, op="decision.use", agent_token="full-token", kind="go", actions="reboot", id=made["id"])["words"]
    assert "1 run left" in use()
    assert "0 runs left" in use()


def test_text_keeps_nothing_that_cant_be_shown(world):
    hubd, store, _clock, login = world
    asked = call(hubd, op="decision.request", agent_token="full-token", kind="go", scope=GO, why="a\ud800\ufe00\u2800b\nc")["id"]
    assert store._all[asked]["why"] == "ab\nc"
    json.dumps(store.list(), ensure_ascii=False).encode("utf-8")


def test_a_card_from_a_conversation_nobody_knows_stays_up(steward):
    hubd, store, _clock, login = steward
    store.session_id_of = lambda _name: None
    ask, reply = card_again(hubd, login, "allow")
    assert reply["ok"] is False and "doesn't know a conversation" in reply["error"]
    assert hubd.asks.waiting(ask.id) is ask and store.list() == []


# --- from the review of the merges --------------------------------------------------------------
def test_a_card_can_name_the_repository_with_the_organization(steward):
    hubd, store, _clock, login = steward
    _ask, reply = card_again(hubd, login, "allow", {"repo": "GlassineOS/hub", "number": 7, "head": HEAD})
    assert reply["ok"] and next(r for r in store.list() if r["kind"] == "merge")["scope"]["repo"] == "hub"
    assert call(hubd, op="gh", argv=merge_argv(), agent_token="steward-token")["code"] == 0


def test_a_card_is_never_answered_and_left_without_its_decision(steward, fake_pr):
    hubd, store, _clock, login = steward
    fake_pr[1].write_text(json.dumps({"state": "OPEN", "headRefOid": HEAD, "baseRefName": "release+1"}))
    ask, reply = card_again(hubd, login, "allow")
    assert reply["ok"] is False and "branch" in reply["error"]
    assert hubd.asks.waiting(ask.id) is ask and store.list() == []


def test_allowing_a_full_sessions_card_makes_a_decision_and_its_terminal_doesnt(world):
    hubd, store, _clock, login = world
    assert call(hubd, op="gh", argv=merge_argv(), agent_token="full-token")["refused"], "a yes in its terminal reaches hubd as this"
    async def go():
        ask = hubd.asks.add("full", "PermissionRequest", TOOL, CARD, None, None, 600)
        return await hubd.request({"op": "ask.answer", "token": login, "id": ask.id, "verdict": "allow"})
    assert asyncio.run(go())["ok"]
    assert call(hubd, op="gh", argv=merge_argv(), agent_token="full-token")["code"] == 0


def test_a_failure_recording_the_outcome_cant_leave_it_using(world, monkeypatch):
    hubd, store, _clock, login = world
    made = merge_decision(hubd, login)["decision"]
    async def fails(*_):
        raise OSError("no")
    monkeypatch.setattr(hubd, "_merge_outcome", fails)
    with pytest.raises(OSError):
        call(hubd, op="gh", argv=merge_argv(), agent_token="full-token")
    assert store._all[made["id"]]["state"] == "ended" and "isn't known" in store._all[made["id"]]["why_ended"]


def test_a_click_uses_up_a_sessions_decision_and_a_merge_ends_the_rest(world):
    hubd, store, _clock, login = world
    named = call(hubd, op="decision.request", agent_token="full-token", kind="merge", scope={"repo": "hub", "number": 7, "head": HEAD}, why="w")["id"]
    call(hubd, op="decision.approve", token=login, id=named)
    other = call(hubd, op="decision.request", agent_token="other-token", kind="merge", scope={"repo": "hub", "number": 7, "head": HEAD}, why="w")["id"]
    call(hubd, op="decision.approve", token=login, id=other)
    assert call(hubd, op="gh", argv=merge_argv(), token=login)["code"] == 0
    assert {store._all[i]["state"] for i in (named, other)} == {"ended"}
    assert "the pull request merged" in {store._all[i]["why_ended"] for i in (named, other)}


def test_a_click_gh_fails_after_says_it_merged(world, tmp_path, fake_pr):
    hubd, _store, _clock, login = world
    fake_pr[0].write_text(f"""#!/bin/sh\nif [ "$1 $2" = "pr view" ]; then echo '{{"state": "MERGED"}}'; else echo "failed to delete remote branch" >&2; exit 1; fi\n""")
    reply = call(hubd, op="gh", argv=merge_argv(), token=login)
    assert reply["code"] == 0 and "It merged" in reply["stderr"]


def test_the_refusal_names_a_way_this_session_has(steward):
    hubd, _store, _clock, _login = steward
    words = call(hubd, op="gh", argv=merge_argv(), agent_token="steward-token")["error"]
    assert "decision_request" not in words and "Needs you" not in words and "merge_pr" in words and "card" in words
    full = call(hubd, op="gh", argv=merge_argv(), agent_token="full-token")["error"]
    assert "decision_request" in full and "kind merge" in full and "merge_pr" in full and "card" not in full
    assert full.count("Ask with") == 1 and "Call merge_pr with this head" not in full, "told one way, not both"


def test_approving_a_head_twice_keeps_one_decision_to_take_back(world):
    hubd, _store, _clock, login = world
    first = merge_decision(hubd, login)["decision"]
    assert merge_decision(hubd, login)["decision"]["id"] == first["id"], "a second tab"
    mine = [d for d in call(hubd, op="decision.list", token=login)["decisions"] if d["kind"] == "merge" and d["state"] == "current"]
    assert [d["id"] for d in mine] == [first["id"]]
    assert call(hubd, op="decision.end", token=login, id=first["id"], why="no")["ok"]
    assert merge_decision(hubd, login)["decision"]["id"] != first["id"], "ended, so it can be given again"
