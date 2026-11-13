# SPDX-License-Identifier: GPL-2.0-or-later
"""Signals, routing, facts and evaluation: what moves a workflow instance on its own."""
import asyncio
import itertools
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from hubd import auth, judge as judgelib, machine, machinerun, summary
from hubd.agents import Agents, Library
from hubd.feed import Feed
from hubd.instances import FILE, Instance, Machines
from hubd.machinerun import HubFacts, Runner, check, pr_facts, tried
from hubd.server import Hubd

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "hubd" / "machine_hook.py"
LIBRARY = Library(REPO / "agents")

TWO = '''
schema = 1
name = "two"
initial = "a"

[state.a]
[[state.a.exit]]
to = "b"
decided_by = "facts"
requires = ["pr.open"]
on = ["turn.end", "feed:pr.checks"]

[state.b]
final = true
'''


def workflow(*exits: str, extra: str = "") -> str:
    """A workflow whose state a has these exits (TOML bodies), each to a final state."""
    body = "".join(f"[[state.a.exit]]\n{e.strip()}\n" for e in exits)
    targets = dict.fromkeys(line.split('"')[1] for e in exits for line in e.splitlines() if line.startswith("to = "))
    finals = "".join(f"[state.{t}]\nfinal = true\n" for t in targets)
    return f'''schema = 1
name = "w"
initial = "a"
judge = "default"
[state.a]
{body}
{finals}{extra}'''


JUDGED = workflow('to = "b"\ndecided_by = "judge"\nwhen = "The change is complete"\nrequires = ["pr.open"]\non = ["turn.end"]')
TURN = "user: go on\n\nassistant: The change is complete and pushed."


class Fake(judgelib.Judge):
    """Folds the summary to a fixed text and answers the question with what it was given."""
    provider, model = "fake", "fixed"

    def __init__(self, answer=None, gate: asyncio.Event | None = None):
        self.answer = answer if answer is not None else {"exit": 0, "evidence": "The change is complete", "confidence": 0.9}
        self.gate, self.asked, self.folds = gate, [], 0

    async def complete(self, system, user, schema):
        if schema is summary.FOLD_SCHEMA:
            self.folds += 1
            return {"summary": "Working on it."}, 0.001
        self.asked.append(user)
        if self.gate is not None:
            await self.gate.wait()
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer, 0.002


class World:
    def __init__(self, tmp: Path, judge=None, facts=None, debounce=0.0, sleep=None):
        self.sessions = tmp / "sessions"
        self.sessions.mkdir()
        self.machines = Machines(self.sessions, tmp / "machines.sqlite", lambda _a: None, lambda n: (self.sessions / n / "session.json").exists(),
                                 clock=lambda: 1000.0)
        self.judge = judge or Fake()
        self.facts = facts if facts is not None else {}
        self.runner = Runner(self.machines, facts=lambda name, _r: self.facts.get(name, {}), judges=lambda: {"default": self.judge},
                             turn=lambda _n, _r: TURN, items=lambda _n, record: [(c["repo"], c["number"]) for c in record["config"]["covers"]],
                             names=lambda: sorted(p.name for p in self.sessions.iterdir()), debounce=debounce,
                             sleep=sleep or (lambda _s: asyncio.sleep(0)))

    def session(self, name: str, text: str = TWO, covers=(("boot", 1),), **inst) -> str:
        d = self.sessions / name
        d.mkdir()
        (d / "session.json").write_text(json.dumps({"session_id": f"id-{name}", "object": "issue",
                                                    "config": {"covers": [{"repo": r, "number": n} for r, n in covers]}}))
        i = Instance.new(text, 0.0)
        for k, v in inst.items():
            setattr(i, k, v)
        (d / FILE).write_text(json.dumps(i.to_json()))
        return name

    def state(self, name):
        return self.machines.load(name)[1].state

    def evaluations(self, name):
        return self.machines.log.history(f"id-{name}")["evaluations"]

    def moves(self, name):
        return self.machines.log.history(f"id-{name}")["moves"]


def run(coro):
    return asyncio.run(coro)


async def settle(w: World, *signals):
    out = [w.runner.signal(*s) if isinstance(s, tuple) else s() for s in signals]
    await w.runner.idle()
    return out


# ---- the hook -----------------------------------------------------------------------------------

def _listen(path: Path, hold: bool = False):
    got, ready = [], threading.Event()
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(path))
    server.listen(1)

    def serve():
        ready.set()
        conn, _ = server.accept()
        with conn:
            got.append(conn.makefile("rb").readline())
            if hold:
                time.sleep(3)  # never answers
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    ready.wait()
    return got, thread, server


