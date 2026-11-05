# SPDX-License-Identifier: GPL-2.0-or-later
"""A pull request diff cut down to a token budget, for agents that need its shape, not every line.

Pure functions, standard library only. `compress` keeps the file list first, leaves out the hunks
of files nobody reads line by line, drops context lines, and shares the rest of the room between
the files. Whatever it cuts, it says so in words. A diff that already fits comes back unchanged.
"""
from __future__ import annotations

import re

BUDGET_TOKENS = 6000
CHARS_PER_TOKEN = 4  # a rough estimate, good enough for a budget
BUDGET = BUDGET_TOKENS * CHARS_PER_TOKEN
NOTE_ROOM = 220  # kept free per clamped file for its "cut" sentence
FULL_FETCH = 'get_pr_diff(repo, number, path="...") fetches one file in full.'

_LOCK_NAMES = {"package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "cargo.lock", "poetry.lock",
               "uv.lock", "pipfile.lock", "gemfile.lock", "composer.lock", "go.sum", "flake.lock", "pdm.lock",
               "mix.lock", "pubspec.lock", "packages.lock.json", "podfile.lock"}
_VENDORED_DIRS = {"vendor", "node_modules", "third_party", "third-party", "thirdparty"}
_GENERATED = re.compile(r"(\.pb\.go|_pb2(_grpc)?\.pyi?|\.pb\.cc|\.pb\.h|\.generated\.[a-z]+|_generated\.[a-z]+|\.designer\.cs)$")
_MINIFIED = re.compile(r"(\.min\.(js|css|mjs)|\.(js|css)\.map|\.bundle\.js)$")


class Missing(KeyError):
    """The diff has no file with that path."""


