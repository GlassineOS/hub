# SPDX-License-Identifier: GPL-2.0-or-later
"""The person's decisions: goes and merge approvals, and the hub's own confirms of a workflow move that widens a session's
grant (spec 012 FR-024). A file each, in hubd's state folder.

Only a login records the person's word. Every op that makes a decision current sits behind the login check in
Hubd.request. A session's tool token can ask whether one covers it, spend a run of one that does, ask for one on a card,
and end a go, as that only narrows. Nothing a token can do makes one current.

Each move is on disk before anything acts on it. Answers come in words, with a plain yes or no for a script to act on.

A widening confirm (`machine.widen`), a workflow approval (`machine.approve`) and a workflow change (`workflow.change`, a
proposed version, hubd/machinestore.py) are made by hubd alone, never by a request or a token: approving one confirms or
makes the move it names, or saves the version it carries, and nothing else, so it never becomes current. It goes from
requested straight to ended.

This stops mistakes, relayed quotes and misled locked agents. A full session runs as the same user, and could write these
files: see SECURITY.md.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import tempfile
import time
from pathlib import Path

from .agents import _draws_nothing

log = logging.getLogger("hubd.decisions")

KINDS = ("go", "merge")
WIDEN = "machine.widen"
APPROVE = "machine.approve"  # a workflow exit that holds and whose `approve` asks you first (012 FR-025, FR-052)
CHANGE = "workflow.change"  # a proposed new version of a workflow: approving it saves it (012 FR-060, FR-063)
HUB_KINDS = (WIDEN, APPROVE, CHANGE)  # made by hubd itself: `add` and `request` refuse them
STATES = ("requested", "current", "using", "ended")  # using: its merge is running
EYE_TEST = "eye-test"  # you hold the device while a session holds the lock: "I've got the device" leaves it alone
ANY = "any"
MAX_GO_HOURS = 8  # "a few hours", proposed in docs/workspace.md
MAX_RUNS = 20
MAX_WORDS = 2000
MAX_WHY = 500
MAX_ACTIONS = 16
MAX_REQUESTS = 8  # open at once from one session, so it can't bury the page
REQUEST_LIFE = 24 * 3600  # seconds an unanswered request stays up: by then what it asked for has moved on
SHOWN_ENDED = 200

_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_ACTION_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
_REPO_RE = re.compile(r"\.?[A-Za-z0-9_][A-Za-z0-9._-]{0,99}")
_BRANCH_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}")
_HEAD_RE = re.compile(r"[0-9a-f]{40}")
_ID_RE = re.compile(r"d-[0-9a-f]{12}")
_TARGET_RE = re.compile(rf"({_REPO_RE.pattern})#([1-9][0-9]{{0,9}})(?:@(\S+))?")


class DecisionError(Exception):
    pass


def text(value, limit: int, what: str) -> str:
    """One piece of what someone typed, without what wouldn't show on the page."""
    if not isinstance(value, str):
        raise DecisionError(f"{what} has to be text")
    kept = "".join(c for c in value if not _draws_nothing(c)).strip()
    if not kept:
        raise DecisionError(f"{what} can't be empty")
    if len(kept) > limit:
        raise DecisionError(f"{what} has to be at most {limit} characters")
    return kept


def _name(value, what: str) -> str:
    if not isinstance(value, str) or not _NAME_RE.fullmatch(value):
        raise DecisionError(f"{what} has to be a name, or {ANY}")
    return value


def actions_of(value) -> list[str]:
    """A list, or words with commas between them as `dev take --does` has them."""
    names = value.split(",") if isinstance(value, str) else value
    if not isinstance(names, list) or not names or len(names) > MAX_ACTIONS:
        raise DecisionError(f"name between 1 and {MAX_ACTIONS} actions")
    names = [n.strip() if isinstance(n, str) else n for n in names]
    if not all(isinstance(n, str) and _ACTION_RE.fullmatch(n) for n in names):
        raise DecisionError("an action is a short name: reboot, suspend, load-test")
    return list(dict.fromkeys(names))