def _hook(tmp, path, event):
    token = tmp / "tool-token"
    token.write_text("tok\n")
    start = time.monotonic()
    proc = subprocess.run([sys.executable, "-I", str(HOOK), str(path), str(token)], input=json.dumps(event).encode(),
                          capture_output=True, timeout=20)
    return proc, time.monotonic() - start


def test_the_hook_posts_the_event_and_nothing_of_the_tool(tmp_path):
    path = tmp_path / "s.sock"
    got, thread, server = _listen(path, hold=True)
    proc, took = _hook(tmp_path, path, {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "secret"},
                                        "tool_response": "words"})
    thread.join(5)
    server.close()
    assert proc.returncode == 0 and proc.stdout == b"" and took < 2.5  # it didn't wait for an answer that never came
    assert json.loads(got[0]) == {"op": "session.signal", "agent_token": "tok", "how": "PostToolUse"}


def test_the_hook_is_silent_when_hubd_is_down(tmp_path):
    proc, _ = _hook(tmp_path, tmp_path / "nothing.sock", {"hook_event_name": "Stop"})
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, b"", b"")
    token = tmp_path / "tool-token"
    proc = subprocess.run([sys.executable, "-I", str(HOOK), str(tmp_path / "x.sock"), str(token)], input=b"not json", capture_output=True, timeout=20)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, b"", b"")


def _agents(tmp):
    return Agents(LIBRARY, None, tmp / "state", socket=tmp / "hubd.sock")


def _machine_entries(settings):
    return {event: [h for h in entries for x in h["hooks"] if "machine_hook.py" in x["command"]]
            for event, entries in settings["hooks"].items()}


def test_the_hook_is_installed_only_for_the_signals_a_workflow_names(tmp_path):
    a = _agents(tmp_path)
    action = LIBRARY.actions["issue-implement"]
    config = a.defaults("issue-implement", "boot", 5)
    directory = a.sessions / "x"
    plain = a._hooks(directory, config, action)
    assert not any(_machine_entries(plain).values())
    two = a._hooks(directory, config, {**action, "definition": TWO})
    entries = _machine_entries(two)
    assert {e for e, found in entries.items() if found} == {"Stop"}
    assert len(two["hooks"]["Stop"]) == len(plain["hooks"]["Stop"]) + 1  # added to what was there
    every = workflow('to = "b"\ndecided_by = "judge"\nwhen = "x"\non = ["turn.end", "session.end", "tool.after", "compact.before"]')
    found = _machine_entries(a._hooks(directory, config, {**action, "definition": every}))
    assert {e for e, f in found.items() if f} == {"Stop", "SessionEnd", "PostToolUse", "PreCompact"}
    command = found["Stop"][0]["hooks"][0]["command"]
    assert str(tmp_path / "hubd.sock") in command and str(directory / "tool-token") in command


def test_a_resumed_session_on_a_workflow_with_steps_gets_the_hook(tmp_path):
    a = _agents(tmp_path)
    action = LIBRARY.actions["issue-implement"]
    directory = a.sessions / "x"
    directory.mkdir(parents=True)
    (directory / FILE).write_text(json.dumps(Instance.new(TWO, 0).to_json()))
    assert _machine_entries(a._hooks(directory, a.defaults("issue-implement", "boot", 5), action))["Stop"]


def test_no_socket_no_hook(tmp_path):
    a = Agents(LIBRARY, None, tmp_path / "state")
    action = LIBRARY.actions["issue-implement"]
    assert a._machine_hooks(a.sessions / "x", {**action, "definition": TWO}) == {}


# ---- routing ------------------------------------------------------------------------------------

def test_a_feed_change_reaches_the_sessions_on_that_item(tmp_path):
    w = World(tmp_path)
    w.session("on-it", covers=[("boot", 1)])
    w.session("elsewhere", covers=[("boot", 2)])
    w.session("other-repo", covers=[("hub", 1)])
    w.session("not-listening", text=workflow('to = "b"\ndecided_by = "facts"\nrequires = ["pr.open"]\non = ["feed:pr.review"]'))

    async def go():
        routed = w.runner.feed([{"kind": "pr", "what": "checks", "repo": "Boot", "number": 1}, {"kind": "pr", "what": "bogus", "repo": "boot", "number": 1}])
        await w.runner.idle()
        return routed
    assert run(go()) == ["on-it"]
    assert [e["signal"] for e in w.evaluations("on-it")] == ["feed:pr.checks"]
    assert w.evaluations("elsewhere") == w.evaluations("not-listening") == []


def test_a_session_signal_reaches_only_its_session_and_only_a_named_one(tmp_path):
    w = World(tmp_path)
    w.session("s")
    w.session("t")

    async def go():
        return [w.runner.hook("s", "Stop"), w.runner.hook("s", "Notification"), w.runner.signal("turn.end", None), w.runner.signal("no.such", "s")]
    assert run(go()) == [["s"], [], [], []]