def tokens(text: str) -> int:
    return -(-len(text) // CHARS_PER_TOKEN)


class _File:
    def __init__(self, lines: list[str]):
        self.raw = lines
        split = next((i for i, l in enumerate(lines) if l.startswith("@@")), len(lines))
        self.head, self.body = lines[:split], lines[split:]
        self.old, self.new = _names(lines[0], self.head)
        self.path = self.new if self.new != "/dev/null" else self.old
        self.added = sum(1 for l in self.body if l.startswith("+"))
        self.removed = sum(1 for l in self.body if l.startswith("-"))
        text = "\n".join(self.head)
        self.binary = "GIT binary patch" in text or bool(re.search(r"^Binary files .* differ$", text, re.M))
        if self.old == "/dev/null":
            self.status = "A"
        elif self.new == "/dev/null":
            self.status = "D"
        elif self.old != self.new:
            self.status = "R"
        else:
            self.status = "M"
        self.skip = self._why_skip()

    def _why_skip(self) -> str | None:
        parts = self.path.lower().split("/")
        if self.binary:
            return "binary file"
        if parts[-1] in _LOCK_NAMES or parts[-1].endswith(".lock"):
            return "lock file"
        if _MINIFIED.search(parts[-1]):
            return "minified file"
        if _VENDORED_DIRS & set(parts[:-1]):
            return "vendored file"
        if _GENERATED.search(parts[-1]):
            return "generated file"
        return None

    def line(self) -> str:
        name = f"{self.old} -> {self.new}" if self.status == "R" else self.path
        return f"{self.status} {name}  +{self.added} -{self.removed}" + (f"  ({self.skip}, hunks left out)" if self.skip else "")

    def changed(self) -> list[str]:
        """The file header and its changed lines, without context."""
        head = [l for l in self.head if not l.startswith("index ")]
        return head + [l for l in self.body if l[:1] in ("+", "-", "@") or l.startswith("\\")]


def _unquote(name: str) -> str:
    return name[1:-1] if len(name) > 1 and name[0] == name[-1] == '"' else name


def _names(first: str, head: list[str]) -> tuple[str, str]:
    """Old and new path. Spaces in names make the first line ambiguous, so the other header lines go first."""
    old = new = None
    for l in head:
        if l.startswith("rename from "):
            old = l[12:]
        elif l.startswith("rename to "):
            new = l[10:]
        elif l.startswith("--- ") and old is None:
            old = _unquote(l[4:].split("\t")[0])
            old = old if old == "/dev/null" else old[2:]
        elif l.startswith("+++ ") and new is None:
            new = _unquote(l[4:].split("\t")[0])
            new = new if new == "/dev/null" else new[2:]
    if old and new:
        return old, new
    rest = _unquote(first[len("diff --git "):])
    m = re.fullmatch(r"a/(.+) b/\1", rest)  # no ---/+++ lines: a mode change, or an empty file
    if m:
        return m[1], m[1]
    m = re.fullmatch(r"a/(\S+) b/(\S+)", rest) or re.fullmatch(r"a/(.+) b/(.+)", rest)
    return (old or (m[1] if m else rest)), (new or (m[2] if m else rest))


def parse(diff: str) -> list[_File]:
    lines = diff.split("\n")
    starts = [i for i, l in enumerate(lines) if l.startswith("diff --git ")]
    return [_File(lines[a:b]) for a, b in zip(starts, starts[1:] + [len(lines)])]


def one_file(diff: str, path: str) -> str:
    """The full diff of one file, by its new path (or its old one, for a rename). Raises Missing."""
    for f in parse(diff):
        if path in (f.new, f.old) and path != "/dev/null":
            return "\n".join(f.raw).rstrip("\n") + "\n"
    raise Missing(path)


def _clamp(lines: list[str], room: int) -> tuple[list[str], int]:
    kept, used = [], 0
    for l in lines:
        if used + len(l) + 1 > room:
            break
        kept.append(l)
        used += len(l) + 1
    return kept, len(lines) - len(kept)


def _shares(sizes: dict[int, int], room: int) -> dict[int, int]:
    """Fair shares: a small file gets all it needs, and the rest split what is left, so one giant can't take it all."""
    out, left = {}, room
    order = sorted(sizes, key=sizes.get)
    for n, k in enumerate(order):
        share = max(left, 0) // (len(order) - n)
        out[k] = min(sizes[k], share)
        left -= out[k]
    return out


def compress(diff: str, more: str = FULL_FETCH, budget: int = BUDGET) -> str:
    """The diff itself if it fits `budget` characters; otherwise a summary that says what it left out."""
    if len(diff) <= budget:
        return diff
    files = parse(diff)
    if not files:
        kept, cut = _clamp(diff.split("\n"), budget)
        return "\n".join(kept) + f"\n[Cut: {cut} more lines of a diff that has no files in the usual form. {more}]\n"
    added, removed = sum(f.added for f in files), sum(f.removed for f in files)
    listing = [f"Diff of {len(files)} files, +{added} -{removed}. It is longer than about {budget // CHARS_PER_TOKEN} tokens, so this is a short form.",
               "Files:"] + ["  " + f.line() for f in files] + [""]
    bodies = {i: f.changed() for i, f in enumerate(files) if not f.skip}
    room = budget - sum(len(l) + 1 for l in listing) - 400 - NOTE_ROOM * len(bodies)
    shares = _shares({i: sum(len(l) + 1 for l in b) for i, b in bodies.items()}, room)
    out, clamped, hidden = list(listing), [], [f for f in files if f.skip]
    for i, b in bodies.items():
        kept, cut = _clamp(b, shares[i])
        out += kept
        if cut:
            clamped.append(files[i].path)
            out.append(f"[Cut: {cut} of {len(b)} lines of the changes to {files[i].path} are not shown. {more}]")
        out.append("")
    notes = ["Cut from this view:", "- Unchanged context lines are left out everywhere."]
    if hidden:
        notes.append(f"- Hunks of {len(hidden)} file(s) left out, named in the list above with the reason: " + ", ".join(f.path for f in hidden) + ".")
    if clamped:
        notes.append(f"- Changed lines cut from {len(clamped)} file(s) that did not fit: " + ", ".join(clamped) + ".")
    notes.append(f"Nothing else was cut. {more}")
    return "\n".join(out + notes) + "\n"


def one_file_short(diff: str, path: str, more: str, budget: int = BUDGET) -> str:
    """One file's diff, cut to the budget with a sentence saying so, for a reader who cannot fetch more."""
    text = one_file(diff, path)
    if len(text) <= budget:
        return text
    kept, cut = _clamp(text.rstrip("\n").split("\n"), budget - NOTE_ROOM)
    return "\n".join(kept) + f"\n[Cut: the last {cut} lines of this file's diff are not shown, because it is longer than about {budget // CHARS_PER_TOKEN} tokens. {more}]\n"
