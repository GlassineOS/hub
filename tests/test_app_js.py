"""Behaviour of the page's pure functions, run in node: what static checks of the source can't show.

Each function is taken from app.js as it is (a top-level `function name(...) { ... }` that ends at a line holding only
`}`), so the test runs the shipped code, not a copy."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app" / "hub" / "static" / "app.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node isn't installed")


def function(name: str) -> str:
    match = re.search(rf"^function {name}\(.*?^}}$", APP.read_text(), re.S | re.M)
    assert match, f"no top-level function {name} in app.js"
    return match.group(0)


def run(names: list[str], body: str):
    script = "\n".join(function(n) for n in names) + f"\nconsole.log(JSON.stringify((() => {{ {body} }})()));"
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30, check=True).stdout
    return json.loads(out)


def test_only_rows_for_the_words_typed_now_count():
    """#28 review: a late reply for "battery" can't stand in for "battery drain", nor be picked with Enter."""
    rows = [{"repo": "hub", "number": 1}]
    got = run(["currentRows"], f"""
        const rows = {json.dumps(rows)};
        return [
          currentRows({{ words: "battery", rows }}, "battery"),
          currentRows({{ words: "battery", rows }}, "battery drain"),
          currentRows({{ words: "", rows: [] }}, "battery"),
        ];""")
    assert got == [rows, [], []]


def test_a_run_says_how_it_ended():
    """#28 review: a cancelled or timed-out run doesn't read "closed"."""
    got = run(["pillState"], """
        const run = (conclusion, status = "completed") => pillState("run", { status, conclusion });
        return [run(null, "in_progress"), run("success"), run("failure"), run("timed_out"), run("startup_failure"),
                run("cancelled"), run("skipped"), run("neutral")];""")
    assert got == ["running", "passed", "failing", "failing", "failing", "cancelled", "skipped", "closed"]


def test_esc_is_left_alone_when_no_list_is_open():
    """#28 review: an empty picker inside a dialog mustn't swallow the Esc that closes the dialog."""
    got = run(["listKeys"], """
        const press = (open) => {
          const e = { key: "Escape", prevented: false, stopped: false,
                      preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; } };
          let closed = false;
          listKeys(e, { size: 0, active: 0, setActive() {}, pick() {}, close() { closed = true; }, open });
          return [e.prevented, e.stopped, closed];
        };
        return [press(true), press(false)];""")
    assert got == [[True, True, True], [False, False, False]]


def test_a_session_is_embedded_only_in_the_item_it_was_placed_on():
    """#34 review 5: a move on this page is keyed by session and item, and the stored view counts only for its own item."""
    got = run(["embeddedPhase"], """
        const view = (over) => ({ name: "s", agent: { view: { mode: "embedded", where: "Work", ref: "hub#1", ...over } } });
        const A = "hub#1", B = "hub#2";
        return [
          embeddedPhase(null, A, {}),                                   // no session
          embeddedPhase(view({}), A, {}),                               // stored for this item
          embeddedPhase(view({}), B, {}),                               // stored for another item: background here, as after a reload
          embeddedPhase(view({ ref: null }), B, {}),                    // stored with no item: any
          embeddedPhase(view({ where: "Sessions" }), A, {}),            // placed from Sessions
          embeddedPhase(view({ mode: "background" }), A, {}),
          embeddedPhase({ name: "s", agent: {} }, A, {}),               // no stored view at all
          embeddedPhase(view({}), B, { "s@hub#1": "embedded" }),        // moved on item A says nothing about B
          embeddedPhase(view({}), A, { "s@hub#1": "background" }),      // moved here wins over the stored view
          embeddedPhase(view({ mode: "background" }), B, { "s@hub#2": "embedded" }),
        ];""")
    assert got == [None, "embedded", "background", "embedded", "background", "background", "background", "background", "background", "embedded"]