def test_a_signal_with_no_event_loop_is_dropped_quietly(tmp_path):
    w = World(tmp_path)
    w.session("s")
    assert w.runner.signal("turn.end", "s") == []


def test_the_hub_index_covers_items_and_known_pull_requests(tmp_path):
    class FakeAgents:
        sessions = tmp_path / "sessions"
        machines = None

        def known_prs(self, name):
            return [{"repo": "boot", "number": 9, "state": "OPEN"}] if name == "s" else None
    w = World(tmp_path)
    w.session("s", covers=[("boot", 1)])
    FakeAgents.machines = w.machines
    r = machinerun.for_hub(FakeAgents(), None, lambda: {})
    assert r.index() == {("boot", 1): {"s"}, ("boot", 9): {"s"}}


# ---- debounce and one at a time -----------------------------------------------------------------

def test_signals_in_the_window_share_one_pass(tmp_path):
    async def go():
        gate = asyncio.Event()

        async def sleep(_s):
            await gate.wait()
        w = World(tmp_path, sleep=sleep, facts={})
        w.session("s", text=workflow('to = "b"\ndecided_by = "facts"\nrequires = ["pr.open"]\non = ["turn.end", "feed:pr.checks"]'))
        w.runner.signal("turn.end", "s")
        w.runner.signal("turn.end", "s")
        w.runner.signal("feed:pr.checks", None, {"repo": "boot", "number": 1})
        await asyncio.sleep(0)
        assert w.evaluations("s") == []
        gate.set()
        await w.runner.idle()
        return w
    w = run(go())
    assert [e["signal"] for e in w.evaluations("s")] == ["turn.end, feed:pr.checks"]


def test_a_signal_during_a_pass_gets_one_more_pass_not_two_at_once(tmp_path):
    async def go():
        gate = asyncio.Event()
        judge = Fake(answer={"exit": None, "evidence": "", "confidence": 0.1}, gate=gate)
        w = World(tmp_path, judge=judge)
        w.session("s", text=JUDGED)
        w.runner.signal("turn.end", "s")
        while not judge.asked:
            await asyncio.sleep(0)
        for _ in range(3):  # all during the first pass
            w.runner.signal("turn.end", "s")
        await asyncio.sleep(0)
        assert len(judge.asked) == 1
        gate.set()
        await w.runner.idle()
        return w, judge
    w, judge = run(go())
    assert len(judge.asked) == 2 and len(w.evaluations("s")) == 2


def test_evaluations_of_one_instance_never_overlap(tmp_path):
    async def go():
        gate = asyncio.Event()
        judge = Fake(answer={"exit": None, "evidence": "", "confidence": 0.1}, gate=gate)
        w = World(tmp_path, judge=judge)
        w.session("s", text=JUDGED)
        first = asyncio.ensure_future(w.runner.evaluate("s", ["turn.end"]))
        second = asyncio.ensure_future(w.runner.evaluate("s", ["turn.end"]))
        for _ in range(5):
            await asyncio.sleep(0)
        assert len(judge.asked) == 1
        gate.set()
        await asyncio.gather(first, second)
        return judge
    assert len(run(go()).asked) == 2


# ---- facts --------------------------------------------------------------------------------------

_ids = itertools.count(1)
HEAD = "a" * 40


def ev(**over):
    return {"id": f"{'d' * 16}-{next(_ids)}", "kind": "pr", "repo": "boot", "number": 7, "what": "checks", "at": "2026-11-05T15:02:00Z",
            "old": "", "new": "passing", "old_head": "", "new_head": "", "actor": None, **over}


@pytest.mark.parametrize("checks, want", [("passing", "pass"), ("failing", "fail"), ("pending", "pending"), ("none", None)])
def test_feed_checks_map_to_the_words_requires_uses(checks, want):
    assert pr_facts("OPEN", {"checks": checks}, False).get("pr.checks") == want


@pytest.mark.parametrize("review, want", [("APPROVED", "approved"), ("CHANGES_REQUESTED", "changes_requested"), ("REVIEW_REQUIRED", "none")])
def test_feed_reviews_map_to_the_words_requires_uses(review, want):
    assert pr_facts(None, {"review": review}, False) == {"pr.review": want, "pr.reviewed": True}


