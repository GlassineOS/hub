# SPDX-License-Identifier: GPL-2.0-or-later
"""The limits the code map's builder and code search's ripgrep both run under."""
import json
import subprocess
import sys

from hubd import codemap, codesearch, limits


def test_a_child_started_with_apply_has_the_limits():
    # Read in the child itself, in bytes: a shell's `ulimit` counts blocks, and rounds a core limit of one byte down to zero.
    show = "import json, os, resource as r; print(json.dumps([list(r.getrlimit(k)) for k in (r.RLIMIT_AS, r.RLIMIT_FSIZE, r.RLIMIT_CORE)] + [os.nice(0)]))"
    memory, file_size, core, nice = json.loads(subprocess.run([sys.executable, "-c", show], preexec_fn=limits.apply, capture_output=True, text=True, check=True).stdout)
    assert memory == [limits.MAX_MEMORY] * 2 and file_size == [limits.MAX_OUTPUT] * 2 and core == [0, 0]
    assert nice >= 15


def test_both_users_start_their_program_with_it():
    # The two tests that run a stand-in builder and a stand-in ripgrep show the limits arrive; this shows nobody keeps a copy of the numbers.
    for module in (codemap, codesearch):
        assert module.limits is limits
        assert not hasattr(module, "_limits") and not hasattr(module, "MAX_MEMORY") and not hasattr(module, "MAX_OUTPUT")