def test_the_origin_is_told_in_words():
    """#34 follow-up: a session started with the one click says so, and only one with no origin at all is called old."""
    constants = "\n".join(re.search(rf"^const {n} = .*;$", APP.read_text(), re.M).group(0) for n in ("STEWARD", "byWords"))
    script = f"{constants}\n{function('originWords')}\nconsole.log(JSON.stringify((() => {{ %s }})()));"
    body = """
        const words = (a) => originWords(a);
        return [
          words({ origin: { launch: null, from: null, by: "you" } }),
          words({ origin: { launch: "w1", from: { view: "Work", ref: "hub#4" }, by: "you" } }),
          words({ origin: { launch: "w2", from: { view: "Needs you", ref: null }, by: "steward" } }),
          words({ origin: { launch: "w3", from: null, by: "you" } }),
          words({ origin: null, started_by: "steward" }),
          words({ origin: null, started_by: null }),
        ];"""
    out = subprocess.run([NODE, "-e", script % body], capture_output=True, text=True, timeout=30, check=True).stdout
    assert json.loads(out) == ["started directly, by you", "from Work item hub#4, by you", "from Needs you, by the Steward",
                               "from Launch, by you", "started by the Steward", "started before origins were kept"]


def test_a_note_on_a_removed_line_sits_under_that_line():
    """#37 review 1: a LEFT note counts old-file lines, so it goes under the `del` row with that old number and never
    under the unrelated new-side row that happens to share it."""
    diff = "\n".join(["@@ -10,3 +10,3 @@", " keep", "-gone", "+new", " tail"])
    got = run(["diffRows", "noteBelongsTo"], f"""
        const rows = diffRows({json.dumps(diff)});
        const under = (thread) => rows.filter((r) => noteBelongsTo(thread, r)).map((r) => [r.kind, r.a || null, r.b || null]);
        return [
          under({{ line: 11, side: "LEFT" }}),    // the removed line: old number 11
          under({{ line: 11, side: "RIGHT" }}),   // new number 11 is the added line, not the removed one
          under({{ line: 12, side: "LEFT" }}),    // old number 12 is the unchanged tail
          under({{ line: 13, side: "LEFT" }}),    // no old line 13 in the hunk: nowhere, as for any line outside it
          under({{ line: null, side: "LEFT" }}),
        ];""")
    assert got == [[["del", 11, None]], [["add", None, 11]], [["ctx", 12, 12]], [], []]


def test_the_theme_follows_the_browser_scheme():
    """001 FR-014: theme.js picks White Night while the browser prefers dark, White Paper otherwise, and follows a change."""
    theme = (APP.parent / "theme.js").read_text()
    script = """
        const listeners = [], media = { matches: true, addEventListener(type, f) { listeners.push([type, f]); } };
        globalThis.window = { matchMedia: (q) => { seen.push(q); return media; } };
        globalThis.document = { documentElement: { dataset: {} } };
        const seen = [], picked = [];
    """ + theme + """
        picked.push(document.documentElement.dataset.theme);
        media.matches = false; listeners.forEach(([type, f]) => type === "change" && f());
        picked.push(document.documentElement.dataset.theme);
        console.log(JSON.stringify({ seen, picked, listeners: listeners.length }));
    """
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30, check=True).stdout
    assert json.loads(out) == {"seen": ["(prefers-color-scheme: dark)"], "picked": ["white-night", "white-paper"], "listeners": 1}
    # Without matchMedia the page still gets a theme.
    bare = "globalThis.window = {}; globalThis.document = { documentElement: { dataset: {} } };" + theme + \
        "console.log(JSON.stringify(document.documentElement.dataset.theme));"
    assert json.loads(subprocess.run([NODE, "-e", bare], capture_output=True, text=True, timeout=30, check=True).stdout) == "white-paper"


