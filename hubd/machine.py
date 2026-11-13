# SPDX-License-Identifier: GPL-2.0-or-later
"""Workflow definitions: a hierarchical state machine a session holds (spec 012, FR-001 to FR-010).

Pure data and checks, no I/O. `parse` reads the TOML text form, `emit` writes it back, `check` finds what stops a save
(problems) and what only shows (marks), and `effective`/`compare` give a state's grant and tell a widening move.

A state's grant holds a session's rights: access, permission_mode, tools, hub_tools, asks_first, checkout and all_repos,
plus github capabilities. A workflow also says how its sessions begin: its `[[start]]` tables (spec 012, FR-100 to FR-105),
each a way to start it from one kind of item, and its `[launch]` table, what every session of it is however it begins
(its personas, its result type and how a person applies it, what a managed session of it starts with). Neither grants
anything: a session's rights are its starting state's grant.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import MISSING, dataclass, field, fields

from . import feed

SCHEMA = 1
_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")      # state ids and managed names: no dots, they sit inside fact names
_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")    # workflow, judge, persona names: never a URL
_FIELD = re.compile(r"[a-z][a-z0-9_]{0,63}")
_TOOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_WORD = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_RESERVED = {"or", "not", "true", "false"}

CONTEXTS = ("keep", "compact", "fresh")
ACCESS = ("locked", "full")                                  # ordered, narrowest first
PERMISSION_MODES = ("plan", "dontAsk", "default", "acceptEdits", "auto", "bypassPermissions")  # ordered, narrowest first
CHECKOUTS = (False, "default", "pr", "pr-branch", "new-branch")
# The one list of GitHub capability names: a state's grant names them, and a session's token (apps.CAPABILITIES) maps each
# to the GitHub App permissions it takes.
GITHUB = ("read", "issues.read", "issues.write", "issues.comment", "issues.label", "issues.delete",
          "pr.read", "pr.write", "pr.comment", "pr.review", "pr.label", "push", "merge",
          "runs.read", "runs.write", "runs.trigger", "runs.rerun", "runs.cancel", "runs.approve", "repo.public", "repo.delete")
# FR-034. The mark adds no rule.
SENSITIVE = {"merge": "merging to the default branch", "runs.approve": "approving workflow runs from forks",
             "repo.public": "making a repository public", "repo.delete": "deleting a repository"}
SENSITIVE_HUB_TOOLS = {"merge_pr": "merging to the default branch"}
ENTERS = ("first", "history")
DECIDERS = ("judge", "facts", "counter", "hand")
MOVES = ("auto", "on-request")
APPROVERS = ("none", "owner", "maintainer", "steward", "me")
STARTS = ("auto", "on-request")
REUSES = ("resume", "fresh")
ON_EXIT = ("stop", "keep", "handover")
WITH = ("issue", "pr", "diff", "diff.since_last_round", "owner.summary")
WITH_PREFIXES = ("notes:", "brief:")
# Starts (FR-100 to FR-105): the kinds of item a start applies to, what it does while an instance holds the item, the checks of
# the item a start is offered on, and the names a prompt may fill in.
START_ON = ("issue", "pr", "run", "repo", "project", "knowledge", "notes")
WHEN_HELD = ("beside", "ask", "hide")
START_WHEN = ("failing", "not-failing")
START_NEEDS = ("review",)
PROMPT_FIELDS = ("repo", "number", "checkout")
# FR-104: what a starting grant may hold and still run beside an instance that holds the item. GitHub's read capabilities
# (apps.READ_CAPABILITIES), and hub tools that write nothing outside the hub or only hand in what a person applies (the
# session's read-only tools, agents.READS_ONLY, and these). Anything else, full access included, can write on the item.
READ_GITHUB = ("read", "issues.read", "pr.read", "runs.read")
READ_HUB_TOOLS = frozenset({
    "code_search", "docs_index_status", "docs_search", "get_issue", "get_pr", "get_pr_diff", "get_pr_diff_summary", "get_pr_threads",
    "get_run", "get_run_log", "list_issues", "list_prs", "list_repo_files", "list_runs", "list_workflows", "map_definition",
    "map_overview", "map_string", "map_usages", "notes_find", "overview", "plan_work", "rate_limit", "read_repo_file", "read_report",
    "request_repository", "roadmap", "run_history", "submit_result", "work_search", "work_status"})
QUIET_HUB_TOOLS = READ_HUB_TOOLS | {"submit_drafts", "request_move", "draft_workflow", "read_draft", "read_workflow"}


def _feed_signals() -> tuple[str, ...]:
    # The pairs the change feed records: a run's change only on a run, a head, review or checks change only on a PR.
    pr_only = ("head", "review", "checks")
    return tuple(f"feed:{kind}.{what}" for kind in ("issue", "pr", "run") for what in feed.WHATS
                 if (kind == "run") == (what == "run") and (what not in pr_only or kind == "pr"))


SIGNALS = ("turn.end", "session.end", "tool.after", "compact.before",
           "hub:decision", "hub:managed.return", "hub:managed.end", *_feed_signals())

# The facts `requires` may test, with their value types: "bool", "int", or the tuple of values an enum takes.
# <state> names a state of the definition; <entry>.<field> a `manages` entry of the state or an ancestor and a field of its
# `returns`, whose values are the entry's. started.<entry>: whether a session of that entry started in the entry's current
# round, or its start waits for an approval, known for every entry in force. when.<entry>: what the judge said of an entry's
# `when` this round, unknown until it is judged. draft.reviewed: the newest draft went to a reviewer. design.accepted: whether a design session the state manages had its pull request
# merged. draft.*: the newest workflow draft of a workflow-change session, and its failed drafts in the current round.
FACTS = {"pr.open": "bool", "pr.merged": "bool", "pr.checks": ("pass", "fail", "pending"),
         "pr.review": ("approved", "changes_requested", "none"), "pr.reviewed": "bool", "branch.pushed": "bool", "issue.linked": "bool",
         "design.accepted": "bool", "report.answered": "bool", "draft.ok": "bool", "draft.sensitive": "bool", "drafts.failed": "int",
         "draft.reviewed": "bool", "started.<entry>": "bool", "when.<entry>": "bool", "rounds.<state>": "int", "time.<state>": "int", "tokens.<state>": "int", "managed.<entry>.<field>": "returns"}
COUNTERS = ("rounds", "time", "tokens")
# A `returns` field is a list of the values it takes (a fact), or TEXT_LIST: short lines of text handed to the owner as data,
# never a fact. Bounds on what such a field carries:
TEXT_LIST = "text-list"
MAX_TEXT_ITEMS = 20
MAX_TEXT_ITEM = 500
OPS = ("==", "!=", "<", "<=", ">", ">=")


@dataclass(frozen=True)
class Problem:
    where: str
    text: str


class DefinitionError(Exception):
    def __init__(self, problems: list[Problem]):
        super().__init__("; ".join(f"{p.where}: {p.text}" for p in problems))
        self.problems = problems


@dataclass(frozen=True)
class Finding:
    kind: str  # "problem" | "mark"
    where: str
    text: str


@dataclass(frozen=True)
class Grant:
    """None means the state doesn't set it and takes its ancestors'."""
    access: str | None = None
    permission_mode: str | None = None
    tools: tuple[str, ...] = ()
    hub_tools: tuple[str, ...] = ()
    asks_first: tuple[str, ...] = ()
    checkout: str | bool | None = None
    all_repos: bool | None = None
    github: tuple[str, ...] = ()


_SET_KEYS = ("tools", "hub_tools", "asks_first", "github")
_ORDERED = {"access": ACCESS, "permission_mode": PERMISSION_MODES, "all_repos": (False, True)}
_LOWEST = {"access": "locked", "permission_mode": "dontAsk", "all_repos": False}


@dataclass(frozen=True)
class Exit:
    to: str
    decided_by: str
    enter: str = "first"
    when: str = ""
    requires: tuple[str, ...] = ()
    on: tuple[str, ...] = ()
    move: str = "auto"
    approve: str = "none"


@dataclass(frozen=True)
class Manage:
    name: str
    persona: str
    workflow: str
    on_pr: str = ""                # the workflow it runs instead for an owner on a pull request and no issue (a PR taken on)
    start: str = "auto"
    when: str = ""
    max: int = 1
    reuse: str = "resume"
    on_exit: str = "stop"
    with_: tuple[str, ...] = ()
    returns: dict[str, tuple[str, ...] | str] = field(default_factory=dict)  # field -> its values, or TEXT_LIST


@dataclass(frozen=True)
class State:
    id: str
    parent: str | None = None
    instructions: str = ""
    personas: tuple[str, ...] = ()
    context: str = "keep"
    focus: str = ""                # what a compaction keeps, for context = "compact"
    final: bool = False
    initial: str | None = None
    grant: Grant = Grant()
    exits: tuple[Exit, ...] = ()
    manages: tuple[Manage, ...] = ()


@dataclass(frozen=True)
class Start:
    """A way to begin the workflow from one kind of item (FR-100). An empty field takes the workflow's `[launch]` value."""
    on: str
    label: str
    summary: str = ""
    id: str | None = None          # the action id sessions keep; one start of a workflow may leave it out and has its name
    ceiling: str = ""              # its starting grant in plain words, as the item's page shows it
    state: str | None = None       # where it starts: the initial state when none is named
    lead: bool = False
    when_held: str = "ask"
    ask_move: str | None = None    # asked of a holding instance: a move request to this state of its workflow
    order: int | None = None
    verb: str | None = None
    when: str | None = None
    needs: str | None = None
    asks_describe: bool = False
    asks_paths: bool = False
    models: tuple[str, ...] = ()
    efforts: tuple[str, ...] = ()
    prompt: str = ""