def test_hub_facts_come_from_the_lookup_and_the_feed(tmp_path):
    feed = Feed(":memory:")

    class FakeAgents:
        prs = None

        def known_prs(self, _name):
            return self.prs
    agents = FakeAgents()
    facts = HubFacts(agents, feed)
    assert facts("s", {"object": "issue"}) == {"issue.linked": True}  # never looked up: no pr fact at all
    agents.prs = []
    assert facts("s", {"object": "pr"}) == {"pr.open": False, "pr.merged": False}
    agents.prs = [{"repo": "boot", "number": 3, "state": "CLOSED"}, {"repo": "Boot", "number": 7, "state": "OPEN"}]
    assert facts("s", {"object": "issue"}) == {"issue.linked": True, "pr.open": True, "pr.merged": False, "branch.pushed": True}
    feed.record([ev(new="failing"), ev(what="review", new="APPROVED")])
    assert facts("s", {"object": "issue"})["pr.checks"] == "fail"
    feed.record([ev(what="head", old="", new="", old_head=HEAD, new_head="b" * 40)])
    got = facts("s", {"object": "issue"})
    assert "pr.checks" not in got and "pr.review" not in got  # from before the newest head: not known for this one
    feed.record([ev(new="passing"), ev(what="state", old="OPEN", new="MERGED")])
    got = facts("s", {"object": "issue"})
    assert (got["pr.checks"], got["pr.open"], got["pr.merged"]) == ("pass", False, True)


def test_a_pull_request_session_has_no_branch_fact():
    class FakeAgents:
        def known_prs(self, _name):
            return [{"repo": "boot", "number": 7, "state": None}]
    assert HubFacts(FakeAgents(), None)("s", {"object": "pr"}) == {}


def test_an_unknown_fact_holds_neither_way():
    assert not check("pr.open", {})["holds"] and not check("not pr.open", {})["holds"]
    got = check("pr.checks == pass or rounds.a > 2", {"pr.checks": "fail", "rounds.a": 3})
    assert got["holds"] and [t["value"] for t in got["terms"]] == ["fail", 3]


def test_known_prs_says_when_it_has_not_looked(tmp_path):
    a = _agents(tmp_path)
    d = a.sessions / "s"
    d.mkdir(parents=True)
    (d / "session.json").write_text(json.dumps({"session_id": "x", "object": "issue", "config": {}}))
    assert a.known_prs("s") is None
    a._prs["s"] = (0.0, [{"repo": "boot", "number": 2, "state": "OPEN"}], "x")
    assert a.known_prs("s") == [{"repo": "boot", "number": 2, "state": "OPEN"}]
    a._prs["s"] = (0.0, [], "an earlier conversation")
    assert a.known_prs("s") is None


# ---- each way an exit is decided ----------------------------------------------------------------

def test_facts_move_when_requires_hold_and_not_otherwise(tmp_path):
    w = World(tmp_path)
    w.session("s")
    run(settle(w, ("turn.end", "s")))
    assert w.state("s") == "a"
    row = w.evaluations("s")[-1]
    assert not row["failed"] and row["judge"] is None
    assert row["checks"]["exits"][0]["checks"][0]["terms"][0] == {"fact": "pr.open", "op": "==", "want": True, "value": None, "holds": False}
    w.facts["s"] = {"pr.open": True}
    run(settle(w, ("turn.end", "s")))
    assert w.state("s") == "b"
    assert [(m["from"], m["to"], m["by"]) for m in w.moves("s")] == [("a", "b", "machine")]
    assert w.evaluations("s")[-1]["checks"]["move"] == {"moved": True, "to": "b"}


def test_a_counter_exit_moves_on_its_count(tmp_path):
    w = World(tmp_path)
    w.session("s", text=workflow('to = "c"\ndecided_by = "counter"\nrequires = ["rounds.a >= 1"]\non = ["hub:decision"]'))
    run(settle(w, ("hub:decision", "s")))
    assert w.state("s") == "c"


def test_hand_and_on_request_exits_are_never_tried(tmp_path):
    w = World(tmp_path)
    w.session("s", text=workflow('to = "b"\ndecided_by = "hand"\non = ["turn.end"]',
                                 'to = "c"\ndecided_by = "facts"\nrequires = ["rounds.a >= 1"]\nmove = "on-request"\non = ["turn.end"]',
                                 'to = "d"\ndecided_by = "counter"\nrequires = ["rounds.a >= 9"]\non = ["hub:decision"]'))
    w.facts["s"] = {"pr.open": True}
    assert run(settle(w, ("turn.end", "s"))) == [[]]
    assert w.evaluations("s") == [] and w.state("s") == "a" and w.judge.asked == []


def test_the_first_exit_that_holds_moves(tmp_path):
    w = World(tmp_path)
    w.session("s", text=workflow('to = "b"\ndecided_by = "facts"\nrequires = ["pr.merged"]\non = ["turn.end"]',
                                 'to = "c"\ndecided_by = "facts"\nrequires = ["pr.open"]\non = ["turn.end"]',
                                 'to = "d"\ndecided_by = "counter"\nrequires = ["rounds.a >= 1"]\non = ["turn.end"]'))
    w.facts["s"] = {"pr.open": True, "pr.merged": False}
    run(settle(w, ("turn.end", "s")))
    assert w.state("s") == "c"
    assert [r["to"] for r in w.evaluations("s")[0]["checks"]["exits"]] == ["b", "c"]