def test_the_state_chip_says_the_path_and_the_kind_in_words():
    """012 FR-080: the path of states and its kind in words, for every kind; a one-state workflow shows its action's name,
    quietly, and is over once Claude has ended; a final state is over; a move waiting for a confirm waits for you."""
    got = run(["chipKindWords", "chipOf"], """
        const m = (over) => ({ workflow: "implement", state: "review", path: ["work", "review"], one_state: false, final: false, paused: false, waits: false, ...over });
        const one = { workflow: "issue-triage", state: "session", path: ["session"], one_state: true, final: true, paused: false, waits: false };
        const pick = (c) => c && [c.kind, c.label, c.sub, c.quiet];
        return [
          ["holds", "moving", "waits", "up", "over"].map(chipKindWords),
          pick(chipOf(m({}), false)),
          pick(chipOf(m({ waits: true }), false)),
          pick(chipOf(m({ state: "merged", path: ["merged"], final: true }), false)),
          pick(chipOf(m({ paused: true }), false)),
          pick(chipOf(one, false)),
          pick(chipOf(one, true)),
          pick(chipOf({ ...one, waits: true }, false)),
          chipOf(null, false),
          chipOf(m({}), false).said,
        ];""")
    assert got == [["holds", "moving", "waits for you", "sent up", "over"],
                   ["holds", "work › review", "holds", False],
                   ["waits", "work › review", "waits for you", False],
                   ["over", "merged", "over", False],
                   ["holds", "work › review", "holds · paused", False],
                   ["holds", "issue-triage", "holds", True],
                   ["over", "issue-triage", "over", True],
                   ["waits", "issue-triage", "waits for you", False],
                   None,
                   "workflow implement, in work › review, holds"]


STATES = [
    {"id": "work", "parent": None, "initial": "implement", "final": False, "manages": [],
     "exits": [{"to": "escalated", "decided_by": "judge", "when": "Stuck", "requires": ["time.work > 7200"], "enter": "first", "move": "auto", "approve": "none"}]},
    {"id": "implement", "parent": "work", "initial": None, "final": False, "manages": [],
     "exits": [{"to": "review", "decided_by": "facts", "when": "", "requires": ["pr.open"], "enter": "first", "move": "auto", "approve": "none"}]},
    {"id": "review", "parent": "work", "initial": None, "final": False, "manages": [{"name": "reviewer", "persona": "reviewer", "workflow": "pr-review", "start": "auto"}],
     "exits": [{"to": "work", "decided_by": "counter", "when": "", "requires": ["rounds.review >= 3"], "enter": "history", "move": "auto", "approve": "none"}]},
    {"id": "escalated", "parent": None, "initial": None, "final": False, "manages": [], "exits": []},
    {"id": "merged", "parent": None, "initial": None, "final": True, "manages": [], "exits": []},
]


def test_the_outline_lists_children_before_their_parents_exits():
    """012 FR-081: the outline in place of the diagram: depth, where it is now, and how far each exit tried now holds."""
    tried = [{"from": "review", "place": 1, "result": "fails"}, {"from": "work", "place": 1, "result": "unknown"}]
    got = run(["exitWhy", "outlineRows"], f"""
        return outlineRows({json.dumps(STATES)}, "work", ["work", "review"], {json.dumps(tried)})
          .map((r) => r.row === "state" ? ["state", r.id, r.depth, r.tags.join(","), r.sub] : ["exit", r.n, r.to, r.depth, r.why, r.holds]);""")
    assert got == [
        ["state", "work", 0, "inside it now,parent,starts here", "Its grant and its exits apply in implement, review."],
        ["state", "implement", 1, "starts here", ""],
        ["exit", "1", "review", 2, "facts · requires pr.open", ""],
        ["state", "review", 1, "now", "Runs reviewer (pr-review, starts on entry)."],
        ["exit", "1", "work", 2, "counter · requires rounds.review >= 3 · back to where it was", "doesn’t hold"],
        ["exit", "then, in any of them", "escalated", 1, "judged · “Stuck” · requires time.work > 7200", "not known yet"],
        ["state", "escalated", 0, "", ""],
        ["state", "merged", 0, "final", ""],
    ]


def test_a_move_by_hand_can_go_anywhere_but_where_it_is():
    got = run(["statePath", "moveTargets"], f"return moveTargets({json.dumps(STATES)}, 'review');")
    assert [(t["id"], t["label"], t["parent"]) for t in got] == [
        ("work", "work", True), ("implement", "work › implement", False), ("escalated", "escalated", False), ("merged", "merged (final)", False)]