@dataclass(frozen=True)
class Launch:
    """What a session of the workflow is however it begins. A workflow without starts is started only as a managed session,
    which takes `on`, `label`, `summary`, `ceiling`, `models`, `efforts` and `prompt` from here."""
    personas: tuple[str, ...] = ()
    result: str = ""
    result_tools: tuple[str, ...] = ()
    plan: bool = True
    per_repo: bool = False
    singleton: str | None = None
    repository: str | None = None
    repo: str | None = None
    roadmap: bool = False
    asks_wait_for_you: bool = False
    drafting: dict[str, str] | None = None
    on: str | None = None
    label: str = ""
    summary: str = ""
    ceiling: str = ""
    order: int | None = None
    models: tuple[str, ...] = ()
    efforts: tuple[str, ...] = ()
    prompt: str = ""


_START_ORDER = ("id", "on", "label", "summary", "ceiling", "state", "lead", "when_held", "ask_move", "order", "verb", "when", "needs",
                "asks_describe", "asks_paths", "models", "efforts", "prompt")
_LAUNCH_ORDER = ("personas", "result", "result_tools", "plan", "per_repo", "singleton", "repository", "repo", "roadmap",
                 "asks_wait_for_you", "on", "label", "summary", "ceiling", "order", "models", "efforts", "prompt", "drafting")


@dataclass(frozen=True)
class Definition:
    name: str
    initial: str
    states: dict[str, State]
    judge: str | None = None
    schema: int = SCHEMA
    status: bool = False           # a move posts a one-line status comment to the session's pull request or issue (FR-025)
    launch: Launch | None = None   # None: the text has none, and a saved version takes the file's
    starts: tuple[Start, ...] | None = None  # None: the text names none, and a saved version takes the file's; () none at all


# ---- requires ----

@dataclass(frozen=True)
class Term:
    name: str
    op: str
    value: bool | int | str

    def holds(self, values: dict) -> bool:
        have = values.get(self.name)
        if have is None or type(have) is not type(self.value):
            return False
        return {"==": have == self.value, "!=": have != self.value, "<": have < self.value, "<=": have <= self.value,
                ">": have > self.value, ">=": have >= self.value}[self.op]


@dataclass(frozen=True)
class Requirement:
    """Terms joined by `or`. A `requires` list is the AND of its requirements."""
    terms: tuple[Term, ...]

    def holds(self, values: dict) -> bool:
        return any(t.holds(values) for t in self.terms)


_TOKEN = re.compile(r"\s*(==|!=|<=|>=|<|>|-?[0-9]+|[A-Za-z0-9_][A-Za-z0-9_.:-]*)")


def fact_type(name: str):
    """The value type of a fact name by the registry, or None if it isn't one. Doesn't check that a state exists."""
    if name in FACTS and "<" not in name:
        return FACTS[name]
    parts = name.split(".")
    if len(parts) == 2 and parts[0] in COUNTERS and _ID.fullmatch(parts[1]):
        return "int"
    if len(parts) == 3 and parts[0] == "managed" and _ID.fullmatch(parts[1]) and _FIELD.fullmatch(parts[2]):
        return "returns"
    if len(parts) == 2 and parts[0] in ("started", "when") and _ID.fullmatch(parts[1]):
        return "bool"
    return None


def _value(word: str):
    if re.fullmatch(r"-?[0-9]+", word):
        return int(word)
    if word in ("true", "false"):
        return word == "true"
    return word


def _typed(term: Term, kind) -> str | None:
    """Why a term doesn't fit its fact's type, or None. `kind` is "bool", "int" or the tuple of an enum's values."""
    if kind == "bool":
        return None if type(term.value) is bool and term.op in ("==", "!=") else f"{term.name} is true or false"
    if kind == "int":
        return None if type(term.value) is int else f"{term.name} is a number"
    if type(term.value) is not str or term.op not in ("==", "!="):
        return f"{term.name} is one of {', '.join(kind)}, compared with == or !="
    return None if term.value in kind else f"{term.name} is one of {', '.join(kind)}"