def test_a_parents_exit_applies_in_its_states(tmp_path):
    text = '''schema = 1
name = "p"
initial = "work"
[state.work]
initial = "a"
[[state.work.exit]]
to = "done"
decided_by = "facts"
requires = ["pr.merged"]
on = ["feed:pr.state"]
[state.a]
parent = "work"
[[state.a.exit]]
to = "done"
decided_by = "counter"
requires = ["rounds.a > 5"]
on = ["turn.end"]
[state.done]
final = true
'''
    w = World(tmp_path)
    w.session("s", text=text)
    w.facts["s"] = {"pr.merged": True}
    assert run(settle(w, ("feed:pr.state", None, {"repo": "boot", "number": 1}))) == [["s"]]
    assert w.state("s") == "done"


def test_a_judge_exit_moves_when_picked_and_its_requires_hold(tmp_path):
    w = World(tmp_path)
    w.session("s", text=JUDGED)
    w.facts["s"] = {"pr.open": True}
    run(settle(w, ("turn.end", "s")))
    assert w.state("s") == "b"
    row = w.evaluations("s")[-1]
    assert row["proposal"] == "exit 0 to b" and row["evidence"] == "The change is complete" and row["judge"].startswith("default")
    assert row["cost"] == pytest.approx(0.003) and row["ms"] is not None
    assert summary.read(w.sessions / "s") == "Working on it."
    assert "Working on it." in w.judge.asked[0] and "The change is complete and pushed." in w.judge.asked[0]


def test_the_judge_picks_but_a_failed_requirement_stops_the_move(tmp_path):
    w = World(tmp_path)
    w.session("s", text=JUDGED)
    w.facts["s"] = {"pr.open": False}
    run(settle(w, ("turn.end", "s")))
    assert w.state("s") == "a" and w.moves("s") == []
    row = w.evaluations("s")[-1]
    assert row["proposal"] == "exit 0 to b" and row["evidence"] and not row["failed"]
    exit_ = row["checks"]["exits"][0]
    assert exit_["picked"] and not exit_["holds"] and exit_["checks"][0]["terms"][0]["value"] is False


def test_a_failed_verdict_moves_nothing_and_is_logged(tmp_path):
    w = World(tmp_path, judge=Fake(answer=judgelib.JudgeFault("couldn't reach the endpoint")))
    w.session("s", text=workflow('to = "b"\ndecided_by = "judge"\nwhen = "x"\non = ["turn.end"]',
                                 'to = "c"\ndecided_by = "counter"\nrequires = ["rounds.a >= 1"]\non = ["turn.end"]'))
    run(settle(w, ("turn.end", "s")))
    assert w.state("s") == "a"
    row = w.evaluations("s")[-1]
    assert row["failed"] and row["proposal"] is None


def test_an_out_of_form_answer_fails(tmp_path):
    w = World(tmp_path, judge=Fake(answer={"exit": 0}))
    w.session("s", text=JUDGED)
    w.facts["s"] = {"pr.open": True}
    run(settle(w, ("turn.end", "s")))
    assert w.state("s") == "a" and w.evaluations("s")[-1]["failed"]


def test_a_judge_table_that_cant_be_read_fails_the_evaluation(tmp_path):
    w = World(tmp_path)
    w.runner._judges = lambda: (_ for _ in ()).throw(judgelib.ConfigError(["judge.x: bad"]))
    w.session("s", text=JUDGED)
    run(settle(w, ("turn.end", "s")))
    assert w.evaluations("s")[-1]["failed"] and w.judge.asked == []


def test_facts_before_a_judge_exit_move_without_asking_it(tmp_path):
    w = World(tmp_path)
    w.session("s", text=workflow('to = "c"\ndecided_by = "counter"\nrequires = ["rounds.a >= 1"]\non = ["turn.end"]',
                                 'to = "b"\ndecided_by = "judge"\nwhen = "x"\non = ["turn.end"]'))
    run(settle(w, ("turn.end", "s")))
    assert w.state("s") == "c" and w.judge.asked == []


def test_the_same_turn_is_folded_once(tmp_path):
    w = World(tmp_path, judge=Fake(answer={"exit": None, "evidence": "", "confidence": 0.1}))
    w.session("s", text=JUDGED)
    run(settle(w, ("turn.end", "s")))
    run(settle(w, ("turn.end", "s")))
    assert w.judge.folds == 1 and len(w.judge.asked) == 2


