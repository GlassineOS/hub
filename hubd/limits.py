# SPDX-License-Identifier: GPL-2.0-or-later
"""Limits on a program hubd starts to work on the hub's copies.

The code map's builder and code search's ripgrep read whatever the repositories hold, and this host is someone's desktop: neither may
use most of its memory, fill its disk or compete with what the person is doing. Both start their program with `apply`, so the numbers are
written once. What is particular to one of them, such as how long it may run or how much scratch space it gets, stays with it.
"""
from __future__ import annotations

import os
import resource

MAX_MEMORY = 2 * 1024 ** 3  # bytes of address space
MAX_OUTPUT = 512 * 1024 ** 2  # bytes in any one file it writes


def apply() -> None:
    """In the child, before it runs: limits on this process and whatever it starts, and it comes after everything else on the host."""
    resource.setrlimit(resource.RLIMIT_AS, (MAX_MEMORY, MAX_MEMORY))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT, MAX_OUTPUT))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.nice(15)
