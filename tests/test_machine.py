# SPDX-License-Identifier: GPL-2.0-or-later
"""Workflow definitions: parse, emit, checks, grants, exits, requires and the outline diff."""
import dataclasses
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hubd import feed, machine  # noqa: E402
from hubd.machine import (Change, DefinitionError, Exit, Grant, Requirement, Term, check, compare, effective,  # noqa: E402
                          emit, exits_of, outline_diff, parse, parse_requires)

IMPLEMENT = '''
schema = 1
name = "implement"
initial = "work"
judge = "default"

[state.work]
personas = ["implementor"]
initial = "implement"
[state.work.grant]
access = "locked"
tools = ["Read", "Grep"]
hub_tools = ["get_pr", "docs_search"]
checkout = "pr-branch"
github = ["pr.read", "issues.comment"]
[[state.work.exit]]
to = "escalated"
decided_by = "judge"
when = "The session seems stuck"
requires = ["time.work > 7200 or tokens.work > 600000"]
on = ["turn.end"]

[state.implement]
parent = "work"
instructions = "Implement the issue on your branch."
[state.implement.grant]
permission_mode = "acceptEdits"
tools = ["Edit", "Bash"]
github = ["push"]
[[state.implement.exit]]
to = "review"
decided_by = "judge"
when = "The change is complete"
requires = ["pr.open", "branch.pushed"]
on = ["turn.end", "feed:pr.checks"]

[state.review]
parent = "work"
context = "compact"
[state.review.grant]
permission_mode = "plan"
[[state.review.exit]]
to = "fix"
decided_by = "facts"
requires = ["managed.reviewer.verdict == fail", "rounds.review < 3"]
on = ["hub:managed.return"]
[[state.review.exit]]
to = "merge-ready"
decided_by = "facts"
requires = ["managed.reviewer.verdict == pass", "pr.checks == pass"]
on = ["hub:managed.return", "feed:pr.checks"]
[[state.review.exit]]
to = "escalated"
decided_by = "counter"
requires = ["rounds.review >= 3"]
on = ["hub:managed.return"]
[[state.review.manages]]
name = "reviewer"
persona = "reviewer"
workflow = "pr-review"
reuse = "fresh"
with = ["pr", "diff.since_last_round", "owner.summary"]
returns = { verdict = ["pass", "fail"] }

[state.fix]
parent = "work"
[state.fix.grant]
permission_mode = "acceptEdits"
github = ["push"]
[[state.fix.exit]]
to = "review"
decided_by = "judge"
when = "Every finding has a fixup commit or a reply"
requires = ["pr.checks == pass"]
on = ["turn.end"]

[state.merge-ready]
[state.merge-ready.grant]
github = ["merge"]
[[state.merge-ready.exit]]
to = "merged"
decided_by = "facts"
requires = ["pr.merged"]
on = ["feed:pr.state"]
approve = "me"

[state.escalated]
[[state.escalated.exit]]
to = "work"
enter = "history"
decided_by = "facts"
requires = ["report.answered"]
on = ["hub:decision"]

[state.merged]
final = true
'''

ONE = '''
schema = 1
name = "pr-session"
initial = "session"
[state.session]
personas = ["engineer"]
final = true
[state.session.grant]
access = "full"
permission_mode = "auto"
checkout = false
all_repos = true
asks_first = ["merge_pr"]
'''


def _with(text: str, old: str, new: str) -> str:
    assert old in text
    return text.replace(old, new, 1)


def _problems(text: str) -> list[str]:
    return [f.where + ": " + f.text for f in check(parse(text)) if f.kind == "problem"]


@pytest.fixture
def impl():
    return parse(IMPLEMENT)


def _variants():
    d = parse(IMPLEMENT)
    tricky = "line\n[state.x.grant]\naccess = \"full\"\t\\ \x01 é \U0001f600"
    st = d.states["implement"]
    yield d
    yield parse(ONE)
    yield dataclasses.replace(d, judge=None, states={**d.states, "implement": dataclasses.replace(st, instructions=tricky)})
    yield dataclasses.replace(d, states={**d.states, "fix": dataclasses.replace(d.states["fix"], grant=Grant())})