def test_an_exit_that_needs_approval_waits_and_says_so(tmp_path):
    w = World(tmp_path)
    w.session("s", text=workflow('to = "b"\ndecided_by = "counter"\nrequires = ["rounds.a >= 1"]\napprove = "me"\non = ["turn.end"]',
                                 'to = "c"\ndecided_by = "counter"\nrequires = ["rounds.a >= 0"]\non = ["turn.end"]'))
    run(settle(w, ("turn.end", "s")))
    assert w.state("s") == "a" and w.moves("s") == []
    assert w.evaluations("s")[-1]["checks"]["blocked"] == "approve me"


def test_a_paused_machine_is_not_evaluated(tmp_path):
    w = World(tmp_path)
    w.session("s", paused=True)
    w.facts["s"] = {"pr.open": True}
    assert run(settle(w, ("turn.end", "s"))) == [[]]
    assert w.evaluations("s") == [] and w.state("s") == "a"
    assert run(w.runner.evaluate("s", ["turn.end"])) == {"skipped": "paused"}


def test_a_move_waiting_for_a_confirm_is_left_alone(tmp_path):
    w = World(tmp_path)
    w.session("s", pending={"id": "x", "to_version": instances_version(TWO)})
    assert run(settle(w, ("turn.end", "s"))) == [[]]


def instances_version(text):
    from hubd.instances import version_of
    return version_of(text)


def test_a_hand_move_during_the_judgement_wins(tmp_path):
    async def go():
        gate = asyncio.Event()
        w = World(tmp_path, judge=Fake(gate=gate))
        w.session("s", text=workflow('to = "b"\ndecided_by = "judge"\nwhen = "The change is complete"\nrequires = ["pr.open"]\non = ["turn.end"]',
                                     'to = "c"\ndecided_by = "hand"'))
        w.facts["s"] = {"pr.open": True}
        task = asyncio.ensure_future(w.runner.evaluate("s", ["turn.end"]))
        while not w.judge.asked:
            await asyncio.sleep(0)
        w.machines.move("s", "c", by="hand", who="m")
        gate.set()
        return w, await task
    w, result = run(go())
    assert w.state("s") == "c" and result["move"]["stale"]


def test_a_two_state_workflow_moves_end_to_end_on_a_hook_signal(tmp_path):
    w = World(tmp_path)
    w.session("s")
    w.facts["s"] = {"pr.open": True}
    assert run(settle(w, lambda: w.runner.hook("s", "Stop"))) == [["s"]]
    assert w.state("s") == "b"
    assert [(m["from"], m["to"], m["by"]) for m in w.moves("s")] == [("a", "b", "machine")]
    assert run(settle(w, lambda: w.runner.hook("s", "Stop"))) == [[]]  # b is final: nothing listens


def test_no_judge_call_without_a_matching_signal(tmp_path):
    w = World(tmp_path)
    w.session("s", text=JUDGED, covers=[("boot", 1)])
    w.facts["s"] = {"pr.open": True}
    run(settle(w, ("tool.after", "s"), ("session.end", "s"), ("hub:decision", "s"),
               ("feed:pr.checks", None, {"repo": "boot", "number": 1})))
    assert w.judge.asked == [] and w.judge.folds == 0 and w.evaluations("s") == []
    run(settle(w, ("turn.end", "s")))
    assert len(w.judge.asked) == 1


def test_the_tried_exits_keep_their_places():
    d = machine.parse(workflow('to = "b"\ndecided_by = "hand"\non = ["turn.end"]', 'to = "c"\ndecided_by = "counter"\nrequires = ["rounds.a > 1"]\non = ["turn.end"]'))
    assert [(i, e.to) for i, e in tried(d, "a", ["turn.end"])] == [(1, "c")]
    assert machinerun.wanted(d) == {"turn.end"}


# ---- hubd -----------------------------------------------------------------------------------------

class Recorder:
    def __init__(self):
        self.got = []

    def hook(self, session, how):
        self.got.append(("hook", session, how))

    def feed(self, rows):
        self.got.append(("feed", [(r["repo"], r["number"], r["what"]) for r in rows]))

    def signal(self, name, session=None, payload=None):
        self.got.append(("signal", name, session))


class ScopeAgents:
    def session_id_of(self, _name):
        return "conv"

    def scope(self, token):
        return {"session": "s"} if token == "session-token" else {"session": None} if token == "shared" else None


def _hubd(**over):
    return Hubd(None, None, auth.Sessions(), "shared", agents=ScopeAgents(), **over)