def parse_requires(expr: str) -> Requirement:
    """`name`, `not name` or `name op value`, joined by `or`. Raises DefinitionError on bad grammar, an unknown fact or
    a value of the wrong type; whether a <state> or <entry> exists is for check()."""
    def bad(text):
        raise DefinitionError([Problem("requires", f"{expr!r}: {text}")])
    if not isinstance(expr, str):
        bad("must be text")
    tokens, at = [], 0
    while at < len(expr):
        if not expr[at:].strip():
            break
        m = _TOKEN.match(expr, at)
        if not m:
            bad(f"can't read {expr[at:].strip()[:20]!r}")
        tokens.append(m.group(1))
        at = m.end()
    groups, current = [], []
    for token in tokens:
        if token == "or":
            groups.append(current)
            current = []
        else:
            current.append(token)
    groups.append(current)
    terms = []
    for group in groups:
        if len(group) == 1 and group[0] not in _RESERVED and group[0] not in OPS:
            term = Term(group[0], "==", True)
        elif len(group) == 2 and group[0] == "not" and group[1] not in _RESERVED:
            term = Term(group[1], "==", False)
        elif len(group) == 3 and group[1] in OPS and group[0] not in _RESERVED and group[2] not in OPS:
            word = group[2]
            if not (re.fullmatch(r"-?[0-9]+", word) or word in ("true", "false") or _WORD.fullmatch(word)):
                bad(f"{word!r} isn't a value")
            term = Term(group[0], group[1], _value(word))
        else:
            bad("expected `name`, `not name` or `name op value`, joined by `or`")
        kind = fact_type(term.name)
        if kind is None:
            bad(f"{term.name} isn't a known fact")
        if kind != "returns" and (why := _typed(term, kind)):
            bad(why)
        if kind == "returns" and (type(term.value) is not str or term.op not in ("==", "!=")):
            bad(f"{term.name} is compared with == or != to one of its values")
        terms.append(term)
    return Requirement(tuple(terms))


# ---- parse ----

class _Reader:
    def __init__(self):
        self.problems: list[Problem] = []

    def table(self, value, where: str, allowed: tuple[str, ...]) -> dict:
        if not isinstance(value, dict):
            self.problems.append(Problem(where, "must be a table"))
            return {}
        for key in value:
            if key not in allowed:
                self.problems.append(Problem(where, f"unknown key {key!r}"))
        return value

    def get(self, t: dict, key: str, where: str, kind, default, choices=None, pattern=None):
        """kind: str, bool, int or list (of str). A bad value is a problem and gives the default."""
        if key not in t:
            return default
        value, here = t[key], f"{where}.{key}"
        if kind is list:
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                self.problems.append(Problem(here, "must be a list of text"))
                return default
            for v in value:
                if (choices is not None and v not in choices) or (pattern is not None and not pattern.fullmatch(v)):
                    self.problems.append(Problem(here, f"{v!r} isn't allowed here"))
            if len(set(value)) != len(value):
                self.problems.append(Problem(here, "names an item twice"))
            return tuple(value)
        if type(value) is not kind:
            self.problems.append(Problem(here, f"must be {kind.__name__}"))
            return default
        if (choices is not None and value not in choices) or (pattern is not None and not pattern.fullmatch(value)):
            self.problems.append(Problem(here, f"{value!r} isn't one of the allowed values"))
            return default
        return value


def parse(text: str) -> Definition:
    try:
        top = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, TypeError) as e:
        raise DefinitionError([Problem("text", f"not valid TOML: {e}")]) from None
    r = _Reader()
    r.table(top, "workflow", ("schema", "name", "initial", "judge", "status", "state", "launch", "start"))
    if top.get("schema") != SCHEMA or type(top.get("schema")) is not int:
        r.problems.append(Problem("workflow.schema", f"must be {SCHEMA}"))
    name = r.get(top, "name", "workflow", str, "", pattern=_NAME)
    initial = r.get(top, "initial", "workflow", str, "", pattern=_ID)
    judge = r.get(top, "judge", "workflow", str, None, pattern=_NAME)
    status = r.get(top, "status", "workflow", bool, False)
    for key in ("name", "initial"):
        if key not in top:
            r.problems.append(Problem(f"workflow.{key}", "is missing"))
    raw_states = top.get("state", {})
    if not isinstance(raw_states, dict) or not raw_states:
        r.problems.append(Problem("workflow.state", "needs at least one state"))
        raw_states = {}
    states = {}
    for sid, raw in raw_states.items():
        where = f"state.{sid}"
        if not _ID.fullmatch(sid) or sid in _RESERVED:
            r.problems.append(Problem(where, "a state id is lower-case letters, digits, - and _"))
        t = r.table(raw, where, ("parent", "instructions", "personas", "context", "focus", "final", "initial", "grant", "exit", "manages"))
        states[sid] = State(
            id=sid, parent=r.get(t, "parent", where, str, None), instructions=r.get(t, "instructions", where, str, ""),
            personas=r.get(t, "personas", where, list, (), pattern=_NAME),
            context=r.get(t, "context", where, str, "keep", CONTEXTS), focus=r.get(t, "focus", where, str, ""), final=r.get(t, "final", where, bool, False),
            initial=r.get(t, "initial", where, str, None), grant=_grant(r, t.get("grant"), f"{where}.grant") if "grant" in t else Grant(),
            exits=tuple(_exit(r, e, f"{where}.exit.{i}") for i, e in enumerate(_array(r, t, "exit", where), 1)),
            manages=tuple(_manage(r, m, f"{where}.manages.{i}") for i, m in enumerate(_array(r, t, "manages", where), 1)))
    _structure(r, initial, states)
    launch = _launch(r, top["launch"], "launch") if "launch" in top else None
    starts = tuple(_start(r, t, f"start.{i}") for i, t in enumerate(_array(r, top, "start", "workflow"), 1)) if "start" in top else None
    if r.problems:
        raise DefinitionError(r.problems)
    return Definition(name=name, initial=initial, states=states, judge=judge, status=status, launch=launch, starts=starts)


def _start(r: _Reader, raw, where: str) -> Start:
    t = r.table(raw, where, _START_ORDER)
    for key in ("on", "label"):
        if key not in t:
            r.problems.append(Problem(f"{where}.{key}", "is missing"))
    order = r.get(t, "order", where, int, None)
    return Start(on=r.get(t, "on", where, str, "issue", START_ON), label=r.get(t, "label", where, str, ""),
                 summary=r.get(t, "summary", where, str, ""), id=r.get(t, "id", where, str, None, pattern=_NAME),
                 ceiling=r.get(t, "ceiling", where, str, ""), state=r.get(t, "state", where, str, None, pattern=_ID),
                 lead=r.get(t, "lead", where, bool, False), when_held=r.get(t, "when_held", where, str, "ask", WHEN_HELD),
                 ask_move=r.get(t, "ask_move", where, str, None, pattern=_ID), order=order,
                 verb=r.get(t, "verb", where, str, None, pattern=re.compile(r"[a-z]{2,20}")),
                 when=r.get(t, "when", where, str, None, START_WHEN), needs=r.get(t, "needs", where, str, None, START_NEEDS),
                 asks_describe=r.get(t, "asks_describe", where, bool, False), asks_paths=r.get(t, "asks_paths", where, bool, False),
                 models=r.get(t, "models", where, list, (), pattern=_NAME), efforts=r.get(t, "efforts", where, list, (), pattern=_NAME),
                 prompt=r.get(t, "prompt", where, str, ""))