def test_a_check_the_hub_has_no_value_for_is_not_known_not_failed():
    got = run(["checkWords"], """
        return [
          checkWords({ requires: "rounds.review < 3", result: "holds", terms: [{ fact: "rounds.review", have: 1 }] }),
          checkWords({ requires: "pr.open", result: "unknown", terms: [{ fact: "pr.open", have: null }] }),
          checkWords({ requires: "rounds.review >= 3", result: "fails", terms: [{ fact: "rounds.review", have: 1 }] }),
        ].map((w) => [w.mark, w.value, w.result]);""")
    assert got == [["✓", "rounds.review is 1", "holds"], ["?", "pr.open: no value yet", "not known yet"], ["✗", "rounds.review is 1", "doesn’t hold"]]


def test_the_confirm_marks_each_sensitive_item_and_what_was_never_held():
    """012 FR-024: what the new state adds, with the mark from hubd's list of sensitive items, and which items the
    instance never held."""
    sensitive = {"github": {"merge": "merging to the default branch"}, "hub_tools": {"merge_pr": "merging to the default branch"}}
    got = run(["grantRows"], f"""
        return grantRows({{ github: ["merge", "pr.comment"], hub_tools: ["merge_pr"], permission_mode: ["acceptEdits"], checkout: [false], all_repos: [true] }},
                         {json.dumps(sensitive)}, {{ github: ["merge"] }}).map((r) => [r.kind, r.what, r.sens, r.first]);""")
    assert got == [["GitHub", "merge", "merging to the default branch", True], ["GitHub", "pr.comment", "", False],
                   ["Hub tools", "merge_pr", "merging to the default branch", False], ["Permission mode", "acceptEdits", "", False],
                   ["Checkout", "none", "", False], ["All repositories", "every repository", "", False]]


def test_the_history_puts_moves_and_evaluations_together_newest_first():
    h = {"moves": [{"seq": 1, "at": 10, "from": "implement", "to": "review", "by": "hand", "who": "maintainer", "widening": False, "confirmed_by": None, "change": {"adds": {}, "removes": {"github": ["push"]}}},
                   {"seq": 2, "at": 30, "from": "review", "to": "merge-ready", "by": "hand", "who": "maintainer", "widening": True, "confirmed_by": "maintainer", "change": {"adds": {"github": ["merge"]}}},
                   {"seq": 3, "at": 40, "from": "merge-ready", "to": "merge-ready", "by": "pause", "who": "maintainer", "widening": False, "change": {}}],
         "evaluations": [{"seq": 1, "at": 20, "signal": "turn.end", "state": "review", "proposal": "fix", "evidence": "<b>x</b>", "checks": [{"t": 1}], "judge": "default", "ms": 5, "failed": False}]}
    got = run(["historyRows"], f"return historyRows({json.dumps(h)}).map((r) => [r.title, r.by, r.result, r.details.map((d) => d.join(': '))]);")
    assert got == [["paused automatic moves · in merge-ready", "maintainer", "", []],
                   ["moved by hand · review → merge-ready", "maintainer", "widened: confirmed by maintainer · adds merge", []],
                   ["tried the exits of review", "judge default", "proposed: fix", ["Signal: turn.end", "Evidence: <b>x</b>", 'Checks: {"t":1}', "Judge: default, 5 ms"]],
                   ["moved by hand · implement → review", "maintainer", "takes away push", []]]
    assert run(["historyRows"], "return historyRows(undefined);") == []


def test_the_page_parses_as_a_module(tmp_path):
    """`node --check` on a .js file reads it as a script: a stray brace can hide there that a module rejects."""
    copy = tmp_path / "app.mjs"
    copy.write_text(APP.read_text())
    subprocess.run([NODE, "--check", str(copy)], check=True, capture_output=True, timeout=30)