def test_hubd_takes_a_signal_only_from_a_sessions_token():
    r = Recorder()
    h = _hubd(machine_run=r)
    assert run(h.request({"op": "session.signal", "agent_token": "session-token", "how": "Stop"})) == {"ok": True}
    assert run(h.request({"op": "session.signal", "agent_token": "shared", "how": "Stop"}))["refused"]
    assert run(h.request({"op": "session.signal", "agent_token": "nope", "how": "Stop"}))["refused"]
    assert r.got == [("hook", "s", "Stop")]


def test_hubd_signals_only_what_the_feed_stored_now():
    r = Recorder()
    feed = Feed(":memory:")
    h = _hubd(machine_run=r, change_feed=feed)
    one = ev(number=4)
    assert run(h.request({"op": "feed.record", "events": [one, ev(number=5, what="review", new="APPROVED")]}))["kept"] == 2
    assert run(h.request({"op": "feed.record", "events": [one]}))["kept"] == 0
    assert r.got == [("feed", [("boot", 4, "checks"), ("boot", 5, "review")])]


def test_hubd_signals_a_decision_answered_for_a_session(tmp_path):
    from hubd import decisions
    r = Recorder()
    store = decisions.Decisions(tmp_path / "d")
    store.session_id_of = lambda _name: "conv"
    h = _hubd(machine_run=r, decision_store=store)
    token = h.sessions.create()
    asked = store.request("go", {"actions": ["flash"], "device": "any", "session": "s"}, "why", "s")
    assert run(h.request({"op": "decision.approve", "token": token, "id": asked["id"]}))["ok"]
    anyone = store.request("go", {"actions": ["flash"], "device": "any"}, "why", "s")
    assert run(h.request({"op": "decision.deny", "token": token, "id": anyone["id"]}))["ok"]
    assert r.got == [("signal", "hub:decision", "s")]


# ---- moves on the session's request, and approvals -------------------------------------------------

ON_REQUEST = workflow('to = "b"\ndecided_by = "facts"\nrequires = ["pr.open", "pr.checks == pass"]\nmove = "on-request"',
                      'to = "c"\ndecided_by = "hand"',
                      'to = "d"\ndecided_by = "facts"\nrequires = ["pr.open"]\nmove = "on-request"\napprove = "owner"')


def test_a_request_moves_only_by_an_on_request_exit_whose_requires_hold(tmp_path):
    w = World(tmp_path)
    w.session("s", text=ON_REQUEST)
    got = run(w.runner.request("s", "id-s", "b"))
    assert not got["moved"] and "pr.open, pr.checks" in got["why"] and w.state("s") == "a"
    row = w.evaluations("s")[-1]
    assert row["signal"] == "request" and row["checks"]["exits"][0]["holds"] is False and row["judge"] is None
    w.facts["s"] = {"pr.open": True, "pr.checks": "fail"}
    assert "pr.checks" in run(w.runner.request("s", "id-s", "b"))["why"]
    for to in ("c", "nowhere", None):  # by hand only, or no such exit
        got = run(w.runner.request("s", "id-s", to))
        assert not got["moved"] and "moves on request" in got["why"] and "b, d" in got["why"]
    w.facts["s"] = {"pr.open": True, "pr.checks": "pass"}
    assert run(w.runner.request("s", "an earlier conversation", "b"))["why"] == "that isn't this session's conversation"
    got = run(w.runner.request("s", "id-s", "b"))
    assert got["moved"] and got["to"] == "b" and w.state("s") == "b"
    assert [(m["from"], m["to"], m["by"]) for m in w.moves("s")] == [("a", "b", "machine")]


def test_a_request_or_a_pass_that_needs_approval_asks_and_waits(tmp_path):
    w = World(tmp_path)
    asked = []
    w.runner.on_blocked = lambda name, wait: asked.append((name, wait))
    w.session("s", text=ON_REQUEST)
    w.facts["s"] = {"pr.open": True}
    got = run(w.runner.request("s", "id-s", "d"))
    assert not got["moved"] and got["waits"] == "approve owner" and w.state("s") == "a"
    (name, wait), = asked
    assert name == "s" and {k: wait[k] for k in ("state", "exit", "to", "approve", "session_id")} == {
        "state": "a", "exit": 2, "to": "d", "approve": "owner", "session_id": "id-s"}
    assert wait["checks"][0]["holds"] and w.evaluations("s")[-1]["checks"]["blocked"] == "approve owner"
    # an automatic exit that waits for an approval asks too
    w.session("t", text=workflow('to = "b"\ndecided_by = "counter"\nrequires = ["rounds.a >= 1"]\napprove = "me"\non = ["turn.end"]'))
    run(settle(w, ("turn.end", "t")))
    assert asked[-1][0] == "t" and asked[-1][1]["approve"] == "me"