@pytest.mark.parametrize("d", list(_variants()))
def test_emit_round_trips(d):
    text = emit(d)
    assert parse(text) == d
    assert emit(parse(text)) == text


def test_emit_keeps_injected_text_as_text():
    d = list(_variants())[2]
    assert "\n[state.x.grant]" not in emit(d)
    assert parse(emit(d)).states["implement"].grant.access is None


def test_parse_reads_the_example(impl):
    assert impl.initial == "work" and impl.judge == "default"
    assert impl.states["implement"].parent == "work"
    assert impl.states["review"].manages[0].returns == {"verdict": ("pass", "fail")}
    assert impl.states["review"].manages[0].with_ == ("pr", "diff.since_last_round", "owner.summary")
    assert impl.states["escalated"].exits[0].enter == "history"
    assert parse(ONE).states["session"].grant.checkout is False


@pytest.mark.parametrize("old,new,where", [
    ('name = "implement"', 'name = "implement"\ncolour = "red"', "workflow"),
    ('schema = 1', 'schema = true', "workflow.schema"),
    ('schema = 1', 'schema = 2', "workflow.schema"),
    ('initial = "work"\n', '', "workflow.initial"),
    ('initial = "work"\n', 'initial = "nowhere"\n', "workflow.initial"),
    ('judge = "default"', 'judge = "https://example.com/v1"', "workflow.judge"),
    ('[state.implement]\nparent = "work"', '[state.implement]\nparent = "nope"', "state.implement.parent"),
    ('to = "merged"', 'to = "gone"', "state.merge-ready.exit.1.to"),
    ('to = "merged"', 'to = 3', "state.merge-ready.exit.1.to"),
    ('approve = "me"', 'approve = "anyone"', "state.merge-ready.exit.1.approve"),
    ('on = ["hub:decision"]', 'on = ["whenever"]', "state.escalated.exit.1.on"),
    ('on = ["hub:decision"]', 'on = ["feed:issue.checks"]', "state.escalated.exit.1.on"),
    ('decided_by = "counter"\n', '', "state.review.exit.3.decided_by"),
    ('context = "compact"', 'context = "forget"', "state.review.context"),
    ('final = true', 'final = "yes"', "state.merged.final"),
    ('access = "locked"', 'access = "root"', "state.work.grant.access"),
    ('permission_mode = "plan"', 'permission_mode = "yolo"', "state.review.grant.permission_mode"),
    ('checkout = "pr-branch"', 'checkout = true', "state.work.grant.checkout"),
    ('github = ["merge"]', 'github = ["admin"]', "state.merge-ready.grant.github"),
    ('tools = ["Edit", "Bash"]', 'tools = "Edit"', "state.implement.grant.tools"),
    ('tools = ["Edit", "Bash"]', 'tools = ["Edit", "Edit"]', "state.implement.grant.tools"),
    ('[state.fix.grant]', '[state.fix.grant]\nresult_tools = ["review_pr"]', "state.fix.grant"),
    ('reuse = "fresh"', 'reuse = "fresh"\nmax = 0', "state.review.manages.1.max"),
    ('reuse = "fresh"', 'reuse = "fresh"\nmax = true', "state.review.manages.1.max"),
    ('"owner.summary"]', '"the whole transcript"]', "state.review.manages.1.with"),
    ('returns = { verdict = ["pass", "fail"] }', 'returns = { verdict = "pass" }', "state.review.manages.1.returns"),
    ('returns = { verdict = ["pass", "fail"] }', 'returns = { verdict = ["true", "false"] }', "state.review.manages.1.returns"),
    ('returns = { verdict = ["pass", "fail"] }', 'returns = { verdict = ["3", "or"] }', "state.review.manages.1.returns"),
    ('to = "work"\nenter = "history"', 'to = "merged"\nenter = "history"', "state.escalated.exit.1.enter"),
    ('[state.work]\npersonas = ["implementor"]\ninitial = "implement"', '[state.work]\npersonas = ["implementor"]', "state.work.initial"),
    ('[state.work]\npersonas = ["implementor"]\ninitial = "implement"', '[state.work]\npersonas = ["implementor"]\ninitial = "merged"', "state.work.initial"),
    ('[state.merged]\nfinal = true', '[state.merged]\nfinal = true\ninitial = "work"', "state.merged.initial"),
    ('[state.merged]\nfinal = true', '[state.merged]\nfinal = true\n[[state.merged.exit]]\nto = "work"\ndecided_by = "hand"', "state.merged"),
    ('[state.merged]', '[state.Merged]', "state.Merged"),
])
def test_parse_refuses(old, new, where):
    with pytest.raises(DefinitionError) as e:
        parse(_with(IMPLEMENT, old, new))
    assert any(p.where == where or p.where.startswith(where + ".") for p in e.value.problems), e.value.problems