# ---- the workflow editor and the workflow.change card (012 FR-061, FR-063) ----
DIFF_ROWS = [
    {"kind": "same", "state": "work", "exit": None, "to": None, "fields": [], "depth": 0, "before": {"title": "work", "tags": ["parent"]}, "after": {"title": "work", "tags": ["parent"]}},
    {"kind": "same", "state": "implement", "exit": None, "to": None, "fields": [], "depth": 1, "before": {"title": "implement", "tags": []}, "after": {"title": "implement", "tags": []}},
    {"kind": "same", "state": "implement", "exit": 1, "was": 1, "to": "review", "fields": [], "depth": 2, "before": {"title": "→ review", "sub": "judge"}, "after": {"title": "→ review", "sub": "judge"}},
    {"kind": "same", "state": "review", "exit": None, "to": None, "fields": [], "depth": 1, "before": {"title": "review", "tags": []}, "after": {"title": "review", "tags": []}},
    {"kind": "moved", "state": "review", "exit": 1, "was": 2, "to": "escalated", "fields": [], "depth": 2, "before": {"title": "→ escalated", "sub": "counter"}, "after": {"title": "→ escalated", "sub": "counter"}},
    {"kind": "same", "state": "review", "exit": 2, "was": 1, "to": "merge-ready", "fields": [], "depth": 2, "before": {"title": "→ merge-ready", "sub": "facts"}, "after": {"title": "→ merge-ready", "sub": "facts"}},
    {"kind": "changed", "state": "review", "exit": 3, "was": 3, "to": "fix", "fields": ["requires"], "depth": 2, "before": {"title": "→ fix", "sub": "a"}, "after": {"title": "→ fix", "sub": "b"}},
    {"kind": "added", "state": "review", "exit": 4, "to": "abandoned", "fields": [], "depth": 2, "before": None, "after": {"title": "→ abandoned", "sub": "hand"}},
    {"kind": "same", "state": "merge-ready", "exit": None, "to": None, "fields": [], "depth": 0, "before": {"title": "merge-ready", "tags": ["final"]}, "after": {"title": "merge-ready", "tags": ["final"]}},
    {"kind": "removed", "state": "old", "exit": None, "to": None, "fields": [], "depth": 0, "before": {"title": "old", "tags": []}, "after": None},
]


def test_only_what_changes_folds_the_rest_but_keeps_a_changed_states_other_exits():
    got = run(["odCells", "odRows"], f"""
        const rows = {json.dumps(DIFF_ROWS)};
        const shape = (list) => list.map((r) => r.fold ? r.text : [r.row.state, r.row.exit, r.tag, r.L && r.L.title, r.R && r.R.title, r.L && r.L.mark, r.R && r.R.mark]);
        return [shape(odRows(rows, true)), odRows(rows, false).length];""")
    only, every = got
    assert only == [
        "⋯ 3 unchanged rows",
        ["review", None, "", "review", "review", "", ""],
        ["review", 1, "moved from place 2 to 1", "2. → escalated", "1. → escalated", "old", "add"],
        ["review", 2, "", "1. → merge-ready", "2. → merge-ready", "", ""],      # kept: a changed state's other exits stay
        ["review", 3, "changed: requires", "3. → fix", "3. → fix", "old", "add"],
        ["review", 4, "added", None, "4. → abandoned", None, "add"],
        "⋯ 1 unchanged row",
        ["old", None, "removed", "old", None, "old", None],
    ]
    assert every == len(DIFF_ROWS)


def test_approve_says_why_it_waits_while_a_problem_stands():
    got = run(["approveReason", "checkRows"], """
        const problem = { kind: "problem", where: "state.orphan", text: "can't be reached from 'session'" };
        const mark = { kind: "mark", where: "state.merge.grant.github", text: "merge: merging to the default branch" };
        return [approveReason([mark]), approveReason([problem, mark]), approveReason([problem, problem], "Save"),
                checkRows([mark]).map((r) => r.kind), checkRows([mark, problem]).map((r) => r.kind)];""")
    assert got[0] is None
    assert got[1] == "Approve waits: the checks find a problem. state.orphan: can't be reached from 'session'"
    assert got[2].startswith("Save waits: the checks find 2 problems.")
    assert got[3] == ["ok", "mark"] and got[4] == ["problem", "mark"]


def test_a_text_diff_line_says_its_sign_in_words():
    got = run(["textDiffLines"], """return textDiffLines([{ kind: "hunk", text: "@@ -1 +1 @@" }, { kind: "del", text: "a" }, { kind: "add", text: "b" }, { kind: "ctx", text: "c" }]);""")
    assert [(l["cls"], l["sr"], l["text"]) for l in got] == [("hunk", "", "@@ -1 +1 @@"), ("del", "removed: ", "a"), ("add", "added: ", "b"), ("", "", "c")]
