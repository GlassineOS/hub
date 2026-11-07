# SPDX-License-Identifier: GPL-2.0-or-later
"""What a workflow file says about being started by hand (006 FR-036, FR-037): whether it has
`on: workflow_dispatch`, and the inputs that takes. A small reader of that one part of the YAML,
not a YAML library: anything it can't read for sure it says so about, in words, rather than guess.
"""
from __future__ import annotations

import re

TYPES = ("string", "choice", "boolean", "environment", "number")
MAX_INPUTS = 25  # GitHub's own limit for workflow_dispatch inputs
_KEY_RE = re.compile(r"^(?P<indent> *)(?P<key>\"[^\"]*\"|'[^']*'|[A-Za-z0-9_.-]+)\s*:(?:\s+(?P<rest>.*?))?\s*$")
_ITEM_RE = re.compile(r"^(?P<indent> *)-\s*(?P<rest>.*?)\s*$")
_ON_KEYS = ("on", "true")  # YAML 1.1 reads a bare on as true; GitHub reads the key as "on"


class Unreadable(ValueError):
    """The file is there, but this reader can't tell what it says."""


def _strip_comment(line: str) -> str:
    """A # at the start or after a space starts a comment, outside quotes."""
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
    return line.rstrip()


def _scalar(text: str | None):
    """A plain, quoted or empty scalar. None for nothing, null or ~."""
    if text is None:
        return None
    text = text.strip()
    if text in ("", "null", "~", "Null", "NULL"):
        return None
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    if text[0] in "&*!|>":
        raise Unreadable(f"uses YAML this reader doesn't follow ({text[:20]})")
    return text


def _flow_list(text: str) -> list[str]:
    """The items of `[a, b]` on one line. A list that runs on to the next line, or has an unclosed quote, is Unreadable;
    a comma inside quotes belongs to its item."""
    text = text.strip()
    if len(text) < 2 or text[0] != "[" or text[-1] != "]":
        raise Unreadable("a list in brackets that doesn't close on its line")
    inner = text[1:-1]
    parts, current, quote = [], "", None
    for ch in inner:
        if quote:
            if ch == quote:
                quote = None
            current += ch
        elif ch in "'\"":
            quote = ch
            current += ch
        elif ch == ",":
            parts.append(current)
            current = ""
        else:
            current += ch
    if quote:
        raise Unreadable("a quote in a list that doesn't close")
    parts.append(current)
    if any(("[" in p or "{" in p) and p.strip()[:1] not in "'\"" for p in parts):
        raise Unreadable("a nested list in brackets")
    return [v for v in (_scalar(part) for part in parts) if v is not None]


def _lines(text: str) -> list[tuple[int, str]]:
    out = []
    for raw in text.replace("\t", "    ").splitlines():
        line = _strip_comment(raw)
        if line.strip() and line.strip() not in ("---", "..."):
            out.append((len(line) - len(line.lstrip(" ")), line))
    return out


def _block(lines: list[tuple[int, str]], start: int, parent: int) -> list[tuple[int, str]]:
    """The lines under the one at start-1, more indented than parent."""
    out = []
    for indent, line in lines[start:]:
        if indent <= parent:
            break
        out.append((indent, line))
    return out


def _children(block: list[tuple[int, str]]) -> list[tuple[str, str | None, list[tuple[int, str]]]]:
    """A block mapping's keys at its first indent: (key, rest of the line, the lines under it)."""
    if not block:
        return []
    top = block[0][0]
    out = []
    for i, (indent, line) in enumerate(block):
        if indent != top:
            if indent < top:
                raise Unreadable("indentation this reader can't follow")
            continue
        if out and _ITEM_RE.match(line):  # a list may sit at its key's own indent: it belongs to that key
            out[-1][2].append((indent + 1, line))
            continue
        m = _KEY_RE.match(line)
        if not m:
            raise Unreadable(f"a line it can't read: {line.strip()[:60]}")
        out.append((_scalar(m["key"]), m["rest"], _block(block, i + 1, indent)))
    return out


def _options(rest: str | None, under: list[tuple[int, str]]) -> list[str]:
    if rest and rest.strip().startswith("["):
        return _flow_list(rest)
    if rest and rest.strip():
        raise Unreadable("options is a list")
    out = []
    for _indent, line in under:
        m = _ITEM_RE.match(line)
        if not m:
            raise Unreadable("options is a list")
        value = _scalar(m["rest"])
        if value is not None:
            out.append(value)
    return out


def _input(name: str, rest: str | None, under) -> dict:
    if rest and rest.strip() not in ("{}", ""):
        raise Unreadable(f"input {name}: its settings aren't a block")
    fields = {}
    for key, value, below in _children(under):
        if key == "options":
            fields["options"] = _options(value, below)
        elif below:
            raise Unreadable(f"input {name}: {key} spans lines")
        else:
            fields[key] = _scalar(value)
    kind = (fields.get("type") or "string").lower()
    if kind not in TYPES:
        raise Unreadable(f"input {name}: type {kind} isn't one this form knows")
    required = str(fields.get("required") or "false").lower() == "true"
    out = {"name": name, "type": kind, "required": required, "description": fields.get("description") or ""}
    default = fields.get("default")
    if default is not None:
        out["default"] = default.lower() == "true" if kind == "boolean" else default
    if kind == "choice":
        out["options"] = fields.get("options") or []
        if not out["options"]:
            raise Unreadable(f"input {name}: a choice with no options")
    return out


def dispatch_inputs(text: str) -> tuple[bool, list[dict]]:
    """(whether it can be started by hand, its inputs). Raises Unreadable when it can't tell."""
    lines = _lines(text)
    on_at = None
    for i, (indent, line) in enumerate(lines):
        m = _KEY_RE.match(line)
        if indent == 0 and m and str(_scalar(m["key"])).lower() in _ON_KEYS:
            on_at = i
            break
    if on_at is None:
        return False, []
    rest = _KEY_RE.match(lines[on_at][1])["rest"]
    if rest and rest.strip():
        rest = rest.strip()
        if rest.startswith("["):
            return "workflow_dispatch" in _flow_list(rest), []
        if rest.startswith("{"):
            raise Unreadable("on: written in braces")
        return _scalar(rest) == "workflow_dispatch", []
    under = _block(lines, on_at + 1, 0)
    if under and _ITEM_RE.match(under[0][1]):
        names = [_scalar(_ITEM_RE.match(line)["rest"]) for indent, line in under if indent == under[0][0] and _ITEM_RE.match(line)]
        return "workflow_dispatch" in names, []
    for key, value, below in _children(under):
        if key != "workflow_dispatch":
            continue
        if value and value.strip() not in ("{}", "null", "~"):
            raise Unreadable("workflow_dispatch: its settings aren't a block")
        for sub, sub_value, sub_below in _children(below):
            if sub != "inputs":
                continue
            if sub_value and sub_value.strip() not in ("{}", "null", "~"):
                raise Unreadable("inputs aren't a block")
            inputs = [_input(name, v, b) for name, v, b in _children(sub_below)]
            if len(inputs) > MAX_INPUTS:
                raise Unreadable(f"more than {MAX_INPUTS} inputs")
            return True, inputs
        return True, []
    return False, []