def test_parse_refuses_bad_toml_and_parent_loops():
    with pytest.raises(DefinitionError, match="not valid TOML"):
        parse("schema = = 1")
    loop = _with(IMPLEMENT, '[state.work]\n', '[state.work]\nparent = "implement"\n')
    with pytest.raises(DefinitionError, match="loop"):
        parse(loop)


def test_parse_collects_every_problem():
    with pytest.raises(DefinitionError) as e:
        parse(_with(_with(IMPLEMENT, 'approve = "me"', 'approve = "x"'), 'context = "compact"', 'context = "y"'))
    assert len(e.value.problems) == 2


def test_check_passes_the_example(impl):
    assert _problems(IMPLEMENT) == []
    marks = {(f.where, f.text.split(":")[0]) for f in check(impl) if f.kind == "mark"}
    assert marks == {("state.merge-ready.grant.github", "merge")}


def test_check_marks_full_and_sensitive_hub_tools():
    marks = {f.where for f in check(parse(ONE)) if f.kind == "mark"}
    assert marks == {"state.session.grant.access", "state.session.grant.asks_first"}


@pytest.mark.parametrize("old,new,needle", [
    # unreachable: nothing goes to fix any more
    ('[[state.review.exit]]\nto = "fix"', '[[state.review.exit]]\nto = "escalated"', "state.fix: can't be reached"),
    # no exit
    ('[[state.escalated.exit]]\nto = "work"\nenter = "history"\ndecided_by = "facts"\nrequires = ["report.answered"]\non = ["hub:decision"]\n',
     '', "state.escalated: isn't final and has no exit"),
    ('requires = ["pr.open", "branch.pushed"]', 'requires = ["pr.open", "branch.pushed", "pr.lucky"]', "pr.lucky isn't a known fact"),
    ('requires = ["pr.open", "branch.pushed"]', 'requires = ["pr.checks == green"]', "pr.checks is one of"),
    ('requires = ["pr.open", "branch.pushed"]', 'requires = ["pr.open > 3"]', "true or false"),
    ('requires = ["pr.open", "branch.pushed"]', 'requires = ["rounds.nowhere < 3"]', "'nowhere' isn't a state"),
    ('requires = ["pr.open", "branch.pushed"]', 'requires = ["pr.open and branch.pushed"]', "expected"),
    ('"managed.reviewer.verdict == pass"', '"managed.qa.verdict == pass"', "no managed entry here returns qa.verdict"),
    ('"managed.reviewer.verdict == pass"', '"managed.reviewer.verdict == maybe"', "is one of pass, fail"),
    ('when = "The change is complete"\n', '', "needs a `when` question"),
    ('decided_by = "counter"\nrequires = ["rounds.review >= 3"]', 'decided_by = "counter"\nrequires = ["pr.open"]', "tests rounds."),
    ('on = ["feed:pr.state"]', 'on = []', "never tried"),
    # shadowed: an earlier facts exit whose requires are a subset of a later one's and whose signals cover it
    ('requires = ["managed.reviewer.verdict == pass", "pr.checks == pass"]\non = ["hub:managed.return", "feed:pr.checks"]',
     'requires = ["managed.reviewer.verdict == fail", "rounds.review < 3", "pr.checks == pass"]\non = ["hub:managed.return"]',
     "state.review.exit.2: it never moves: in review"),
])
def test_check_finds(old, new, needle):
    problems = _problems(_with(IMPLEMENT, old, new))
    assert any(needle in p for p in problems), problems


