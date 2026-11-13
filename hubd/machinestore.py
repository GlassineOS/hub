# SPDX-License-Identifier: GPL-2.0-or-later
"""Saved versions of the workflows, the editor's ops and the definition-change decision (spec 012, FR-001, FR-008, FR-009,
FR-060 to FR-063).

**The store.** A version is a file that never changes once written: `workflows/<scope>/<name>/v<N>.toml` under hubd's state
folder, beside a `v<N>.json` that says who saved it, when, and from what. A scope is `org`, or `<owner>__<repo>` for one
repository's override. The file under agents/workflows is version 0 of the organisation's, and read-only. A session on a
repository takes that repository's newest override, else the organisation's newest saved version, else the file
(`resolve`). A save parses and checks the text, refuses it on a problem or if a newer version was saved since the one the
editor started from, and writes the next number with a link, which fails if the name is taken: two saves can't share a
number, and nothing overwrites a version. A session takes the new version at its next move (instances.move's `latest`).

**Who changes one.** Only the maintainer, with a login: `workflow.save` in the editor, or approving a `workflow.change`
card in Needs you, which `workflow.propose` makes. The tool server has no op here (a Workflow author's drafts, in drafts.py, save nothing). A sensitive item (FR-034) or full access
is marked on the card and in the editor; the mark adds no rule.

**Replay** (FR-009) runs a definition over a past session's machine log, without a model: its exits decided by facts and
counters are evaluated on the facts the log kept, and an exit a judge decides takes the verdict the judge gave then, when the
same question was asked of it. The log keeps only the facts the exits of the time tested, so a fact it hasn't is "can't
tell", never "fails". Rounds are counted by the replay's own moves. Evidence quotes are left out: they can be an outsider's.
"""
from __future__ import annotations

import dataclasses
import difflib
import json
import logging
import os
import re
import secrets
import time
from pathlib import Path

from . import machine
from .instances import _enter, version_of
from .machine import Definition, DefinitionError

log = logging.getLogger("hubd.machinestore")

ORG = "org"
OWNER = "GlassineOS"
MAX_TEXT = 128 * 1024
MAX_NOTE = 2000
_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_REPO = re.compile(r"\.?[A-Za-z0-9_][A-Za-z0-9._-]{0,99}")
_FILE = re.compile(r"v([1-9][0-9]{0,6})\.toml")
OPS = ("workflow.list", "workflow.get", "workflow.check", "workflow.diff", "workflow.replay", "workflow.save",
       "workflow.propose", "workflow.reorder", "workflow.start")


class StoreError(Exception):
    """A request about the saved versions that can't be done; the message goes back to the caller."""


def scope_of(repo: str | None) -> str:
    if repo is None:
        return ORG
    if not isinstance(repo, str) or not _REPO.fullmatch(repo) or ".." in repo:
        raise StoreError("not a repository name")
    return f"{OWNER}__{repo}"


def repo_of(scope) -> str | None:
    """The repository a scope overrides for, None for the organisation's. Refuses anything else."""
    if scope == ORG:
        return None
    owner, sep, repo = scope.partition("__") if isinstance(scope, str) else ("", "", "")
    if not sep or owner != OWNER or not _REPO.fullmatch(repo) or ".." in repo:
        raise StoreError(f"a scope is {ORG!r} or {OWNER}__<repository>")
    return repo


def _name(name) -> str:
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise StoreError("not a workflow name")
    return name


