# SPDX-License-Identifier: GPL-2.0-or-later
"""Which repositories a question that spans the organization looks in.

The code map and code search both answer from the hub's copies, so they keep one rule, written once here: a private
repository is looked in when it's named, or for a session that reads the whole project, and with no name an agent doesn't
get private text by asking about a topic, as for `work_search`. Whatever is left out is listed, with why, in every reply.
A repository that doesn't say whether it's private counts as private, and one that doesn't say whether it's a fork as a fork.
"""
from __future__ import annotations

PRIVATE = "private: name it to search it"
UNKNOWN = ("{} isn't a repository of the organization that the hub knows of. "
           "Code outside the organization stays out of reach: say you couldn't check it")


class ReachError(Exception):
    pass


def is_private(record: dict) -> bool:
    return record.get("private", True) is not False


def is_fork(record: dict) -> bool:
    return bool(record.get("fork", True))


def choose(repos: dict, repo, everything: bool, *, fork_why: str, forks_when_named: bool, unready) -> tuple[list[str], list[dict]]:
    """The repositories to look in, and what's left out and why.

    repos is the hub's list of them, from `Seeds.status()`. A fork is looked in when it's named, if forks_when_named, and never
    otherwise. unready(name, named) says why a repository can't be looked in yet, or None: for one that was named it's the
    whole error to raise, and for the rest the reason to list.
    """
    if repo not in (None, ""):
        if repo not in repos:
            raise ReachError(UNKNOWN.format(repo))
        if is_fork(repos[repo]) and not forks_when_named:
            raise ReachError(f"{repo} is {fork_why}")
        why = unready(repo, True)
        if why:
            raise ReachError(why)
        return [repo], []
    chosen, left_out = [], []
    for name, record in sorted(repos.items()):
        private = is_private(record)
        if is_fork(record):
            left_out.append({"repo": name, "private": private, "why": fork_why})
        elif private and not everything:
            left_out.append({"repo": name, "private": True, "why": PRIVATE})
        elif (why := unready(name, False)):
            left_out.append({"repo": name, "private": private, "why": why})
        else:
            chosen.append(name)
    return chosen, left_out