def test_check_cycle_bound_by_a_parent_counter():
    # Without rounds on review, the cycle is still bounded: work's exit tests time.work, a parent of every state on it.
    text = _with(IMPLEMENT, '"rounds.review < 3"', '"pr.open"')
    text = _with(text, 'decided_by = "counter"\nrequires = ["rounds.review >= 3"]', 'decided_by = "facts"\nrequires = ["pr.merged"]')
    assert not any("cycle" in p for p in _problems(text))
    text = _with(text, 'requires = ["time.work > 7200 or tokens.work > 600000"]', 'requires = ["pr.open"]')
    assert any("cycle" in p for p in _problems(text))


def test_check_shadowing_needs_covered_signals_and_auto():
    base = ('requires = ["managed.reviewer.verdict == pass", "pr.checks == pass"]\non = ["hub:managed.return", "feed:pr.checks"]')
    sub = 'requires = ["managed.reviewer.verdict == fail", "rounds.review < 3", "pr.checks == pass"]\n'
    # the later exit listens to a signal the earlier doesn't: it can move then
    assert not any("never moves" in p for p in _problems(_with(IMPLEMENT, base, sub + 'on = ["hub:managed.return", "feed:pr.checks"]')))
    # the earlier exit waits for the agent's request: it doesn't always move first
    text = _with(IMPLEMENT, base, sub + 'on = ["hub:managed.return"]')
    text = _with(text, 'on = ["hub:managed.return"]\n[[state.review.exit]]', 'on = ["hub:managed.return"]\nmove = "on-request"\n[[state.review.exit]]')
    assert not any("never moves" in p for p in _problems(text))
    # order of terms in an `or` doesn't hide a shadow
    text = _with(IMPLEMENT, '"rounds.review < 3"]', '"rounds.review < 3 or pr.open"]')
    text = _with(text, '"pr.checks == pass"]\non = ["hub:managed.return", "feed:pr.checks"]',
                 '"pr.checks == pass", "managed.reviewer.verdict == fail", "pr.open or rounds.review < 3"]\non = ["hub:managed.return"]')
    assert any("exit.2: it never moves" in p for p in _problems(text))


def test_check_parent_exit_overridden_in_one_child_only():
    # implement moves to review on pr.open alone, which covers work's exit there, but work's exit still moves in fix
    text = _with(IMPLEMENT, 'requires = ["time.work > 7200 or tokens.work > 600000"]', 'requires = ["pr.open", "rounds.work < 9"]')
    text = _with(text, 'decided_by = "judge"\nwhen = "The change is complete"\nrequires = ["pr.open", "branch.pushed"]',
                 'decided_by = "facts"\nrequires = ["pr.open"]')
    assert not any("never moves" in p for p in _problems(text))
    # with fix and review covering it too, it never moves
    text = _with(text, 'decided_by = "judge"\nwhen = "Every finding has a fixup commit or a reply"\nrequires = ["pr.checks == pass"]',
                 'decided_by = "facts"\nrequires = ["pr.open"]')
    text = _with(text, 'requires = ["managed.reviewer.verdict == fail", "rounds.review < 3"]\non = ["hub:managed.return"]',
                 'requires = ["pr.open"]\non = ["turn.end"]')
    assert any("state.work.exit.1: it never moves" in p for p in _problems(text))