def start_from(raw) -> Start:
    """One start from a table of its fields, as the editor sends it: checked as the text's own would be."""
    r = _Reader()
    st = _start(r, raw, "start")
    if r.problems:
        raise DefinitionError(r.problems)
    return st


def start_json(st: Start) -> dict:
    """A start's fields, as the editor reads and sends them."""
    return {f: (list(v) if isinstance(v, tuple) else v) for f in _START_ORDER if (v := getattr(st, f)) is not None}


def _launch(r: _Reader, raw, where: str) -> Launch:
    t = r.table(raw, where, _LAUNCH_ORDER)
    drafting = t.get("drafting")
    if "drafting" in t and not (isinstance(drafting, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in drafting.items())):
        r.problems.append(Problem(f"{where}.drafting", "is a table of state and entry names"))
        drafting = None
    return Launch(personas=r.get(t, "personas", where, list, (), pattern=_NAME), result=r.get(t, "result", where, str, "", pattern=_NAME),
                  result_tools=r.get(t, "result_tools", where, list, (), pattern=_TOOL), plan=r.get(t, "plan", where, bool, True),
                  per_repo=r.get(t, "per_repo", where, bool, False), singleton=r.get(t, "singleton", where, str, None, pattern=_NAME),
                  repository=r.get(t, "repository", where, str, None), repo=r.get(t, "repo", where, str, None),
                  roadmap=r.get(t, "roadmap", where, bool, False), asks_wait_for_you=r.get(t, "asks_wait_for_you", where, bool, False),
                  drafting=dict(drafting) if drafting is not None else None, on=r.get(t, "on", where, str, None, START_ON),
                  label=r.get(t, "label", where, str, ""), summary=r.get(t, "summary", where, str, ""),
                  ceiling=r.get(t, "ceiling", where, str, ""), order=r.get(t, "order", where, int, None),
                  models=r.get(t, "models", where, list, (), pattern=_NAME), efforts=r.get(t, "efforts", where, list, (), pattern=_NAME),
                  prompt=r.get(t, "prompt", where, str, ""))


def _array(r: _Reader, t: dict, key: str, where: str) -> list:
    value = t.get(key, [])
    if not isinstance(value, list):
        r.problems.append(Problem(f"{where}.{key}", "must be an array of tables"))
        return []
    return value


def _grant(r: _Reader, raw, where: str) -> Grant:
    t = r.table(raw, where, tuple(f.name for f in fields(Grant)))
    checkout = t.get("checkout")
    if "checkout" in t and not (checkout is False or (isinstance(checkout, str) and checkout in CHECKOUTS)):
        r.problems.append(Problem(f"{where}.checkout", "is false or one of " + ", ".join(c for c in CHECKOUTS if c)))
        checkout = None
    return Grant(access=r.get(t, "access", where, str, None, ACCESS),
                 permission_mode=r.get(t, "permission_mode", where, str, None, PERMISSION_MODES),
                 tools=r.get(t, "tools", where, list, (), pattern=_TOOL),
                 hub_tools=r.get(t, "hub_tools", where, list, (), pattern=_TOOL),
                 asks_first=r.get(t, "asks_first", where, list, (), pattern=_TOOL),
                 checkout=checkout, all_repos=r.get(t, "all_repos", where, bool, None),
                 github=r.get(t, "github", where, list, (), GITHUB))


def _exit(r: _Reader, raw, where: str) -> Exit:
    t = r.table(raw, where, tuple(f.name for f in fields(Exit)))
    for key in ("to", "decided_by"):
        if key not in t:
            r.problems.append(Problem(f"{where}.{key}", "is missing"))
    on = r.get(t, "on", where, list, ())
    for signal in on:
        if signal not in SIGNALS:
            r.problems.append(Problem(f"{where}.on", f"{signal!r} isn't a signal"))
    return Exit(to=r.get(t, "to", where, str, ""), decided_by=r.get(t, "decided_by", where, str, "hand", DECIDERS),
                enter=r.get(t, "enter", where, str, "first", ENTERS), when=r.get(t, "when", where, str, ""),
                requires=r.get(t, "requires", where, list, ()), on=on, move=r.get(t, "move", where, str, "auto", MOVES),
                approve=r.get(t, "approve", where, str, "none", APPROVERS))


def _with_ok(ref: str) -> bool:
    return ref in WITH or any(ref.startswith(p) and _WORD.fullmatch(ref[len(p):]) for p in WITH_PREFIXES)


def _manage(r: _Reader, raw, where: str) -> Manage:
    names = [f.name for f in fields(Manage) if f.name != "with_"] + ["with"]
    t = r.table(raw, where, tuple(names))
    for key in ("name", "persona", "workflow"):
        if key not in t:
            r.problems.append(Problem(f"{where}.{key}", "is missing"))
    refs = r.get(t, "with", where, list, ())
    for ref in refs:
        if not _with_ok(ref):
            r.problems.append(Problem(f"{where}.with", f"{ref!r} isn't a named reference"))
    returns, raw_returns = {}, t.get("returns", {})
    if not isinstance(raw_returns, dict):
        r.problems.append(Problem(f"{where}.returns", "must be a table"))
        raw_returns = {}
    for key in raw_returns:
        if raw_returns[key] == TEXT_LIST:
            if _FIELD.fullmatch(key):
                returns[key] = TEXT_LIST
            else:
                r.problems.append(Problem(f"{where}.returns.{key}", "is a field name"))
            continue
        values = r.get(raw_returns, key, f"{where}.returns", list, None, pattern=_WORD)
        if not _FIELD.fullmatch(key) or not values or any(v in _RESERVED or v.isdigit() for v in values):
            r.problems.append(Problem(f"{where}.returns.{key}", f"is a field name with a list of the values it takes, or {TEXT_LIST!r}"))
        else:
            returns[key] = values
    most = r.get(t, "max", where, int, 1)
    if most < 1:
        r.problems.append(Problem(f"{where}.max", "is at least 1"))
    return Manage(name=r.get(t, "name", where, str, "", pattern=_ID), persona=r.get(t, "persona", where, str, "", pattern=_NAME),
                  workflow=r.get(t, "workflow", where, str, "", pattern=_NAME), on_pr=r.get(t, "on_pr", where, str, "", pattern=_NAME),
                  start=r.get(t, "start", where, str, "auto", STARTS),
                  when=r.get(t, "when", where, str, ""), max=most, reuse=r.get(t, "reuse", where, str, "resume", REUSES),
                  on_exit=r.get(t, "on_exit", where, str, "stop", ON_EXIT), with_=refs, returns=returns)