class Store:
    """`defaults`: workflow name -> the text of its file, which is the organisation's version 0."""

    def __init__(self, root: Path, defaults: dict[str, str], clock=time.time):
        self.root = Path(root)
        self.defaults = dict(defaults)
        self.clock = clock

    scope_of = staticmethod(scope_of)

    def _dir(self, name: str, scope: str) -> Path:
        repo_of(scope)
        return self.root / scope / _name(name)

    def numbers(self, name: str, scope: str) -> list[int]:
        folder = self._dir(name, scope)
        try:
            found = [int(m.group(1)) for p in folder.iterdir() if (m := _FILE.fullmatch(p.name))]
        except FileNotFoundError:
            found = []
        return sorted(found)

    def text(self, name: str, scope: str, number: int) -> str:
        if name not in self.defaults:
            raise StoreError(f"there is no workflow {name!r}")
        if not isinstance(number, int) or isinstance(number, bool) or number < 0:
            raise StoreError("a version is a whole number")
        if number == 0:
            if scope != ORG:
                raise StoreError("a repository's overrides start at v1")
            return self.defaults[name]
        try:
            return (self._dir(name, scope) / f"v{number}.toml").read_text()
        except FileNotFoundError:
            raise StoreError(f"{name} has no v{number} here") from None

    def about(self, name: str, scope: str, number: int) -> dict:
        if number == 0:
            return {"v": 0, "who": None, "at": None, "note": "the file under agents/workflows", "default": True}
        try:
            meta = json.loads((self._dir(name, scope) / f"v{number}.json").read_text())
        except (OSError, ValueError):
            meta = {}
        return {"v": number, "who": meta.get("who"), "at": meta.get("at"), "note": meta.get("note"), "base": meta.get("base"),
                "decision": meta.get("decision"), "default": False}

    def latest(self, name: str, scope: str) -> tuple[int, str] | None:
        """The newest version in this scope: for the organisation the file (v0) when nothing is saved; None for a repository
        with no override."""
        numbers = self.numbers(name, scope)
        if numbers:
            return numbers[-1], self.text(name, scope, numbers[-1])
        return (0, self.defaults[name]) if scope == ORG and name in self.defaults else None

    def latest_number(self, name: str, scope: str) -> int:
        found = self.latest(name, scope)
        return found[0] if found else 0

    def overrides(self, repo: str) -> dict[str, str]:
        """A repository's newest override of each workflow that has one."""
        scope = scope_of(repo)
        out = {}
        for name in self.defaults:
            found = self.latest(name, scope)
            if found:
                out[name] = found[1]
        return out

    def scopes(self, name: str) -> list[str]:
        """The organisation, and each repository with an override of this workflow."""
        out = [ORG]
        try:
            folders = sorted(p.name for p in self.root.iterdir() if p.is_dir() and p.name != ORG)
        except FileNotFoundError:
            folders = []
        for scope in folders:
            try:
                repo_of(scope)
            except StoreError:
                continue
            if self.numbers(name, scope):
                out.append(scope)
        return out

    def resolve(self, name: str, repo: str | None = None) -> dict:
        """Which version a session on `repo` runs: its override, else the organisation's newest, else the file."""
        if repo is not None and (found := self.latest(name, scope_of(repo))):
            return {"scope": scope_of(repo), "v": found[0], "text": found[1]}
        n, text = self.latest(name, ORG)
        return {"scope": ORG, "v": n, "text": text}

    def known_versions(self, name: str) -> dict[str, tuple[str, int]]:
        """Every version this workflow has had here, by its hash: (scope, number)."""
        out = {version_of(self.defaults[name]): (ORG, 0)} if name in self.defaults else {}
        for scope in self.scopes(name):
            for n in self.numbers(name, scope):
                out.setdefault(version_of(self.text(name, scope, n)), (scope, n))
        return out

    def save(self, name: str, scope: str, text: str, base, who: str | None, note: str | None = None, decision: str | None = None) -> dict:
        """Writes v<base+1>, if base is the newest version in the scope. The caller has checked the text."""
        if name not in self.defaults:
            raise StoreError(f"there is no workflow {name!r}")
        if not isinstance(base, int) or isinstance(base, bool):
            raise StoreError("base_version is the version the change starts from")
        newest = self.latest_number(name, scope)
        if base != newest:
            raise StoreError(f"v{newest} was saved since v{base}, which this change starts from: open v{newest} and make it again")
        folder = self._dir(name, scope)
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        number = newest + 1
        meta = {"who": who, "at": self.clock(), "note": note, "base": base, "decision": decision, "version": version_of(text)}
        self._create(folder / f"v{number}.json", json.dumps(meta))  # first, so a version is never there without who saved it
        try:
            self._create(folder / f"v{number}.toml", text)
        except BaseException:
            (folder / f"v{number}.json").unlink(missing_ok=True)
            raise
        log.info("workflow %s v%d saved for %s by %s", name, number, scope, who)
        return {"v": number, "version": version_of(text), "scope": scope}

    @staticmethod
    def _create(path: Path, text: str) -> None:
        """Written whole to a scratch file, then linked to its name: a name that is taken fails, and is never overwritten."""
        scratch = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
        fd = os.open(scratch, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(scratch, 0o400)
            try:
                os.link(scratch, path)
            except FileExistsError:
                raise StoreError(f"{path.stem} was saved meanwhile: open it and make the change again") from None
        finally:
            scratch.unlink(missing_ok=True)


# ---- what the editor shows of a definition ----

_LIST_KEYS = ("tools", "hub_tools", "asks_first", "github")
_LEVEL_KEYS = ("access", "permission_mode", "all_repos", "checkout")


def _sensitive(key: str, item) -> str:
    if key == "github":
        return machine.SENSITIVE.get(item, "")
    if key in ("hub_tools", "asks_first"):
        return machine.SENSITIVE_HUB_TOOLS.get(item, "")
    if key == "access" and item == "full":
        return "runs with the maintainer's own rights: guarded, not limited"
    return ""


def grant_rows(d: Definition, sid: str) -> list[dict]:
    """The state's effective grant, each item with where it comes from: the state itself (`from` None) or the nearest parent
    that sets it, and its sensitive mark."""
    chain = machine.ancestors(d, sid)
    eff = machine.effective(d, sid)
    rows = []
    for key in _LIST_KEYS:
        for item in getattr(eff, key):
            owner = next((s for s in chain if item in getattr(d.states[s].grant, key)), sid)
            rows.append({"key": key, "item": item, "from": None if owner == sid else owner, "sensitive": _sensitive(key, item)})
    for key in _LEVEL_KEYS:
        value = getattr(eff, key)
        owner = next((s for s in chain if getattr(d.states[s].grant, key) is not None), None)
        rows.append({"key": key, "item": value, "from": None if owner in (sid, None) else owner, "set": owner is not None,
                     "sensitive": _sensitive(key, value)})
    return rows


def _exit_json(e: machine.Exit) -> dict:
    return {k: list(v) if isinstance(v, tuple) else v for k, v in dataclasses.asdict(e).items()}


def _leaf(d: Definition, sid: str) -> str:
    return _enter(d, sid, {}, "first")


def outline(d: Definition, inherited=None) -> dict:
    """The definition as the editor's outline and inspector read it: states in the order the text lists them."""
    states = []
    for s in d.states.values():
        mine = machine.effective(d, s.id)
        exits = []
        for i, e in enumerate(s.exits, 1):
            target = _leaf(d, e.to) if e.to in d.states else None
            change = machine.compare(mine, machine.effective(d, target)) if target else None
            exits.append({**_exit_json(e), "place": i, "widens": bool(change and change.widens),
                          "adds": {k: list(v) for k, v in change.adds.items()} if change else {}})
        states.append({"id": s.id, "parent": s.parent, "initial": s.initial, "final": s.final, "personas": list(s.personas),
                       "instructions": s.instructions, "context": s.context, "focus": s.focus,
                       "depth": len(machine.ancestors(d, s.id)) - 1, "path": list(reversed(machine.ancestors(d, s.id))),
                       "grant": grant_rows(d, s.id), "exits": exits,
                       "inherited": [{**_exit_json(e), "from": owner, "place": i} for owner in machine.ancestors(d, s.id)[1:]
                                     for i, e in enumerate(d.states[owner].exits, 1)],
                       "manages": [{**{k: (list(v) if isinstance(v, tuple) else v) for k, v in dataclasses.asdict(m).items() if k != "with_"},
                                    "with": list(m.with_), "returns": {k: list(v) for k, v in m.returns.items()}} for m in s.manages]})
    return {"name": d.name, "initial": d.initial, "judge": d.judge, "status": d.status, "states": states,
            "launch": _launch_json(d.launch), "starts": starts_outline(d, inherited), "starts_named": d.starts is not None}


def _launch_json(launch) -> dict | None:
    if launch is None:
        return None
    return {k: (list(v) if isinstance(v, tuple) else v) for k, v in dataclasses.asdict(launch).items() if v not in (None, (), "")}


def starts_outline(d: Definition, inherited=None) -> list[dict]:
    """The starts in force (FR-105): the text's own, or the file's when it names none, each with where it starts, whether its
    grant there can write on the item, and what a session of it receives."""
    from .agents import details_preview  # agents imports this module
    out = []
    for place, st in enumerate(machine.effective_starts(d, inherited), 1):
        leaf = machine.start_state(d, st) if (st.state is None or st.state in d.states) else None
        prompt = st.prompt or (d.launch.prompt if d.launch else "")
        out.append({**machine.start_json(st), "place": place, "id": machine.start_id(d, st), "starts_in": leaf,
                    "path": list(reversed(machine.ancestors(d, leaf))) if leaf else [],
                    "writes": machine.writes_on_item(machine.effective(d, leaf)) if leaf else [],
                    "persona": next((p for s in (machine.ancestors(d, leaf) if leaf else ()) for p in d.states[s].personas),
                                    (d.launch.personas[0] if d.launch and d.launch.personas else None)),
                    "inherited": d.starts is None, "receives": details_preview(st.on, prompt)})
    return out


def edit_start(text: str, place, start, inherited=None) -> str:
    """The text with one start changed (`place`, 1-based), added (place None) or removed (start None), written again by
    machine.emit (comments go). A text that names no starts takes the file's first, so editing one keeps the others."""
    d = machine.parse(text)
    starts = list(machine.effective_starts(d, inherited))
    if place is not None and (not isinstance(place, int) or isinstance(place, bool) or not 1 <= place <= len(starts)):
        raise StoreError("place is a start's place, from 1")
    if start is None:
        if place is None:
            raise StoreError("name the start to remove")
        del starts[place - 1]
    else:
        new = machine.start_from(start)
        if place is None:
            starts.append(new)
        else:
            starts[place - 1] = new
    return machine.emit(dataclasses.replace(d, starts=tuple(starts)))


def _finding(f) -> dict:
    return {"kind": f.kind, "where": f.where, "text": f.text}


def examine(text, name: str | None = None, library=None, repo: str | None = None) -> dict:
    """Parse and check a text: its findings (problems stop a save, marks only show), and its outline if it parses. With a
    library, also what the library's own checks say of it as that workflow's version."""
    if not isinstance(text, str) or len(text) > MAX_TEXT:
        return {"findings": [{"kind": "problem", "where": "text", "text": f"the text is at most {MAX_TEXT // 1024} KiB"}], "outline": None}
    try:
        d = machine.parse(text)
    except DefinitionError as e:
        return {"findings": [{"kind": "problem", "where": p.where, "text": p.text} for p in e.problems], "outline": None}
    inherited = _file_starts(library, name)
    findings = [_finding(f) for f in machine.check(d)]
    if d.starts is None and inherited:  # the file's starts are in force: they are checked against this text's states
        findings += [_finding(f) for f in machine.check_starts(d, inherited)]
    if name is not None and d.name != name:
        findings.insert(0, {"kind": "problem", "where": "workflow.name", "text": f"is {d.name!r}: this is {name!r}'s version"})
    elif name is not None and library is not None and not any(f["kind"] == "problem" for f in findings):
        from .agents import LibraryError  # agents imports this module
        try:
            library.trial(name, text, repo)
        except LibraryError as e:
            findings.insert(0, {"kind": "problem", "where": "library", "text": str(e)})
    return {"findings": findings, "outline": outline(d, inherited)}


def _file_starts(library, name):
    """The starts of the workflow's file, which a version naming none inherits."""
    d = (getattr(library, "files", None) or {}).get(name) if library is not None and name is not None else None
    return d.starts if d is not None else None


def problems_of(findings: list[dict]) -> list[dict]:
    return [f for f in findings if f["kind"] == "problem"]


# ---- the diff ----

def _row_json(a: Definition, b: Definition, r: machine.Row) -> dict:
    d = a if r.kind == "removed" else b
    depth = len(machine.ancestors(d, r.state)) - 1 if r.state in d.states else 0
    out = {"kind": r.kind, "state": r.state, "exit": r.exit, "to": r.to, "fields": list(r.fields), "depth": depth}
    if r.exit is None:
        out["before"] = _state_face(a, r.state) if r.state in a.states else None
        out["after"] = _state_face(b, r.state) if r.state in b.states else None
    else:
        old = a.states[r.state].exits[(r.exit if r.kind == "removed" else r.was) - 1] if r.kind == "removed" or r.was else None
        new = b.states[r.state].exits[r.exit - 1] if r.kind != "removed" else None
        out["was"] = r.exit if r.kind == "removed" else r.was
        out["before"] = _exit_face(old) if old else None
        out["after"] = _exit_face(new) if new else None
    sens = []
    for side, dd in (("after", b), ("before", a)):
        if r.exit is None and r.state in dd.states:
            g = dd.states[r.state].grant
            sens.append((side, [f"{x}: {machine.SENSITIVE[x]}" for x in g.github if x in machine.SENSITIVE]
                         + [f"{x}: {machine.SENSITIVE_HUB_TOOLS[x]}" for x in (*g.hub_tools, *g.asks_first) if x in machine.SENSITIVE_HUB_TOOLS]
                         + (["full access: runs with the maintainer's own rights"] if g.access == "full" else [])))
    out["sensitive"] = dict(sens)
    return out


def _state_face(d: Definition, sid: str) -> dict:
    s = d.states[sid]
    tags = [t for t, on in (("parent", s.initial is not None), ("final", s.final),
                            ("starts here", (d.states[s.parent].initial if s.parent else d.initial) == sid)) if on]
    own = machine.effective(d, sid)
    return {"title": sid, "tags": tags, "context": s.context, "instructions": s.instructions[:200],
            "grant": {k: list(v) if isinstance(v, tuple) else v for k, v in dataclasses.asdict(s.grant).items() if v not in (None, ())},
            "access": own.access}


def _exit_face(e: machine.Exit) -> dict:
    parts = [e.decided_by, *([f"when “{e.when}”"] if e.when else []), *([f"requires {', '.join(e.requires)}"] if e.requires else []),
             *([f"on {', '.join(e.on)}"] if e.on else []), *([f"move {e.move}"] if e.move != "auto" else []),
             *([f"approve {e.approve}"] if e.approve != "none" else []), *([f"enter {e.enter}"] if e.enter != "first" else [])]
    return {"title": f"→ {e.to}", "sub": " · ".join(parts), **_exit_json(e)}


def text_diff(a: str, b: str) -> list[dict]:
    """A unified diff, line by line: kind hunk, add, del or ctx."""
    out = []
    for line in list(difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", n=2))[2:]:
        kind = "hunk" if line.startswith("@@") else "add" if line.startswith("+") else "del" if line.startswith("-") else "ctx"
        out.append({"kind": kind, "text": line[1:] if kind in ("add", "del", "ctx") else line})
    return out


def diff(a_text: str, b_text: str, inherited=None) -> dict:
    """The outline diff (machine.outline_diff, with each side's summary), the starts' (a prompt's edit among them) and the
    text diff. Rows need both to parse."""
    lines = text_diff(a_text, b_text)
    stat = {"added": sum(1 for x in lines if x["kind"] == "add"), "removed": sum(1 for x in lines if x["kind"] == "del")}
    try:
        a, b = machine.parse(a_text), machine.parse(b_text)
    except DefinitionError:
        return {"rows": None, "starts": None, "text": lines, "stat": stat}
    return {"rows": [_row_json(a, b, r) for r in machine.outline_diff(a, b)], "starts": machine.starts_diff(a, b, inherited),
            "text": lines, "stat": stat}


def sensitive_marks(a_text: str | None, findings: list[dict], b_text: str | None = None, inherited=None) -> list[dict]:
    """The marks of the new text, each saying whether the old text had it already (`new`), and with the new text, what its
    starts change that a reviewer should see (start_marks)."""
    old = set()
    if a_text is not None:
        try:
            old = {(f.where, f.text) for f in machine.check(machine.parse(a_text)) if f.kind == "mark"}
        except DefinitionError:
            old = set()
    out = [{**f, "new": (f["where"], f["text"]) not in old} for f in findings if f["kind"] == "mark"]
    return out + (start_marks(a_text, b_text, inherited) if b_text is not None else [])


def _an(kind: str) -> str:
    return f"{'an' if kind[:1] in 'aeiou' else 'a'} {kind}"


def start_marks(a_text: str | None, b_text: str, inherited=None) -> list[dict]:
    """What a change to the starts grants or moves, as marks: a start whose session begins holding more than the same start
    did (or, for a new one, more than the workflow's first state), one that now begins on another kind of item or takes or
    gives up the lead, and one whose starting grant writes on the item differently while its ceiling, the words its item's page
    shows, stays as it was."""
    try:
        b = machine.parse(b_text)
        a = machine.parse(a_text) if a_text is not None else None
    except DefinitionError:
        return []
    def keyed(d):
        return {machine.start_id(d, st): st for st in machine.effective_starts(d, inherited)}
    before = keyed(a) if a is not None else {}
    out = []
    mark = lambda sid, text: out.append({"kind": "mark", "where": f"start.{sid}", "text": text, "new": True})  # noqa: E731
    for sid, st in keyed(b).items():
        if (st.state is not None and st.state not in b.states) or b.initial not in b.states:
            continue  # the checks say so as a problem; nothing to mark until it names a state
        grant = machine.effective(b, machine.start_state(b, st))
        old = before.get(sid)
        if a is not None:
            base = machine.effective(a, machine.start_state(a, old)) if old is not None and (old.state is None or old.state in a.states) \
                else machine.effective(a, machine._leaf(a, a.initial)) if a.initial in a.states else machine.Grant()
            if wider := machine.beyond(grant, base):
                words = "; ".join(f"{k} {', '.join(map(str, v))}" for k, v in wider.items())
                mark(sid, f"wider start: {st.label} begins in {machine.start_state(b, st)}, holding more than before ({words})")
        if old is None:
            continue
        if old.on != st.on:
            mark(sid, f"another item: {st.label} now starts on {_an(st.on)}, not {_an(old.on)}")
        if old.lead != st.lead:
            mark(sid, f"lead: {st.label} " + ("now leads" if st.lead else "no longer leads") + f" the starts of {_an(st.on)}")
        writes = machine.writes_on_item(grant)
        if a is not None and writes and old.ceiling == st.ceiling and (old.state is None or old.state in a.states) \
                and writes != machine.writes_on_item(machine.effective(a, machine.start_state(a, old))):
            mark(sid, f"ceiling unchanged: {st.label} writes on its item ({', '.join(writes[:4])}), and its ceiling words are as before")
    return out


def reorder(text: str, state: str, place, by) -> str:
    """The text with one of a state's exits moved one place up or down, written again by machine.emit (comments go)."""
    d = machine.parse(text)
    if state not in d.states:
        raise StoreError(f"{state!r} isn't a state")
    exits = list(d.states[state].exits)
    if not isinstance(place, int) or isinstance(place, bool) or not 1 <= place <= len(exits) or by not in (-1, 1):
        raise StoreError("place is an exit's place and by is -1 or 1")
    other = place - 1 + by
    if not 0 <= other < len(exits):
        raise StoreError("it is at the end already")
    exits[place - 1], exits[other] = exits[other], exits[place - 1]
    states = {**d.states, state: dataclasses.replace(d.states[state], exits=tuple(exits))}
    return machine.emit(dataclasses.replace(d, states=states))


# ---- replay (FR-009) ----

def _verdict(ev: dict) -> str | None:
    """The target of the exit a judge picked in a logged evaluation, or None if it picked none or wasn't asked."""
    proposal = ev.get("proposal") or ""
    m = re.fullmatch(r"exit (\d+) to (\S+)", proposal)
    return m.group(2) if m and ev.get("judge") else None


def _asked(ev: dict, old: Definition | None) -> set[tuple[str, str]]:
    """The (target, question) pairs the judge was asked at this evaluation, when the definition of the time is known."""
    if old is None or ev["state"] not in old.states:
        return set()
    rows = (ev.get("checks") or {}).get("exits") or []
    places = {r.get("exit") for r in rows if r.get("decided_by") == "judge"}
    exits = machine.exits_of(old, ev["state"])
    return {(exits[i].to, exits[i].when) for i in places if isinstance(i, int) and 0 <= i < len(exits)}


NO_VALUE = object()  # a fact the log shows the hub had no value for then (a managed entry that hadn't returned, say)


def _logged_facts(ev: dict) -> dict:
    facts = {}
    for row in (ev.get("checks") or {}).get("exits") or []:
        for c in row.get("checks") or []:
            for t in c.get("terms") or []:
                if isinstance(t, dict) and isinstance(t.get("fact"), str) and "value" in t:
                    if t["value"] is not None:
                        facts[t["fact"]] = t["value"]
                    else:
                        facts.setdefault(t["fact"], NO_VALUE)
    return facts


def _logged_target(ev: dict) -> str | None:
    move = (ev.get("checks") or {}).get("move") or {}
    return move.get("to") if move.get("moved") else None


def _three(expr: str, facts: dict) -> str:
    """holds, fails or unknown: a term whose fact the replay hasn't is unknown, and so is the entry unless another term holds."""
    try:
        req = machine.parse_requires(expr)
    except DefinitionError:
        return "unknown"
    # a fact logged without a value held neither way then, so the hub went on past its term: here it doesn't hold either
    results = {"fails" if facts.get(t.name) is NO_VALUE else "unknown" if facts.get(t.name) is None else "holds" if t.holds(facts)
               else "fails" for t in req.terms}
    return "holds" if "holds" in results else "unknown" if "unknown" in results else "fails"


def replay(d: Definition, history: dict, known: dict[str, Definition] | None = None) -> dict:
    """Runs `d` over a session's logged evaluations and moves, oldest first. `known`: the definitions of the time, by version,
    for which questions the judge was asked. Pure: the same history and definition give the same result."""
    known = known or {}
    events = [("e", ev["at"], ev["seq"], ev) for ev in history.get("evaluations", [])]
    events += [("m", mv["at"], mv["seq"], mv) for mv in history.get("moves", []) if mv.get("by") in ("hand", "rollback")]
    events.sort(key=lambda x: (x[1], x[0] == "e", x[2]))
    state = _leaf(d, d.initial)
    rounds = {s: 1 for s in machine.ancestors(d, state)}
    trail, hist = [], {}
    steps, diverged, unknown_facts = [], False, set()

    def enter(to: str, how: str = "first") -> str:
        nonlocal state
        for parent in machine.ancestors(d, state)[1:]:
            hist[parent] = state
        trail.append(state)
        state = _enter(d, to, hist, how)
        for s in machine.ancestors(d, state):
            rounds[s] = rounds.get(s, 0) + 1
        return state

    for kind, at, _seq, ev in events:
        if kind == "m":
            if ev["by"] == "rollback":
                step = {"at": at, "kind": "rollback", "logged": {"from": ev["from"], "to": ev["to"]}, "replay": {"from": state}}
                if trail:
                    state = trail.pop()
                    step["replay"].update(to=state, result="moves")
                else:
                    step["replay"].update(to=None, result="stays", why="there's no move to roll back")
            else:
                step = {"at": at, "kind": "hand", "logged": {"from": ev["from"], "to": ev["to"]}, "replay": {"from": state}}
                if ev["to"] in d.states:
                    step["replay"].update(to=enter(ev["to"]), result="moves")
                else:
                    step["replay"].update(to=None, result="stays", why=f"it has no state {ev['to']}, so it stays")
            step["differs"] = step["replay"].get("to") != ev["to"]
            step["uncertain"] = diverged
            diverged = diverged or step["differs"]
            steps.append(step)
            continue
        signals = [s.strip() for s in ev["signal"].split(",") if s.strip()]
        facts = {**_logged_facts(ev), **{f"rounds.{s}": int(n) for s, n in rounds.items()}}
        for sid in d.states:
            facts.setdefault(f"rounds.{sid}", 0)
        old = known.get(ev.get("version"))
        logged_to = _logged_target(ev)
        step = {"at": at, "kind": "evaluation", "signal": ev["signal"],
                "logged": {"from": ev["state"], "to": logged_to, "failed": bool(ev.get("failed")), "blocked": (ev.get("checks") or {}).get("blocked")},
                "replay": {"from": state}, "uncertain": diverged}
        tried = _tried(d, state, signals, ev)
        outcome, why, exit_ = "stays", "no exit of this state is tried on that signal", None
        if ev.get("failed"):
            outcome, why = "stays", "the judge didn't answer then, so nothing moves"
            tried = []
        same_state = state == ev["state"]
        verdict, asked = _verdict(ev), _asked(ev, old)
        for place, e in tried:
            if e.decided_by == "judge":
                if not same_state or (e.to, e.when) not in asked:
                    outcome, why, exit_ = "cant_tell", f"the judge wasn't asked “{e.when}” in {state} then", place
                    break
                if verdict != e.to:
                    continue
            results = [_three(r, facts) for r in e.requires]
            unknown_facts |= {t.name for r in e.requires for t in _terms(r) if facts.get(t.name) is None}
            if "fails" in results:
                continue
            if "unknown" in results:
                outcome, why, exit_ = "cant_tell", "a fact its exit needs wasn't in the log", place
                break
            if e.approve != "none":
                outcome, why, exit_ = "asks", f"its exit to {e.to} holds and asks {e.approve} first", place
                break
            outcome, why, exit_ = "moves", f"its exit to {e.to} holds", place
            break
        target = None
        if outcome == "moves":
            chosen = dict(tried)[exit_]
            target = enter(chosen.to, chosen.enter)
        step["replay"].update(to=target, result=outcome, why=why, exit=exit_)
        if outcome == "cant_tell":
            step["differs"] = None
        else:
            step["differs"] = (not same_state) or target != logged_to
        diverged = diverged or bool(step["differs"])
        steps.append(step)
    differs = [s for s in steps if s["differs"]]
    return {"steps": steps, "differs": len(differs), "cant_tell": sum(1 for s in steps if s["differs"] is None),
            "first_difference": differs[0]["at"] if differs else None, "end": state,
            "logged_end": next((s["logged"]["to"] for s in reversed(steps) if s["logged"].get("to")), None),
            "unknown_facts": sorted(unknown_facts)}


def _terms(expr: str):
    try:
        return machine.parse_requires(expr).terms
    except DefinitionError:
        return ()


def _tried(d: Definition, state: str, signals: list[str], ev: dict) -> list[tuple[int, machine.Exit]]:
    """The exits a pass on these signals tries: as the runner does, or for a session's request (`request`) the on-request exits
    to where it asked, or for an approved card (`hub:approved`) the exit to where it was approved."""
    exits = list(enumerate(machine.exits_of(d, state)))
    asked_to = {r.get("to") for r in ((ev.get("checks") or {}).get("exits") or [])}
    if signals == ["request"]:
        return [(i, e) for i, e in exits if e.move == "on-request" and e.decided_by != "hand" and e.to in asked_to]
    if signals == ["hub:approved"]:
        return [(i, dataclasses.replace(e, approve="none")) for i, e in exits if e.decided_by != "hand" and e.to in asked_to][:1]
    wanted = set(signals)
    return [(i, e) for i, e in exits if e.decided_by != "hand" and e.move == "auto" and wanted & set(e.on)]


# ---- the ops ----

class Workflows:
    """The editor's ops and the `workflow.change` decision. `agents` gives the library, the store and the machine log;
    `decisions` the cards. Every op is the maintainer's: the caller has checked the login, and `who` is its user."""

    def __init__(self, agents, decisions=None):
        self.agents = agents
        self.decisions = decisions

    @property
    def store(self) -> Store:
        return self.agents.workflow_store

    @property
    def library(self):
        return self.agents.library

    def _known(self, name) -> str:
        _name(name)
        if name not in self.store.defaults:
            raise StoreError(f"there is no workflow {name!r}")
        return name

    def request(self, op: str, req: dict, who: str | None) -> dict:
        if op not in OPS:
            return {"ok": False, "error": f"unknown request: {op}"}
        try:
            handler = getattr(self, "_" + op.split(".", 1)[1])
            return {"ok": True, **handler(req, who)}
        except StoreError as e:
            return {"ok": False, "error": str(e)}

    def _list(self, _req, _who) -> dict:
        rows = []
        for name in sorted(self.store.defaults):
            org = self.store.latest_number(name, ORG)
            d = self.library.workflows.get(name)
            starts = [a for a in self.library.actions.values() if a.get("workflow") == name and not a.get("managed_only")]
            rows.append({"name": name, "org": org, "states": len(d.states) if d else None,
                         "actions": sorted(a["id"] for a in self.library.actions.values() if a.get("workflow") == name),
                         # FR-105: what each starts on, for a list by kind; a workflow without starts is managed only
                         "starts": [{"id": a["id"], "on": a["object"], "label": a["title"], "lead": bool(a.get("lead")),
                                     "when_held": a.get("when_held")} for a in sorted(starts, key=lambda a: a.get("start", 0))],
                         "kinds": sorted({a["object"] for a in starts}), "managed_only": not starts,
                         "overrides": [{"scope": s, "repo": repo_of(s), "v": self.store.latest_number(name, s)} for s in self.store.scopes(name) if s != ORG],
                         "refused": {s: why for (s, n), why in self.library.refused.items() if n == name}})
        return {"workflows": rows}

    def _scope(self, req) -> tuple[str, str | None]:
        scope = req.get("scope", ORG) or ORG
        return scope, repo_of(scope)

    def _get(self, req, _who) -> dict:
        name = self._known(req.get("name"))
        scope, repo = self._scope(req)
        numbers = ([0] if scope == ORG else []) + self.store.numbers(name, scope)
        version = req.get("version")
        if version is None:
            version = numbers[-1] if numbers else None
        if version is None:  # a repository with no override yet: it starts from what it would run now
            base = self.store.resolve(name, None)
            text, shown = base["text"], {"v": 0, "of": ORG, "from": base["v"]}
        else:
            text, shown = self.store.text(name, scope, version), {"v": version, "of": scope}
        in_use = self.store.resolve(name, repo)
        return {**self._proposal(req.get("proposal"), name, scope), "name": name, "scope": scope, "repo": repo, "text": text, "shown": shown,
                "latest": self.store.latest_number(name, scope), "in_use": {"scope": in_use["scope"], "v": in_use["v"]},
                "versions": [self.store.about(name, scope, n) for n in numbers], "scopes": self.store.scopes(name),
                **examine(text, name, self.library, repo), "sessions": self._sessions(name),
                "running": self._running(name)}

    def _proposal(self, decision_id, name: str, scope: str) -> dict:
        """A workflow.change card's text, to open in the editor: only one for this workflow and scope."""
        if decision_id is None or self.decisions is None:
            return {}
        from .decisions import CHANGE, DecisionError
        try:
            record = self.decisions._get(decision_id)
        except DecisionError:
            raise StoreError("no such proposal") from None
        card = record["scope"]
        if record["kind"] != CHANGE or card.get("workflow") != name or card.get("scope") != scope:
            raise StoreError("that proposal is for another workflow or scope")
        return {"proposal": {"id": record["id"], "text": card["text"], "note": card.get("note"), "base_version": card.get("base_version"),
                             "state": self.decisions.current_state(record)}}

    def _running(self, name: str) -> int:
        count = 0
        for directory in self.agents.sessions.iterdir() if self.agents.sessions.is_dir() else ():
            summary = self.agents.machines.summary(directory.name)
            if summary and summary["workflow"] == name:
                count += 1
        return count

    def _sessions(self, name: str) -> list[dict]:
        """Past and present sessions whose machine log names a version of this workflow, newest first: what a replay can run on."""
        versions = set(self.store.known_versions(name))
        try:
            seen = self.agents.machines.log.sessions()
        except Exception:  # noqa: BLE001: no log, or one that can't be read, offers nothing to replay
            log.exception("the machine log can't be read")
            return []
        return [s for s in seen if versions & set(s["versions"])][:50]

    def _check(self, req, _who) -> dict:
        name = req.get("name")
        if name is not None:
            self._known(name)
        _scope, repo = self._scope(req)
        return examine(req.get("text"), name, self.library if name else None, repo)

    def _from_text(self, name: str, scope: str, version) -> str:
        if version is None:
            return self.store.resolve(name, repo_of(scope))["text"]
        if scope != ORG and version == 0:  # a repository's first override starts from the organisation's
            return self.store.resolve(name, None)["text"]
        return self.store.text(name, scope, version)

    def _diff(self, req, _who) -> dict:
        name = self._known(req.get("name"))
        scope, _repo = self._scope(req)
        text = req.get("text")
        if not isinstance(text, str) or len(text) > MAX_TEXT:
            raise StoreError("text is the definition, at most 128 KiB")
        return diff(self._from_text(name, scope, req.get("from")), text, _file_starts(self.library, name))

    def _replay(self, req, _who) -> dict:
        name = self._known(req.get("name"))
        text, session = req.get("text"), req.get("session")
        if not isinstance(session, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", session):
            raise StoreError("session names a past session's conversation")
        try:
            d = machine.parse(text) if isinstance(text, str) else None
        except DefinitionError as e:
            raise StoreError(f"the text doesn't parse: {e}") from None
        if d is None:
            raise StoreError("text is the definition")
        history = self.agents.machines.log.history(session)
        known = {}
        for version, (scope, n) in self.store.known_versions(name).items():
            try:
                known[version] = machine.parse(self.store.text(name, scope, n))
            except (DefinitionError, StoreError):
                continue
        for ev in history["evaluations"]:  # what the session ran on, if its version isn't one of these (a file since edited)
            if ev["version"] not in known:
                for row in self._instance_texts(session):
                    known.setdefault(version_of(row), machine.parse(row))
                break
        # a start's prompt or fields don't change a move: the replay says which changed, as sessions started after a save get them
        try:
            now = machine.parse(self._from_text(name, self._scope(req)[0], None))
            starts = [r for r in machine.starts_diff(now, d, _file_starts(self.library, name)) if r["kind"] != "same"]
        except (DefinitionError, StoreError):
            starts = None
        return {"session": session, **replay(d, history, known), "starts": starts,
                "starts_note": "Starts don't move a session: what changed in them reaches the sessions started after the save."}

    def _instance_texts(self, session_id: str) -> list[str]:
        for directory in self.agents.sessions.iterdir() if self.agents.sessions.is_dir() else ():
            try:
                record = json.loads((directory / "session.json").read_text())
                if record.get("session_id") != session_id:
                    continue
                inst = json.loads((directory / "machine.json").read_text())
                return [t for t in inst.get("definitions", {}).values() if isinstance(t, str)]
            except (OSError, ValueError, AttributeError):
                continue
        return []

    def _checked(self, name: str, scope: str, text) -> dict:
        if not isinstance(text, str) or len(text) > MAX_TEXT:
            raise StoreError("text is the definition, at most 128 KiB")
        found = examine(text, name, self.library, repo_of(scope))
        return found

    def save(self, name: str, scope: str, text, base, who, note=None, decision=None) -> dict:
        """The one way a version is made: checked here again, whoever asks."""
        found = self._checked(name, scope, text)
        if problems := problems_of(found["findings"]):
            raise StoreError("the checks find a problem: " + "; ".join(f"{p['where']}: {p['text']}" for p in problems[:5]))
        if note is not None and (not isinstance(note, str) or len(note) > MAX_NOTE):
            raise StoreError("the note is text, at most 2000 characters")
        saved = self.store.save(name, scope, text, base, who, note, decision)
        self.library.saved()
        return saved

    def _save(self, req, who) -> dict:
        name = self._known(req.get("name"))
        scope, _repo = self._scope(req)
        return {"saved": self.save(name, scope, req.get("text"), req.get("base_version"), who, req.get("note"))}

    def _reorder(self, req, _who) -> dict:
        text = req.get("text")
        if not isinstance(text, str) or len(text) > MAX_TEXT:
            raise StoreError("text is the definition, at most 128 KiB")
        try:
            return {"text": reorder(text, req.get("state"), req.get("place"), req.get("by"))}
        except DefinitionError as e:
            raise StoreError(f"the text doesn't parse: {e}") from None

    def _start(self, req, _who) -> dict:
        """One start of the text changed, added or removed (FR-105), for the editor to show and check: nothing is saved. The
        saved version still goes through workflow.save or workflow.propose, and a prompt's edit is in their diff and replay."""
        name = self._known(req.get("name"))
        text = req.get("text")
        if not isinstance(text, str) or len(text) > MAX_TEXT:
            raise StoreError("text is the definition, at most 128 KiB")
        start = req.get("start")
        if start is not None and not isinstance(start, dict):
            raise StoreError("start is a table of a start's fields, or none to remove it")
        try:
            new = edit_start(text, req.get("place"), start, _file_starts(self.library, name))
        except DefinitionError as e:
            raise StoreError("; ".join(f"{p.where}: {p.text}" for p in e.problems[:5])) from None
        _scope, repo = self._scope(req)
        return {"text": new, **examine(new, name, self.library, repo)}

    def _propose(self, req, who) -> dict:
        from .decisions import DecisionError  # decisions imports agents, which imports this module
        if self.decisions is None:
            raise StoreError("decisions aren't set up")
        name = self._known(req.get("name"))
        scope, repo = self._scope(req)
        text, note = req.get("text"), req.get("note")
        if not isinstance(note, str) or not note.strip() or len(note) > MAX_NOTE:
            raise StoreError("say what the change is for, in at most 2000 characters")
        found = self._checked(name, scope, text)
        base = self.store.latest_number(name, scope)
        before = self._from_text(name, scope, base)
        if before == text:
            raise StoreError("it's the same as the version it starts from")
        changed = diff(before, text, _file_starts(self.library, name))
        card = {"workflow": name, "scope": scope, "repo": repo, "base_version": base, "text": text, "note": note.strip(),
                "proposed_by": who, "rows": changed["rows"], "starts": changed["starts"], "text_diff": changed["text"], "stat": changed["stat"],
                "findings": found["findings"], "sensitive": sensitive_marks(before, found["findings"], text, _file_starts(self.library, name))}
        session = req.get("session")
        if session is not None:
            try:
                card["replay"] = self._replay({"name": name, "text": text, "session": session}, who)
            except StoreError as e:
                card["replay"] = {"error": str(e)}
        where = "the organisation" if scope == ORG else repo
        why = f"A new version of {name} for {where}, from v{base}: {note.strip()[:300]}"
        try:
            record = self.decisions.change_request(card, why)
        except DecisionError as e:
            raise StoreError(str(e)) from None
        return {"decision": self.decisions.view(record)}

    # --- the card's answer (server.decision_request) ---
    def answer(self, decision_id, accept: bool, who: str | None, words: str | None = None, changes: bool = False) -> dict:
        """Approve saves the proposed text as the next version, if the checks still pass and nothing was saved since it was
        proposed; the card stays up if not. Saying no, or asking for changes, ends it."""
        from .decisions import CHANGE, DecisionError
        record = self.decisions._get(decision_id)
        if record["kind"] != CHANGE:
            raise DecisionError("that isn't a workflow change")
        if self.decisions.current_state(record) != "requested":
            raise DecisionError("that isn't waiting for an answer any more")
        scope = record["scope"]
        if not accept:
            if changes:
                return self.decisions.settle(decision_id, False, f"you asked for changes: {words}" if words else "you asked for changes")
            return self.decisions.settle(decision_id, False, f"discarded: {words}" if words else "discarded")
        try:
            saved = self.save(scope["workflow"], scope["scope"], scope["text"], scope["base_version"], who,
                              scope.get("note"), decision_id)
        except StoreError as e:
            raise DecisionError(f"not saved: {e}") from None
        return self.decisions.settle(decision_id, True, f"saved as v{saved['v']}: sessions take it at their next move", words)