def test_check_cycle_through_history():
    # b → x → back to where it was (b) loops with no counter; without history, x would only re-enter a, which is bounded
    text = """
schema = 1
name = "h"
initial = "p"
[state.p]
initial = "a"
[state.a]
parent = "p"
[[state.a.exit]]
to = "b"
decided_by = "counter"
requires = ["rounds.a < 3"]
on = ["turn.end"]
[state.b]
parent = "p"
[[state.b.exit]]
to = "x"
decided_by = "facts"
requires = ["pr.open"]
on = ["turn.end"]
[state.x]
[[state.x.exit]]
to = "p"
enter = "%s"
decided_by = "facts"
requires = ["report.answered"]
on = ["hub:decision"]
"""
    assert any("the cycle b → x" in p for p in _problems(text % "history"))
    assert not any("cycle" in p for p in _problems(text % "first"))


def test_effective_unions_and_takes_the_widest(impl):
    g = effective(impl, "implement")
    assert g.tools == ("Read", "Grep", "Edit", "Bash")
    assert g.github == ("pr.read", "issues.comment", "push")
    assert (g.access, g.permission_mode, g.checkout, g.all_repos) == ("locked", "acceptEdits", "pr-branch", False)
    assert effective(impl, "review").permission_mode == "plan"
    assert effective(impl, "merged") == Grant(access="locked", permission_mode="dontAsk", checkout=False, all_repos=False)
    full = dataclasses.replace(impl.states["fix"], grant=Grant(access="full", permission_mode="dontAsk", checkout="new-branch"))
    g = effective(dataclasses.replace(impl, states={**impl.states, "fix": full}), "fix")
    assert (g.access, g.permission_mode, g.checkout) == ("full", "dontAsk", "new-branch")


def test_compare(impl):
    c = compare(effective(impl, "review"), effective(impl, "implement"))
    assert c.adds == {"tools": ("Edit", "Bash"), "github": ("push",), "permission_mode": ("acceptEdits",)}
    assert c.removes == {} and c.widens
    assert c.keeps["tools"] == ("Read", "Grep") and c.keeps["checkout"] == ("pr-branch",)
    back = compare(effective(impl, "implement"), effective(impl, "review"))
    assert not back.widens and back.removes["permission_mode"] == ("acceptEdits",) and back.removes["github"] == ("push",)
    assert compare(Grant(), Grant()) == Change({}, {}, {"access": ("locked",), "permission_mode": ("dontAsk",),
                                                       "all_repos": (False,), "checkout": (False,)})
    assert compare(Grant(access="locked"), Grant(access="full")).adds == {"access": ("full",)}
    assert compare(Grant(all_repos=False), Grant(all_repos=True)).widens
    assert compare(Grant(checkout="pr"), Grant(checkout="new-branch")).adds == {"checkout": ("new-branch",)}
    assert not compare(Grant(checkout="pr"), Grant(checkout=False)).widens


ACTIONS = sorted((Path(__file__).resolve().parents[1] / "agents" / "actions").glob("*.toml"))


@pytest.mark.parametrize("path", ACTIONS, ids=[p.stem for p in ACTIONS])
def test_every_action_is_a_one_state_definition(path):
    import tomllib
    a = tomllib.loads(path.read_text())
    keys = [f.name for f in dataclasses.fields(Grant)]
    grant = Grant(**{k: tuple(a[k]) if isinstance(a[k], list) else a[k] for k in keys if k in a})
    d = machine.Definition(path.stem, "session", {"session": machine.State(
        "session", personas=tuple(a["personas"]), final=True, grant=grant)})
    assert parse(emit(d)) == d
    assert [f for f in check(d) if f.kind == "problem"] == []
    assert effective(d, "session").checkout == a.get("checkout", False)


def test_exits_of_child_first(impl):
    assert [e.to for e in exits_of(impl, "review")] == ["fix", "merge-ready", "escalated", "escalated"]
    assert exits_of(impl, "review")[-1].decided_by == "judge"
    assert exits_of(impl, "merged") == []