def head_of(value) -> str:
    if not isinstance(value, str) or not _HEAD_RE.fullmatch(value):
        raise DecisionError("name the head commit in full: 40 hexadecimal characters, in lower case")
    return value


def merge_target(value) -> tuple[str, int, str | None]:
    """repo#number, or repo#number@head."""
    match = _TARGET_RE.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise DecisionError("name a pull request as repo#number, or repo#number@head")
    return match[1], int(match[2]), head_of(match[3]) if match[3] else None


def _scope(kind: str, scope) -> dict:
    if not isinstance(scope, dict):
        raise DecisionError("a decision's scope has to be an object")
    if kind == "go":
        return {"device": _name(scope.get("device", ANY), "the device"), "actions": actions_of(scope.get("actions")),
                "session": _name(scope.get("session", ANY), "the session"), "session_id": None}  # the conversation: Decisions fills it in
    if kind == "merge":
        repo, number, base = scope.get("repo"), scope.get("number"), scope.get("base")
        if not isinstance(repo, str) or not _REPO_RE.fullmatch(repo):
            raise DecisionError("a merge decision names a repository")
        if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
            raise DecisionError("a merge decision names a pull request's number")
        if base is not None and (not isinstance(base, str) or not _BRANCH_RE.fullmatch(base)):
            raise DecisionError("that isn't a branch name")
        return {"repo": repo, "number": number, "head": head_of(scope.get("head")), "base": base,
                "session": _name(scope.get("session", ANY), "the session"), "session_id": None}  # as for a go
    raise DecisionError(f"a decision is one of {', '.join(KINDS)}")


def _ends(kind: str, ends, now: float) -> dict:
    """In the record: runs left, an hour on the clock, or how the kind itself ends."""
    ends = {} if ends is None else ends
    if not isinstance(ends, dict):
        raise DecisionError("when it ends has to be an object")
    kept = {}
    runs, hours = ends.get("runs"), ends.get("hours")
    if runs is not None:
        if kind != "go" or not isinstance(runs, int) or isinstance(runs, bool) or not 0 < runs <= MAX_RUNS:
            raise DecisionError(f"only a go has runs, between 1 and {MAX_RUNS}")
        kept["runs"] = runs
    if hours is not None:
        if not isinstance(hours, (int, float)) or isinstance(hours, bool) or not 0 < hours <= MAX_GO_HOURS:
            raise DecisionError(f"it can run for at most {MAX_GO_HOURS} hours")
        kept["until"] = now + hours * 3600
    if kind == "go" and not kept:
        raise DecisionError("a go must have an end: a number of runs, or hours")
    return kept


def _covers_only_an_eye_test(record: dict) -> bool:
    return record["kind"] == "go" and record["scope"]["actions"] == [EYE_TEST]


def _clock(when: float) -> str:
    return time.strftime("%H:%M", time.localtime(when))


def describe(record: dict) -> str:
    """A decision in a sentence: what it covers, not how it's stored."""
    scope, ends = record["scope"], record["ends"]
    if record["kind"] == WIDEN:
        adds = "; ".join(f"{k} {', '.join(map(str, v))}" for k, v in scope["adds"].items())
        return f"Workflow move for {scope['session']}: {scope['from']} to {scope['to']}, which adds {adds}"
    if record["kind"] == APPROVE and scope.get("type"):  # a report sent up, or a managed session's start: the hub's own words
        return scope["says"]
    if record["kind"] == CHANGE:
        where = "the organisation" if scope["scope"] == "org" else scope["repo"]
        return f"Workflow change: a new version of {scope['workflow']} for {where}, from v{scope['base_version']}"
    if record["kind"] == APPROVE:
        return f"Workflow approval for {scope['session']}: {scope['from']} to {scope['to']}, which its workflow leaves to {scope['level']}"
    if record["kind"] == "go":
        line = f"Go for {', '.join(scope['actions'])}, on {'any device' if scope['device'] == ANY else scope['device']}, for {'any session' if scope['session'] == ANY else scope['session']}"
        if "runs" in ends:
            line += f", {ends['runs']} run{'' if ends['runs'] == 1 else 's'} left"
    else:
        line = f"Merge {scope['repo']}#{scope['number']} at {scope['head'][:12]}"
        if scope.get("base"):
            line += f" into {scope['base']}"
        if scope["session"] != ANY:
            line += f", for {scope['session']}"
    if "until" in ends:
        line += f", until {_clock(ends['until'])}"
    if record["state"] == "requested" and record.get("for_hours"):
        line += f", for {record['for_hours']:g} hour{'' if record['for_hours'] == 1 else 's'} from when it's approved"
    return line