def _structure(r: _Reader, initial: str, states: dict[str, State]) -> None:
    """What makes the states a tree: parents exist and don't loop, parents name a first child, exits go somewhere."""
    if initial and initial not in states:
        r.problems.append(Problem("workflow.initial", f"{initial!r} isn't a state"))
    children = {sid: [c for c in states.values() if c.parent == sid] for sid in states}
    for s in states.values():
        where = f"state.{s.id}"
        if s.parent is not None and s.parent not in states:
            r.problems.append(Problem(f"{where}.parent", f"{s.parent!r} isn't a state"))
        seen, at = {s.id}, s.parent
        while at in states:
            if at in seen:
                r.problems.append(Problem(f"{where}.parent", "parents go round in a loop"))
                break
            seen.add(at)
            at = states[at].parent
        if children[s.id]:
            if s.final:
                r.problems.append(Problem(where, "a final state holds no states"))
            if s.initial is None or s.initial not in {c.id for c in children[s.id]}:
                r.problems.append(Problem(f"{where}.initial", "a parent names one of its own states as its first"))
        elif s.initial is not None:
            r.problems.append(Problem(f"{where}.initial", "only a parent names a first state"))
        if s.context == "compact" and not s.focus.strip():
            r.problems.append(Problem(f"{where}.focus", "a compacting state names what to keep"))
        elif s.context != "compact" and s.focus:
            r.problems.append(Problem(f"{where}.focus", "only a state with context = \"compact\" has a focus"))
        if s.final and s.exits:
            r.problems.append(Problem(where, "a final state has no exits"))
        for i, e in enumerate(s.exits, 1):
            if e.to not in states:
                r.problems.append(Problem(f"{where}.exit.{i}.to", f"{e.to!r} isn't a state"))
            elif e.enter == "history" and not children[e.to]:
                r.problems.append(Problem(f"{where}.exit.{i}.enter", "history enters a parent state"))
        names = [m.name for m in s.manages]
        if len(set(names)) != len(names):
            r.problems.append(Problem(f"{where}.manages", "names an entry twice"))


# ---- emit ----

def _s(value: str) -> str:
    out = []
    for ch in value:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _v(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _s(value)
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{k} = {_v(v)}" for k, v in value.items()) + " }" if value else "{}"
    return "[" + ", ".join(_v(v) for v in value) + "]"


def _text_value(value: str) -> str:
    """A long text with line breaks as a literal multi-line string, so it reads as it is; anything else as a basic string.
    TOML drops the line break right after the opening quotes, so the text reads back the same."""
    if "\n" in value and "'''" not in value and not value.endswith("'") and not any(
            (ord(c) < 0x20 and c not in "\n\t") or ord(c) == 0x7F for c in value):
        return "'''\n" + value + "'''"
    return _s(value)


def _ordered_lines(obj, order: tuple[str, ...]) -> list[str]:
    out = []
    defaults = {f.name: f.default for f in fields(obj)}
    for key in order:
        value = getattr(obj, key)
        if value is None or (key in defaults and defaults[key] is not MISSING and value == defaults[key]) or value == ():
            continue
        if isinstance(value, dict):
            continue
        out.append(f"{key} = {_text_value(value) if key == 'prompt' else _v(value)}")
    return out


def _lines(obj, skip=(), rename=None) -> list[str]:
    """`key = value` for each required field and each that differs from its default."""
    out = []
    for f in fields(obj):
        value = getattr(obj, f.name)
        default = f.default if f.default is not MISSING else f.default_factory() if f.default_factory is not MISSING else MISSING
        if f.name in skip or value is None or value == default:
            continue
        out.append(f"{(rename or {}).get(f.name, f.name)} = {_v(value)}")
    return out


def emit(d: Definition) -> str:
    out = [f"schema = {d.schema}", f"name = {_s(d.name)}", f"initial = {_s(d.initial)}"]
    if d.judge is not None:
        out.append(f"judge = {_s(d.judge)}")
    if d.status:  # only when set, so a text without it reads back the same
        out.append("status = true")
    if d.starts == ():  # no starts at all, which a text without the key doesn't say
        out.append("start = []")
    if d.launch is not None:
        out += ["", "[launch]", *_ordered_lines(d.launch, _LAUNCH_ORDER)]
        if d.launch.drafting is not None:
            out += ["[launch.drafting]", *(f"{k} = {_s(v)}" for k, v in d.launch.drafting.items())]
    for st in d.starts or ():
        out += ["", "[[start]]", *_ordered_lines(st, _START_ORDER)]
    for s in d.states.values():
        out += ["", f"[state.{s.id}]", *_lines(s, skip=("id", "grant", "exits", "manages"))]
        if grant := _lines(s.grant):
            out += [f"[state.{s.id}.grant]", *grant]
        for e in s.exits:
            out += [f"[[state.{s.id}.exit]]", *_lines(e)]
        for m in s.manages:
            out += [f"[[state.{s.id}.manages]]", *_lines(m, rename={"with_": "with"})]
    return "\n".join(out) + "\n"


# ---- grants ----

def ancestors(d: Definition, state_id: str) -> list[str]:
    """The state and its parents, the state first."""
    chain, at = [], state_id
    while at is not None and at in d.states and at not in chain:
        chain.append(at)
        at = d.states[at].parent
    return chain


def effective(d: Definition, state_id: str) -> Grant:
    """The state's own grant with all its ancestors': lists unioned, ordered keys the widest, checkout the nearest set.
    Every field comes back set: unset ordered keys are their narrowest, an unset checkout is none."""
    chain = ancestors(d, state_id)
    grants = [d.states[s].grant for s in reversed(chain)]  # outermost first, so lists keep the parents' order
    merged = {}
    for key in _SET_KEYS:
        merged[key] = tuple(dict.fromkeys(item for g in grants for item in getattr(g, key)))
    for key, order in _ORDERED.items():
        merged[key] = max((getattr(g, key) for g in grants if getattr(g, key) is not None), key=order.index, default=_LOWEST[key])
    merged["checkout"] = next((g.checkout for g in reversed(grants) if g.checkout is not None), False)
    return Grant(**merged)


# ---- managed sessions' grants (FR-043, FR-023) ----

READ_CHECKOUTS = ("default", "pr")  # detached: a session there can't push, so it fits under an owner with any checkout


def managed_of(d: Definition, state_id: str) -> list[tuple[str, Manage]]:
    """The `manages` entries that hold in a state, its own first, then each parent's (FR-045), with the state that names
    each. A child's entry of the same name stands for its parent's."""
    seen, out = set(), []
    for sid in ancestors(d, state_id):
        for m in d.states[sid].manages:
            if m.name not in seen:
                seen.add(m.name)
                out.append((sid, m))
    return out


def _checkout_fits(child, owner) -> bool:
    child, owner = (False if v is None else v for v in (child, owner))
    return child is False or child == owner or (child in READ_CHECKOUTS and owner is not False)


def beyond(child: Grant, owner: Grant) -> dict[str, tuple]:
    """What a managed session's grant holds that its owner's effective grant doesn't, per key, as Change.adds lists it.
    Lists by item, ordered keys by level; a checkout fits when it is none, the owner's, or a detached one under an owner
    that has a checkout at all."""
    out = {}
    for key in _SET_KEYS:
        if extra := tuple(x for x in getattr(child, key) if x not in getattr(owner, key)):
            out[key] = extra
    for key, order in _ORDERED.items():
        c, o = (_LOWEST[key] if v is None else v for v in (getattr(child, key), getattr(owner, key)))
        if order.index(c) > order.index(o):
            out[key] = (c,)
    if not _checkout_fits(child.checkout, owner.checkout):
        out["checkout"] = (child.checkout,)
    return out