@pytest.mark.parametrize("expr,terms", [
    ("pr.open", [("pr.open", "==", True)]),
    ("not pr.open", [("pr.open", "==", False)]),
    ("pr.checks == pass", [("pr.checks", "==", "pass")]),
    ("rounds.merge-ready<3", [("rounds.merge-ready", "<", 3)]),
    ("time.work > 7200 or not branch.pushed", [("time.work", ">", 7200), ("branch.pushed", "==", False)]),
    ("managed.reviewer.verdict != fail", [("managed.reviewer.verdict", "!=", "fail")]),
    ("pr.open == false", [("pr.open", "==", False)]),
])
def test_parse_requires(expr, terms):
    assert parse_requires(expr) == Requirement(tuple(Term(*t) for t in terms))


@pytest.mark.parametrize("expr", ["", "or", "pr.open or", "not", "not not pr.open", "pr.open ==", "== pr.open",
                                  "pr.open == true == true", "pr.checks > pass", "rounds.review == many", "pr.nope",
                                  "pr.checks == pass and pr.open", "pr.checks == 'pass'", "rounds.a.b < 1"])
def test_parse_requires_refuses(expr):
    with pytest.raises(DefinitionError):
        parse_requires(expr)


def test_requirement_holds():
    r = parse_requires("rounds.review >= 3 or pr.checks == fail")
    assert r.holds({"rounds.review": 3}) and r.holds({"pr.checks": "fail", "rounds.review": 0})
    assert not r.holds({"rounds.review": 2}) and not r.holds({}) and not r.holds({"rounds.review": True})


def test_feed_signals_agree_with_the_feed():
    kinds = {s.split(":")[1].split(".")[1] for s in machine.SIGNALS if s.startswith("feed:")}
    assert kinds == set(feed.WHATS)
    assert "feed:run.run" in machine.SIGNALS and "feed:issue.run" not in machine.SIGNALS
    assert "feed:issue.checks" not in machine.SIGNALS and "feed:pr.labels" in machine.SIGNALS


def _kinds(rows):
    return [(r.kind, r.state, r.exit, r.to, r.fields) for r in rows]


def test_outline_diff_same(impl):
    rows = outline_diff(impl, impl)
    assert {r.kind for r in rows} == {"same"}
    assert [(r.state, r.exit) for r in rows][:3] == [("work", None), ("work", 1), ("implement", None)]


def test_outline_diff_kinds(impl):
    review = impl.states["review"]
    e1, e2, e3 = review.exits
    new_review = dataclasses.replace(
        review, exits=(e2, e1, dataclasses.replace(e3, approve="owner"), Exit("abandoned", "hand")), context="keep")
    states = {k: v for k, v in impl.states.items() if k != "fix"}
    states["review"] = new_review
    states["abandoned"] = machine.State("abandoned", final=True)
    b = dataclasses.replace(impl, states=states)
    rows = [r for r in outline_diff(impl, b) if r.kind != "same"]
    assert ("changed", "review", None, None, ("context",)) in _kinds(rows)
    review_exits = [k for k in _kinds(rows) if k[1] == "review" and k[2] is not None]
    # the two swapped exits: one kept its place relative to the rest, the other moved
    assert review_exits == [("moved", "review", 2, "fix", ()), ("changed", "review", 3, "escalated", ("approve",)),
                            ("added", "review", 4, "abandoned", ())]
    assert ("removed", "fix", None, None, ()) in _kinds(rows) and ("removed", "fix", 1, "review", ()) in _kinds(rows)
    assert ("added", "abandoned", None, None, ()) in _kinds(rows)
    order = [r.state for r in outline_diff(impl, b) if r.exit is None]
    assert order.index("fix") == order.index("review") + 1


def test_outline_diff_one_insert_moves_nothing(impl):
    review = impl.states["review"]
    b = dataclasses.replace(impl, states={**impl.states, "review": dataclasses.replace(
        review, exits=(Exit("merged", "hand"), *review.exits))})
    kinds = [r.kind for r in outline_diff(impl, b) if r.state == "review" and r.exit]
    assert kinds == ["added", "same", "same", "same"]
