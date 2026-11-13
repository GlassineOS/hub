# SPDX-License-Identifier: GPL-2.0-or-later
"""For tests that write a workflow's text of their own: the [launch] and [[start]] tables of its file, to put back."""
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[1] / "agents"


def launch_block(name: str, root: Path = AGENTS) -> str:
    """The file's [launch] and [[start]] tables, as its text has them (they come before its states)."""
    text = (root / "workflows" / f"{name}.toml").read_text()
    lines = text.splitlines()
    at = lines.index("[launch]")
    end = next(i for i in range(at, len(lines)) if lines[i].startswith("[state."))
    return "\n".join(lines[at:end]).rstrip() + "\n"


def with_launch(text: str, name: str, root: Path = AGENTS) -> str:
    """A workflow text of a test's own, with the file's launch and starts after its states. Its starts ask a holding instance's
    owner, as the test's grant may write where the file's doesn't."""
    return text.rstrip("\n") + "\n\n" + launch_block(name, root).replace('when_held = "beside"', 'when_held = "ask"')


def launch(name: str, on: str = "issue", label: str | None = None, personas=("triager",), result: str = "comment",
           prompt: str = "Work on #{number} of GlassineOS/{repo}.", order: int = 90, models=("sonnet",), efforts=("low",),
           start: bool = True) -> str:
    """A [launch] and, unless `start` is False, one [[start]] for a test's own workflow."""
    q = lambda xs: "[" + ", ".join(f'"{x}"' for x in xs) + "]"  # noqa: E731
    head = f'\n[launch]\npersonas = {q(personas)}\nresult = "{result}"\n'
    body = (f'on = "{on}"\nlabel = "{label or name}"\nsummary = "A helper on the {on}."\nceiling = "Reads the {on}."\norder = {order}\n'
            f'models = {q(models)}\nefforts = {q(efforts)}\nprompt = "{prompt}"\n')
    return head + ("\n[[start]]\n" + body if start else body)


def with_start_again(root: Path, name: str, on: str = "issue") -> None:
    """Gives a workflow without starts (one kept so its sessions resume) a start again, in a test's copy of the library,
    for tests that start its sessions directly. The start takes everything else from its launch."""
    path = root / "workflows" / f"{name}.toml"
    path.write_text(start_again(path.read_text(), name, on))


def start_again(text: str, name: str, on: str = "issue") -> str:
    """The text with_start_again writes."""
    return text.rstrip("\n") + f'\n\n[[start]]\non = "{on}"\nlabel = "{name} (a test start)"\n'


def library_root(tmp_path: Path, *again: str) -> Path:
    """A copy of agents/ in which these workflows without starts have one again."""
    import shutil
    root = tmp_path / "agents-copy"
    shutil.copytree(AGENTS, root)
    for name in again:
        with_start_again(root, name)
    return root