def cap(child: Grant, owner: Grant, allowed: dict | None = None) -> Grant:
    """A managed session's grant as it runs (FR-043): its own, each key no wider than its owner's, unless `allowed` (what an
    approval above the owner let it have, as `beyond` gives it) says so. Lists keep the child's order; ordered keys take the
    lower; a checkout that doesn't fit becomes none."""
    allowed = allowed or {}
    out = {}
    for key in _SET_KEYS:
        out[key] = tuple(x for x in getattr(child, key) if x in getattr(owner, key) or x in allowed.get(key, ()))
    for key, order in _ORDERED.items():
        c, o = (_LOWEST[key] if v is None else v for v in (getattr(child, key), getattr(owner, key)))
        out[key] = c if c in allowed.get(key, ()) else min(c, o, key=order.index)
    fits = _checkout_fits(child.checkout, owner.checkout) or child.checkout in allowed.get("checkout", ())
    out["checkout"] = child.checkout if fits else False
    return Grant(**out)


def fits(extra: dict, holder: Grant) -> bool:
    """Whether what `beyond` gave (a managed session's items over its owner's) is all within `holder`'s grant: what a
    session above may approve, as it may grant only what it holds itself (FR-051)."""
    wanted = {key: tuple(extra.get(key, ())) for key in _SET_KEYS}
    for key in _ORDERED:
        wanted[key] = extra[key][0] if extra.get(key) else None
    wanted["checkout"] = extra["checkout"][0] if extra.get("checkout") else False
    return not beyond(Grant(**wanted), holder)


def union(*grants: Grant) -> Grant:
    """Every item any of them holds: lists joined, ordered keys the widest, the first set checkout."""
    merged = {key: tuple(dict.fromkeys(x for g in grants for x in getattr(g, key))) for key in _SET_KEYS}
    for key, order in _ORDERED.items():
        merged[key] = max((getattr(g, key) for g in grants if getattr(g, key) is not None), key=order.index, default=_LOWEST[key])
    merged["checkout"] = next((g.checkout for g in grants if g.checkout not in (None, False)), False)
    return Grant(**merged)


@dataclass(frozen=True)
class Change:
    """Per grant key, the items added, removed and kept. An ordered key that widens adds its new value; one that narrows
    removes its old one. A checkout that changes adds the new one (removes the old one), unless the new one is none."""
    adds: dict[str, tuple]
    removes: dict[str, tuple]
    keeps: dict[str, tuple]

    @property
    def widens(self) -> bool:
        return bool(self.adds)


def compare(a: Grant, b: Grant) -> Change:
    adds, removes, keeps = {}, {}, {}

    def put(target, key, items):
        if items:
            target[key] = tuple(items)
    for key in _SET_KEYS:
        old, new = getattr(a, key), getattr(b, key)
        put(adds, key, [x for x in new if x not in old])
        put(removes, key, [x for x in old if x not in new])
        put(keeps, key, [x for x in new if x in old])
    for key, order in _ORDERED.items():
        old, new = (_LOWEST[key] if v is None else v for v in (getattr(a, key), getattr(b, key)))
        if old == new:
            put(keeps, key, [old])
        elif order.index(new) > order.index(old):
            put(adds, key, [new])
        else:
            put(removes, key, [old])
    old, new = (False if v is None else v for v in (a.checkout, b.checkout))
    if old == new:
        put(keeps, "checkout", [old])
    else:
        if new is not False:
            put(adds, "checkout", [new])
        if old is not False:
            put(removes, "checkout", [old])
    return Change(adds, removes, keeps)


# ---- exits and checks ----

def exits_of(d: Definition, state_id: str) -> list[Exit]:
    """The exits tried in a state, in order: its own, then each ancestor's, the nearest first (FR-005)."""
    return [e for s in ancestors(d, state_id) for e in d.states[s].exits]


def _owners(d: Definition, state_id: str) -> list[tuple[str, int, Exit]]:
    """Each exit tried in a state, in order, with the state that owns it and its 1-based place there."""
    return [(s, i, e) for s in ancestors(d, state_id) for i, e in enumerate(d.states[s].exits, 1)]


def _leaf(d: Definition, state_id: str) -> str:
    while d.states[state_id].initial is not None:
        state_id = d.states[state_id].initial
    return state_id


def _is_parent(d: Definition, state_id: str) -> bool:
    return d.states[state_id].initial is not None


def _is_pr_open(req: Requirement) -> bool:
    """A requirement that holds only while a pull request is open: `pr.open` alone, not one side of an `or`."""
    return len(req.terms) == 1 and req.terms[0] in (Term("pr.open", "==", True), Term("pr.open", "!=", False))


def _counter_states(req: Requirement) -> set[str]:
    return {t.name.split(".")[1] for t in req.terms if t.name.split(".")[0] in COUNTERS and t.name.count(".") == 1}


def _sccs(nodes: list[str], edges: dict[str, set[str]]) -> list[list[str]]:
    """Strongly connected components that hold a cycle (Tarjan, iterative enough for small machines)."""
    index, low, stack, on, out, counter = {}, {}, [], set(), [], [0]

    def visit(v):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in edges.get(v, ()):
            if w not in nodes:
                continue
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1 or v in edges.get(v, ()):
                out.append(comp)
    for v in nodes:
        if v not in index:
            visit(v)
    return out


def start_state(d: Definition, start: Start) -> str:
    """The leaf a session of this start begins in: its state, or the workflow's initial one, down its first states."""
    return _leaf(d, start.state if start.state is not None else d.initial)


def writes_on_item(grant: Grant) -> list[str]:
    """What in an effective grant can write on the item a session works on (FR-104), in words; empty if nothing can. Full access
    is the maintainer's own rights. A GitHub capability beyond the reads, or a hub tool (listed or asked first) other than the
    read-only ones and those that only reach the hub, writes. A result a person applies isn't the session writing: the person's
    press is."""
    out = []
    if grant.access == "full":
        out.append("full access")
    out += [f"GitHub {c}" for c in grant.github if c not in READ_GITHUB]
    out += [t for t in dict.fromkeys((*grant.hub_tools, *grant.asks_first)) if t not in QUIET_HUB_TOOLS]
    return out


def prompt_problem(prompt: str) -> str | None:
    """Why a start's prompt can't be filled in, or None. Only {repo}, {number} and {checkout}, with {{ and }} for braces."""
    import string
    try:
        parts = list(string.Formatter().parse(prompt))
    except ValueError as e:
        return f"a brace doesn't close or open ({e}): write {{{{ and }}}} for a brace"
    for _text, field_name, spec, conversion in parts:
        if field_name is None:
            continue
        if field_name not in PROMPT_FIELDS or spec or conversion:
            return f"{{{field_name}}} isn't one of {', '.join('{' + f + '}' for f in PROMPT_FIELDS)}: write {{{{ and }}}} for a brace"
    return None