def test_an_approved_move_happens_only_if_nothing_changed_meanwhile(tmp_path):
    w = World(tmp_path)
    w.session("s", text=ON_REQUEST)
    w.facts["s"] = {"pr.open": True}
    wait = {"session_id": "id-s", "state": "a", "version": w.machines.load("s")[1].version, "exit": 2, "to": "d"}
    for changed, why in (({"session_id": "other"}, "has gone"), ({"state": "b"}, "has moved"), ({"exit": 0}, "isn't there"),
                         ({"exit": 9}, "isn't there")):
        with pytest.raises(machinerun.MachineError, match=why):
            run(w.runner.approved("s", {**wait, **changed}, "me"))
    w.facts["s"] = {"pr.open": False}
    with pytest.raises(machinerun.MachineError, match="don't hold any more: pr.open"):
        run(w.runner.approved("s", wait, "me"))
    w.facts["s"] = {"pr.open": True}
    assert run(w.runner.approved("s", wait, "me"))["moved"] and w.state("s") == "d"
    assert [(m["to"], m["by"], m["who"]) for m in w.moves("s")] == [("d", "machine", "me")]
    assert w.evaluations("s")[-1]["signal"] == "hub:approved"


def test_hubd_takes_a_move_request_only_from_the_sessions_own_conversation():
    class Runner:
        def __init__(self):
            self.got = []

        async def request(self, name, session_id, to):
            self.got.append((name, session_id, to))
            return {"moved": True}

    class Scopes(ScopeAgents):
        conversation = "conv"

        def session_id_of(self, _name):
            return self.conversation

        def scope(self, token):
            return {"session": "s", "instance": "conv", "tools": ["request_move"]} if token == "session-token" else \
                {"session": "s", "instance": "conv", "tools": []} if token == "no-tool" else super().scope(token)
    r, agents = Runner(), Scopes()
    h = Hubd(None, None, auth.Sessions(), "shared", agents=agents, machine_run=r)
    ask = lambda token: run(h.request({"op": "session.request_move", "agent_token": token, "to": "b", "name": "other"}))  # noqa: E731
    assert ask("session-token") == {"ok": True, "moved": True}
    for token in ("shared", "nope", "no-tool"):
        assert ask(token)["refused"]
    agents.conversation = "a later one"
    assert "earlier conversation" in ask("session-token")["error"]
    assert r.got == [("s", "conv", "b")]  # its own session, never the name it sent


def test_a_hand_move_while_an_approval_looks_its_facts_up_wins(tmp_path):
    async def go():
        gate = asyncio.Event()
        w = World(tmp_path)

        async def slow(_name):
            await gate.wait()
        w.runner._refresh = slow
        w.session("s", text=ON_REQUEST)
        w.facts["s"] = {"pr.open": True}
        wait = {"session_id": "id-s", "state": "a", "version": w.machines.load("s")[1].version, "exit": 2, "to": "d"}
        task = asyncio.ensure_future(w.runner.approved("s", wait, "me"))
        await asyncio.sleep(0)
        w.machines.move("s", "c", by="hand", who="m")
        gate.set()
        with pytest.raises(machinerun.MachineError, match="has moved"):
            await task
        return w
    w = run(go())
    assert w.state("s") == "c" and [m["to"] for m in w.moves("s")] == ["c"]


def test_a_push_since_the_review_is_a_fact():
    assert "pr.reviewed" not in pr_facts("OPEN", {}, False)  # the feed hasn't seen it: unknown
    assert pr_facts("OPEN", {"review": "CHANGES_REQUESTED", "checks": "passing"}, False)["pr.reviewed"] is True
    assert pr_facts("OPEN", {"head": True, "checks": "passing"}, False)["pr.reviewed"] is False


def test_while_an_approval_card_is_up_nothing_is_evaluated(tmp_path):
    w = World(tmp_path)
    open_cards = set()
    w.runner.on_blocked = lambda name, wait: open_cards.add((name, wait["session_id"], wait["state"], wait["version"]))
    w.runner.approval_open = lambda *key: key in open_cards
    w.session("s", text=JUDGED.replace('on = ["turn.end"]', 'approve = "me"\non = ["turn.end"]'))
    w.facts["s"] = {"pr.open": True}
    run(settle(w, ("turn.end", "s")))
    assert len(w.judge.asked) == 1 and open_cards and w.state("s") == "a"
    assert run(settle(w, ("turn.end", "s"))) == [[]]  # not even routed: no judge call
    assert run(w.runner.evaluate("s", ["turn.end"])) == {"skipped": "a move waits for an approval"}
    assert len(w.judge.asked) == 1
    open_cards.clear()  # said no: it is tried again
    w.judge.answer = {"exit": None, "evidence": "", "confidence": 0.5}
    run(settle(w, ("turn.end", "s")))
    assert len(w.judge.asked) == 2