def _kept_whole(record: dict) -> bool:
    """Whether a file has what every answer reads. One that doesn't would break the page and every other go, so it's left out."""
    if record["kind"] not in (*KINDS, *HUB_KINDS) or record["state"] not in STATES or not isinstance(record["ends"], dict) or not isinstance(record["scope"], dict):
        return False
    float(record["made"])
    for field in ("asked_by", "why", "why_ended", "words", "ended"):
        record[field]  # noqa: B018: raises if it's missing
    describe(record)
    return True


class Decisions:
    def __init__(self, directory: Path, clock=time.time):
        self.directory = directory
        self.clock = clock
        self.session_id_of = lambda _name: None  # which conversation a session's name holds now. Names come back
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._all: dict[str, dict] = {}
        for path in directory.glob("d-*.json"):
            try:
                record = json.loads(path.read_text())
                if record["id"] == path.stem and _ID_RE.fullmatch(record["id"]) and _kept_whole(record):
                    self._all[record["id"]] = record
                    continue
            except (OSError, ValueError, LookupError, TypeError, AttributeError, OverflowError):
                pass
            log.warning("leaving out a decision that can't be read, so it answers no: %s", path.name)
        for record in list(self._all.values()):
            if record["state"] == "using":  # hubd stopped between starting the merge and hearing how it went
                self._end(record, "hubd stopped during its merge, so its outcome isn't known. Look at the pull request")
        self._holding = self._read_holding()

    # --- on disk ------------------------------------------------------------------------
    def _write(self, name: str, value) -> None:
        fd, temporary = tempfile.mkstemp(dir=self.directory, suffix=".tmp")  # 0600
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(value, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, self.directory / name)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def _save(self, record: dict) -> dict:
        self._write(f"{record['id']}.json", record)
        self._all[record["id"]] = record
        return record

    def _read_holding(self) -> float | None:
        try:
            return float(json.loads((self.directory / "holding.json").read_text())["since"])
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError):
            log.warning("can't read who holds the device, so taking it that you do")
            return self.clock()

    # --- moves --------------------------------------------------------------------------
    def _new(self, kind: str, scope: dict, ends: dict, state: str, words: str | None, **more) -> dict:
        now = self.clock()
        record = {"id": f"d-{secrets.token_hex(6)}", "kind": kind, "words": words, "scope": scope, "ends": ends, "state": state,
                  "why_ended": None, "made": now, "ended": None, "asked_by": None, "why": None, **more}
        return self._save(record)

    def add(self, kind, words, scope, ends=None) -> dict:
        """Yours, typed on the page. Current at once."""
        if kind not in KINDS:
            raise DecisionError(f"a decision is one of {', '.join(KINDS)}")
        words = text(words, MAX_WORDS, "what you decided")
        scope, ends = _scope(kind, scope), _ends(kind, ends, self.clock())
        scope = self._for_this_conversation(scope)
        if kind == "merge":  # two tabs, one word: taking it back has to end it
            for record in self._all.values():
                if record["kind"] == "merge" and record["scope"] == scope and self.current_state(record) == "current":
                    return record
        return self._new(kind, scope, ends, "current", words)

    def request(self, kind, scope, why, asked_by, ends=None) -> dict:
        """A card, for a session asking. It stays no use to anyone until a login approves it."""
        if kind not in KINDS:
            raise DecisionError(f"a decision is one of {', '.join(KINDS)}")
        why = text(why, MAX_WHY, "why")
        now = self.clock()
        scope = self._for_this_conversation(_scope(kind, scope))
        kept_ends = _ends(kind, ends, now) if ends is not None or kind != "go" else {"runs": 1}
        for_hours = None
        if kept_ends.pop("until", None) is not None:  # its clock starts when it's approved: a card can stay up for a day
            for_hours = ends["hours"]
        # The hub's own confirms aren't the session's asking, and don't use up its room.
        waiting = [r for r in self._all.values() if r["kind"] not in HUB_KINDS and self.current_state(r) == "requested" and r["asked_by"] == asked_by]
        if len(waiting) >= MAX_REQUESTS:
            raise DecisionError(f"you have {MAX_REQUESTS} waiting already: wait for an answer")
        return self._new(kind, scope, kept_ends, "requested", None, asked_by=asked_by, why=why, for_hours=for_hours)

    def widen_request(self, scope: dict, why: str) -> dict:
        """hubd's card for a move that waits for the maintainer's confirm. The scope is the hub's own: the session, the
        conversation, the pending move's id, the states and the change. `why` is the hub's words, not the session's."""
        return self._new(WIDEN, scope, {}, "requested", None, asked_by=scope["session"], why=why)

    def approve_request(self, scope: dict, why: str) -> dict:
        """hubd's card for a workflow exit that holds and waits for an approval. The scope is the hub's own: the session, the
        conversation, the state and version it was asked from, the exit's place and target, and the level."""
        return self._new(APPROVE, scope, {}, "requested", None, asked_by=scope["session"], why=why)

    def change_request(self, scope: dict, why: str) -> dict:
        """hubd's card for a proposed workflow version. The scope is the hub's own: the workflow, its scope, the version it
        starts from, the text, and what the hub found of it. Approving it saves the text, after checking it again."""
        return self._new(CHANGE, scope, {}, "requested", None, asked_by=None, why=why)

    def settle(self, decision_id, accepted: bool, why: str, words: str | None = None) -> dict:
        """A widening confirm answered or dropped: it ends, saying how."""
        record = self._get(decision_id)
        if record["kind"] not in HUB_KINDS:
            raise DecisionError("that isn't a confirm of the hub's")
        if record["state"] == "ended":
            return record
        more = {"approved": self.clock(), "words": words or "Confirmed on its card."} if accepted else {}
        return self._end({**record, **more}, why)

    def open_widenings(self, session: str, kind: str = WIDEN) -> list[dict]:
        return [r for r in list(self._all.values()) if r["kind"] == kind and r["scope"].get("session") == session
                and self.current_state(r) == "requested"]

    def open_approvals(self, session: str) -> list[dict]:
        return self.open_widenings(session, APPROVE)

    def retarget(self, session: str, old: str, new: str) -> int:
        """A fresh context's new conversation takes over the workflow cards still waiting on the old one (handoff.py): a
        move's confirm and an exit's approval. A go keeps to the conversation it was given to."""
        moved = 0
        for r in list(self._all.values()):
            if r["kind"] in (WIDEN, APPROVE) and r["scope"].get("session") == session and r["scope"].get("session_id") == old \
                    and self.current_state(r) == "requested":
                self._save({**r, "scope": {**r["scope"], "session_id": new}})
                moved += 1
        return moved

    def approve(self, decision_id, words=None, scope=None, ends=None) -> dict:
        """A login, on the card. It can narrow what was asked, and doesn't widen a go's actions."""
        record = self._get(decision_id)
        if record["kind"] in HUB_KINDS:
            raise DecisionError("a workflow move's confirm is answered through its session's machine")
        if self.current_state(record) != "requested":
            raise DecisionError("that isn't waiting for an answer any more")
        kept_scope = record["scope"]
        if scope is not None:
            if not isinstance(scope, dict) or record["kind"] != "go" or set(scope) != {"actions"}:
                raise DecisionError("a card is narrowed by a go's actions, and nothing else. Say no, or record one of your own")
            actions = actions_of(scope["actions"])
            if not set(actions) <= set(record["scope"]["actions"]):
                raise DecisionError("that adds actions to what was asked for. Narrow it, or record a go of your own")
            kept_scope = {**kept_scope, "actions": actions}
        now = self.clock()
        kept_ends = record["ends"] if ends is None else _ends(record["kind"], ends, now)
        if ends is None and record.get("for_hours"):
            kept_ends = {**kept_ends, "until": now + record["for_hours"] * 3600}
        said = text(words, MAX_WORDS, "what you decided") if words else "Approved on its card."
        return self._save({**record, "scope": kept_scope, "ends": kept_ends, "words": said, "state": "current", "approved": now})

    def deny(self, decision_id, why=None) -> dict:
        record = self._get(decision_id)
        if record["kind"] in HUB_KINDS:
            raise DecisionError("a workflow move's confirm is answered through its session's machine")
        if self.current_state(record) != "requested":
            raise DecisionError("that isn't waiting for an answer any more")
        return self._end(record, f"you said no: {text(why, MAX_WHY, 'why')}" if why else "you said no")

    def end(self, decision_id, why, by: str = "you") -> dict:
        record = self._get(decision_id)
        if record["kind"] in HUB_KINDS:
            raise DecisionError("a workflow move's confirm is answered, not ended")
        if self.current_state(record) != "current":
            raise DecisionError("that isn't current")
        said = text(why, MAX_WHY, "why") if why else None
        return self._end(record, f"ended by {by}: {said}" if said else f"ended by {by}")

    def end_go(self, decision_id, why, by: str) -> dict:
        """For a session, as that only narrows. Only a go: what else ends is yours."""
        if self._get(decision_id)["kind"] != "go":
            raise DecisionError("a session can end a go, and nothing else")
        return self.end(decision_id, why, by)

    def _for_this_conversation(self, scope: dict) -> dict:
        """Names come back, so a decision for a session is for the conversation that holds its name now, once, here."""
        if scope["session"] == ANY:
            return scope
        conversation = self.session_id_of(scope["session"])
        if not conversation:
            raise DecisionError(f"the hub doesn't know a conversation under the name {scope['session']}, so nothing could answer to this")
        return {**scope, "session_id": conversation}

    def check_new(self, kind: str, scope: dict) -> dict:
        """Refuses now what `add` would, for a caller that can't fail after it has answered a card."""
        self._for_this_conversation(_scope(kind, scope))
        return scope

    def _get(self, decision_id) -> dict:
        record = self._all.get(decision_id) if isinstance(decision_id, str) else None
        if record is None:
            raise DecisionError("there's no decision with that id")
        return record

    def _end(self, record: dict, why: str) -> dict:
        return self._save({**record, "state": "ended", "why_ended": why, "ended": self.clock()})

    def current_state(self, record: dict) -> str:
        """Its state as of now: time runs out with nobody watching, and that goes on disk when someone looks."""
        if record["state"] == "requested" and record["made"] + REQUEST_LIFE < self.clock():
            record = self._end(record, "nobody answered in time")
        elif record["state"] == "current" and "until" in record["ends"] and record["ends"]["until"] <= self.clock():
            record = self._end(record, f"its time ran out at {_clock(record['ends']['until'])}")
        return record["state"]

    def current(self, record: dict) -> bool:
        return self.current_state(record) == "current"

    # --- "I've got the device" --------------------------------------------------------------
    @property
    def holding(self) -> float | None:
        return self._holding

    def have_device(self) -> int:
        """Ends every recorded device go, but an eye test, where you hold it on purpose. It can't stop a running command."""
        if self._holding is None:
            since = self.clock()
            self._write("holding.json", {"since": since})
            self._holding = since
        ended = 0
        for record in list(self._all.values()):
            if record["kind"] == "go" and self.current(record) and not _covers_only_an_eye_test(record):
                self._end(record, "you took the device")
                ended += 1
        return ended

    def done(self) -> None:
        (self.directory / "holding.json").unlink(missing_ok=True)
        self._holding = None

    def holding_view(self) -> dict:
        if self._holding is None:
            return {"holding": False, "words": "The person hasn't said they have the device."}
        return {"holding": True, "since": self._holding,
                "words": f"The person has the device, since {_clock(self._holding)}, until they press Done. A take that names actions is refused, but an eye test."}

    # --- answers ------------------------------------------------------------------------
    @staticmethod
    def _no(words: str) -> dict:
        return {"answer": "no", "words": f"No: {words}"}

    @staticmethod
    def _answers_to(record: dict, session, session_id) -> bool:
        """A go for a named session answers only to that one. A plain shell, which has no session, matches only `any`.
        Names come back, so it keeps to the conversation it was made for, and one that isn't known answers to nobody."""
        wanted = record["scope"].get("session", ANY)
        if wanted == ANY:
            return True
        if wanted != session:
            return False
        kept = record["scope"].get("session_id")
        return bool(kept) and kept == session_id

    def _go_answer(self, record: dict, actions: list[str], device, session, session_id) -> dict | None:
        """Why this go doesn't do, or None if it does."""
        scope = record["scope"]
        missing = [a for a in actions if a not in scope["actions"]]
        if missing:
            return self._no(f"{record['id']} doesn't cover {', '.join(missing)}. It covers {', '.join(scope['actions'])}")
        if not self._answers_to(record, session, session_id):
            return self._no(f"{record['id']} answers to another session")
        if scope["device"] != ANY and device != scope["device"]:
            return self._no(f"{record['id']} is for {scope['device']}")
        return None

    def check_go(self, action, device, session, session_id, decision_id=None) -> tuple[dict, dict | None]:
        """Whether a go covers these actions for this caller. With an id, that go; without, any that does."""
        actions = actions_of(action)
        if device is not None and not (isinstance(device, str) and _NAME_RE.fullmatch(device)):
            raise DecisionError("that isn't a device's name")
        if self._holding is not None and actions != [EYE_TEST]:
            return self._no(f"the person has the device, since {_clock(self._holding)}, until they press Done"), None
        if decision_id is not None:
            record = self._get_or_none(decision_id)
            if record is None or record["kind"] != "go":
                return self._no("there's no go with that id"), None
            state = self.current_state(record)
            record = self._all[record["id"]]
            if state != "current":
                return self._no(f"{record['id']} {'is waiting for an answer' if state == 'requested' else 'has ended: ' + str(record['why_ended'])}"), None
            refused = self._go_answer(record, actions, device, session, session_id)
            return refused or self._yes(record), None if refused else record
        last = None
        for record in sorted(self._all.values(), key=lambda r: r["made"]):
            if record["kind"] == "go" and self.current(record):
                record = self._all[record["id"]]
                refused = self._go_answer(record, actions, device, session, session_id)
                if not refused:
                    return self._yes(record), record
                last = refused
        return last or self._no("there's no current go. Ask the person, or `decision_request`"), None

    def _get_or_none(self, decision_id) -> dict | None:
        return self._all.get(decision_id) if isinstance(decision_id, str) else None

    @staticmethod
    def _yes(record: dict) -> dict:
        return {"answer": "yes", "id": record["id"], "words": f"Yes: {record['id']}. {describe(record)}."}

    def spend(self, record: dict) -> dict:
        """A run of a go. Only a take that got through everything comes here."""
        if "runs" not in record["ends"]:
            return record
        left = record["ends"]["runs"] - 1
        if left <= 0:
            return self._end({**record, "ends": {**record["ends"], "runs": 0}}, "its last run was used")
        return self._save({**record, "ends": {**record["ends"], "runs": left}})

    def merges(self, repo: str, number: int, session, everyone: bool = False) -> list[dict]:
        """Current merge decisions for this pull request that answer to this caller, or everyone's, for a login."""
        session_id = self.session_id_of(session) if session else None
        found = []
        for record in list(self._all.values()):
            if record["kind"] == "merge" and self.current(record):
                record = self._all[record["id"]]
                scope = record["scope"]
                if scope["repo"].lower() == repo.lower() and scope["number"] == number and (everyone or self._answers_to(record, session, session_id)):
                    found.append(record)
        return found

    def merge_answer(self, record: dict, now: dict | None, head=None) -> dict | None:
        """Why a merge decision doesn't do for this head, or None if it does. `now` is what GitHub says of the pull
        request; a moved head ends the decision, as nothing can bring it back. The caller may have waited for `now`, so
        this reads the record as it is."""
        record = self._all[record["id"]]
        if not self.current(record):
            return self._no(f"{record['id']} isn't current any more")
        record = self._all[record["id"]]
        scope = record["scope"]
        if head is not None and head != scope["head"]:
            return self._no(f"{record['id']} is for head {scope['head'][:12]}, not {head[:12]}")
        if now is None:
            return self._no("GitHub can't say what this pull request's head is right now")
        if now.get("state") != "OPEN":
            return self._no(f"{scope['repo']}#{scope['number']} isn't open")
        if now.get("headRefOid") != scope["head"]:
            self._end(record, f"the head moved, from {scope['head'][:12]} to {str(now.get('headRefOid'))[:12]}")
            return self._no(f"{record['id']} is for head {scope['head'][:12]}, and the head has moved")
        if now.get("baseRefName") != scope.get("base"):
            return self._no(f"{record['id']} is for merging into {scope['base']}, and it now targets {now.get('baseRefName')}")
        return None

    def claim(self, record: dict) -> dict:
        """On disk before the merge, so a crash during it, or a second merge at once, can't use it again."""
        record = self._all[record["id"]]
        if self.current_state(record) != "current":
            raise DecisionError(f"{record['id']} isn't current any more")
        return self._save({**record, "state": "using"})

    def merged(self, record: dict) -> dict:
        return self._end(record, "used: it merged")

    def not_merged(self, record: dict) -> dict:
        """GitHub said no, for red checks or a conflict, so it stands."""
        return self._save({**record, "state": "current"})

    def head_moved(self, record: dict) -> dict:
        return self._end(record, "the head moved: GitHub refused the merge for it")

    def outcome_unknown(self, record: dict, what: str) -> dict:
        record = self._all[record["id"]]
        if record["state"] != "using":  # the outcome was recorded, and something failed after that
            return record
        return self._end(record, f"spent, and its outcome isn't known: {what}. Look at the pull request")

    def pull_request_merged(self, repo: str, number: int) -> None:
        """Nothing can use the others now, and with no time limit they'd read as current for good."""
        for record in self.merges(repo, number, None, everyone=True):
            self._end(record, "the pull request merged")

    def mark_handled(self, decision_id, handled: dict) -> dict:
        """Who answered its card, and where the page said it was. Shown, never read by a rule."""
        return self._save({**self._get(decision_id), "handled": handled})

    def view(self, record: dict) -> dict:
        self.current_state(record)
        record = self._all[record["id"]]
        return {**record, "says": describe(record)}

    def list(self) -> list[dict]:
        rows = [self.view(r) for r in list(self._all.values())]
        rows.sort(key=lambda r: r["made"], reverse=True)
        kept = [r for r in rows if r["state"] != "ended"]
        return kept + [r for r in rows if r["state"] == "ended"][:SHOWN_ENDED]