def effective_starts(d: Definition, inherited: tuple[Start, ...] | None) -> tuple[Start, ...]:
    """The starts in force: the text's own, or with none named (None) those `inherited` gives, the file's."""
    return d.starts if d.starts is not None else (inherited or ())


def start_id(d: Definition, start: Start, place: int = 0) -> str:
    """A start's id is the workflow's name unless it names its own, so only one start of a workflow may leave it out."""
    return start.id or d.name


def check_starts(d: Definition, starts: tuple[Start, ...]) -> list[Finding]:
    """FR-101 and FR-104 within one workflow. The library checks labels and leads across all of them."""
    found: list[Finding] = []
    problem = lambda where, text: found.append(Finding("problem", where, text))  # noqa: E731
    seen_labels, seen_ids, leads = {}, {}, {}
    for i, st in enumerate(starts, 1):
        where = f"start.{i}"
        if not st.label.strip():
            problem(f"{where}.label", "a start has a button label")
        if st.state is not None and st.state not in d.states:
            problem(f"{where}.state", f"{st.state!r} isn't a state")
            continue
        leaf = start_state(d, st)
        # A one-state workflow's only state is final (FR-010) and is where its sessions start; a state named for a start isn't.
        if st.state is not None and d.states[leaf].final:
            problem(f"{where}.state", f"{leaf} is final: a session would start with nothing to do")
        key = (st.on, st.label.strip().lower())
        if key in seen_labels:
            problem(f"{where}.label", f"start {seen_labels[key]} has the label {st.label!r} on a {st.on} too")
        seen_labels.setdefault(key, i)
        sid = start_id(d, st, i)
        if sid in seen_ids:
            problem(f"{where}.id", f"start {seen_ids[sid]} has the id {sid!r} too: each start after one without an id names its own")
        seen_ids.setdefault(sid, i)
        if st.lead:
            if st.on in leads:
                problem(f"{where}.lead", f"start {leads[st.on]} leads for a {st.on} already")
            leads.setdefault(st.on, i)
        if st.prompt and (why := prompt_problem(st.prompt)):
            problem(f"{where}.prompt", why)
        if st.when_held == "beside" and (writes := writes_on_item(effective(d, leaf))):
            problem(f"{where}.when_held", f"runs beside a holding instance, but {leaf}'s grant can write on the item "
                    f"({', '.join(writes[:4])}): it asks the owner or is hidden (FR-104)")
        if st.ask_move is not None and st.when_held != "ask":
            problem(f"{where}.ask_move", "only a start that asks the owner names a move to ask for")
    if d.launch is not None and d.launch.prompt and (why := prompt_problem(d.launch.prompt)):
        problem("launch.prompt", why)
    return found


def check(d: Definition) -> list[Finding]:
    """Problems stop a save or an approval; marks only show (FR-008)."""
    found: list[Finding] = []
    problem = lambda where, text: found.append(Finding("problem", where, text))  # noqa: E731
    found += check_starts(d, d.starts or ())
    leaves = [s for s in d.states if not _is_parent(d, s)]
    parsed: dict[tuple[str, int], list[Requirement]] = {}

    for s in d.states.values():
        returns = {m.name: m.returns for _sid, m in managed_of(d, s.id)}  # the entries in force there: a child's stands for its parent's
        for i, e in enumerate(s.exits, 1):
            where = f"state.{s.id}.exit.{i}"
            reqs = []
            for expr in e.requires:
                try:
                    req = parse_requires(expr)
                except DefinitionError as err:
                    problem(f"{where}.requires", err.problems[0].text)
                    continue
                for t in req.terms:
                    kind = t.name.split(".")
                    if kind[0] in COUNTERS and len(kind) == 2 and kind[1] not in d.states:
                        problem(f"{where}.requires", f"{t.name}: {kind[1]!r} isn't a state")
                    if kind[0] in ("started", "when") and len(kind) == 2 and kind[1] not in returns:
                        problem(f"{where}.requires", f"{t.name}: no managed entry here is named {kind[1]}")
                    if kind[0] == "managed" and len(kind) == 3:
                        values = returns.get(kind[1], {}).get(kind[2])
                        if values is None:
                            problem(f"{where}.requires", f"{t.name}: no managed entry here returns {kind[1]}.{kind[2]}")
                        elif values == TEXT_LIST:
                            problem(f"{where}.requires", f"{t.name} is text for the owner to read, not a fact")
                        elif t.value not in values:
                            problem(f"{where}.requires", f"{t.name} is one of {', '.join(values)}")
                reqs.append(req)
            parsed[(s.id, i)] = reqs
            if e.decided_by == "judge" and not e.when.strip():
                problem(where, "a judge decides it, so it needs a `when` question")
            if e.decided_by in ("facts", "counter") and not e.requires:
                problem(where, "decided by facts, so it needs `requires`")
            if e.decided_by == "counter" and not any(_counter_states(r) for r in reqs):
                problem(where, "decided by a counter, so a `requires` tests rounds., time. or tokens.")
            if e.decided_by != "hand" and e.move == "auto" and not e.on:
                problem(where, "names no signal in `on`, so it is never tried")

    # Reachability over states: entering a state enters its ancestors and its first-child chain.
    reached, todo = set(), [d.initial]
    while todo:
        target = todo.pop()
        for sid in {*ancestors(d, _leaf(d, target)), *ancestors(d, target)} - reached:
            reached.add(sid)
            todo += [e.to for e in d.states[sid].exits]
    for sid in d.states:
        if sid not in reached:
            problem(f"state.{sid}", f"can't be reached from {d.initial!r}")

    for sid in leaves:
        if not d.states[sid].final and not exits_of(d, sid):
            problem(f"state.{sid}", "isn't final and has no exit, its own or a parent's")

    # Cycles over leaf states, moves by hand left out. A state with an exit that tests a counter of a state on the cycle
    # (or a parent of one) bounds every cycle through it; whatever cycle is left without one never has to end.
    # A move back to where it was may land on any state under the target.
    edges = {sid: {leaf for e in exits_of(d, sid) if e.decided_by != "hand"
                   for leaf in ([lf for lf in leaves if e.to in ancestors(d, lf)] if e.enter == "history" else [_leaf(d, e.to)])}
             for sid in leaves}

    def bounded(sid, comp):
        scope = {a for c in comp for a in ancestors(d, c)}
        return any(_counter_states(r) & scope for owner, i, _e in _owners(d, sid) for r in parsed.get((owner, i), ()))
    pending = _sccs(leaves, edges)
    while pending:
        comp = pending.pop()
        keep = [c for c in comp if not bounded(c, comp)]
        if len(keep) == len(comp):
            problem(f"state.{sorted(comp)[0]}", f"the cycle {' → '.join(sorted(comp))} has no exit that tests a counter")
        else:
            pending += _sccs(keep, edges)

    # FR-012: a session that may push can't leave the states that let it without a pull request. An exit from a state whose
    # effective grant has `push` to one whose grant hasn't (a final state aside) needs a `requires` that is `pr.open` alone.
    # A move by hand is the maintainer's and checks no `requires`, so it isn't held to this.
    pushing = {sid for sid in leaves if "push" in effective(d, sid).github}
    for sid in sorted(pushing):
        for owner, place, e in _owners(d, sid):
            if e.decided_by == "hand" or any(_is_pr_open(r) for r in parsed.get((owner, place), ())):
                continue
            targets = [lf for lf in leaves if e.to in ancestors(d, lf)] if e.enter == "history" else [_leaf(d, e.to)]
            if any(t not in pushing and not d.states[t].final for t in targets):
                where = f"state.{owner}.exit.{place}"
                if not any(f.where == where and "pr.open" in f.text for f in found):
                    problem(where, "leaves the states that may push without a pull request: it requires pr.open (FR-012)")

    # Shadowed exits: an earlier exit decided by facts alone, moving on its own, whose requirements are among a later
    # exit's and whose signals cover the later one's, always moves first.
    # A parent's exit counts only when it is shadowed in every state under it: a child may override it on purpose.
    shadowed: dict[tuple[str, int], dict[str, str]] = {}
    for sid in leaves:
        tried = _owners(d, sid)
        for j, (owner_j, place_j, later) in enumerate(tried):
            if later.decided_by == "hand" or later.move == "on-request":  # tried only by hand or on a request, never after those
                continue
            req_j = {frozenset(r.terms) for r in parsed.get((owner_j, place_j), ())}
            for owner_i, place_i, earlier in tried[:j]:
                if earlier.decided_by not in ("facts", "counter") or earlier.move != "auto" or not earlier.requires:
                    continue
                req_i = parsed.get((owner_i, place_i), ())
                if len(req_i) == len(earlier.requires) and {frozenset(r.terms) for r in req_i} <= req_j and set(later.on) <= set(earlier.on):
                    shadowed.setdefault((owner_j, place_j), {})[sid] = earlier.to
                    break
    for (owner, place), where in shadowed.items():
        if set(where) >= {leaf for leaf in leaves if owner in ancestors(d, leaf)}:
            problem(f"state.{owner}.exit.{place}", f"it never moves: in {', '.join(sorted(where))} the exit to "
                    f"{', '.join(sorted(set(where.values())))} before it holds whenever it does")

    for s in d.states.values():
        for item in s.grant.github:
            if item in SENSITIVE:
                found.append(Finding("mark", f"state.{s.id}.grant.github", f"{item}: {SENSITIVE[item]}"))
        for key in ("hub_tools", "asks_first"):
            for item in getattr(s.grant, key):
                if item in SENSITIVE_HUB_TOOLS:
                    found.append(Finding("mark", f"state.{s.id}.grant.{key}", f"{item}: {SENSITIVE_HUB_TOOLS[item]}"))
        if s.grant.access == "full":
            found.append(Finding("mark", f"state.{s.id}.grant.access",
                                 "full: runs with the maintainer's own rights, so the grant is guarded, not enforced"))
    return found


# ---- outline diff ----

@dataclass(frozen=True)
class Row:
    """One row of the outline: a state (exit None) or one of its own exits. kind: same, added, removed, changed (fields
    names what) or moved (only the exit's place among the state's exits changed). exit is its 1-based place, in b unless
    removed; was is its place in a, for an exit row that is in both."""
    kind: str
    state: str
    exit: int | None = None
    to: str | None = None
    fields: tuple[str, ...] = ()
    was: int | None = None


def _diff_fields(x, y, skip=()) -> tuple[str, ...]:
    return tuple(f.name for f in fields(x) if f.name not in skip and getattr(x, f.name) != getattr(y, f.name))


def _rising(seq: list[int]) -> set[int]:
    """Positions of one longest rising run through seq: the exits that kept their order."""
    best = [[] for _ in seq]
    for i, v in enumerate(seq):
        best[i] = max((best[j] for j in range(i) if seq[j] < v), key=len, default=[]) + [i]
    return set(max(best, key=len, default=[]))


def _exit_rows(sid: str, a: tuple[Exit, ...], b: tuple[Exit, ...]) -> list[Row]:
    pairs, free_a = {}, list(range(len(a)))
    for match in (lambda x, y: x == y, lambda x, y: x.to == y.to):
        for j, y in enumerate(b):
            if j in pairs:
                continue
            i = next((i for i in free_a if match(a[i], y)), None)
            if i is not None:
                pairs[j] = i
                free_a.remove(i)
    matched = sorted(pairs)
    kept = {matched[k] for k in _rising([pairs[j] for j in matched])}
    rows = []
    for j, y in enumerate(b):
        if j not in pairs:
            rows.append(Row("added", sid, j + 1, y.to))
            continue
        changed = _diff_fields(a[pairs[j]], y) + (() if j in kept else ("order",))
        kind = "same" if not changed else "moved" if changed == ("order",) else "changed"
        rows.append(Row(kind, sid, j + 1, y.to, changed if kind == "changed" else (), pairs[j] + 1))
    rows += [Row("removed", sid, i + 1, a[i].to) for i in free_a]
    return rows


def starts_diff(a: Definition, b: Definition, inherited: tuple[Start, ...] | None = None) -> list[dict]:
    """The starts, one row each, matched by id (the workflow's name for one without): same, added, removed or changed (the
    fields that differ, a prompt among them). With none named, a text has the file's (`inherited`)."""
    def keyed(d):
        return {start_id(d, st): st for st in effective_starts(d, inherited)}
    x, y = keyed(a), keyed(b)
    rows = []
    for sid in [*y, *(k for k in x if k not in y)]:
        old, new = x.get(sid), y.get(sid)
        if old is None or new is None:
            rows.append({"kind": "added" if old is None else "removed", "id": sid, "label": (new or old).label, "on": (new or old).on, "fields": []})
            continue
        changed = [f for f in _START_ORDER if getattr(old, f) != getattr(new, f)]
        rows.append({"kind": "changed" if changed else "same", "id": sid, "label": new.label, "on": new.on, "fields": changed,
                     **({"prompt": {"before": old.prompt, "after": new.prompt}} if "prompt" in changed else {})})
    return rows


def outline_diff(a: Definition, b: Definition) -> list[Row]:
    """State by state, exit by exit (FR-063). States in b's order, a state b dropped after the one it followed in a."""
    order = list(b.states)
    for k, sid in enumerate(a.states):
        if sid not in b.states:
            before = next((p for p in reversed(list(a.states)[:k]) if p in order), None)
            order.insert(order.index(before) + 1 if before else 0, sid)
    rows = []
    for sid in order:
        x, y = a.states.get(sid), b.states.get(sid)
        if x is None or y is None:
            rows.append(Row("added" if x is None else "removed", sid))
            rows += [Row("added" if x is None else "removed", sid, i, e.to) for i, e in enumerate((y or x).exits, 1)]
            continue
        changed = _diff_fields(x, y, skip=("exits",))
        rows.append(Row("changed" if changed else "same", sid, fields=changed))
        rows += _exit_rows(sid, x.exits, y.exits)
    return rows
