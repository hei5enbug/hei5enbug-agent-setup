"""Close the never-used shell terminals that sit beside a session's own terminal in its Orca worktree.

A never-used shell terminal runs no agent, shows only a shell prompt with an empty input line, and holds no command in
its output. The caller passes in `run`, a function that runs `orca <arguments> --json` and returns the parsed payload or
None, so this module starts no process of its own and never sends input to a terminal.
"""

from __future__ import annotations

import time
from collections.abc import Callable

PROMPT_ENDINGS = ("%", "$", "#", ">", "❯")
BANNER = "Last login"
BUDGET_SECONDS = 4.0

Run = Callable[..., "dict | None"]


def is_bare_prompt(line: str) -> bool:
    """True for a line that is a shell prompt with nothing typed after it."""
    text = line.rstrip()
    if not text or not text.endswith(PROMPT_ENDINGS):
        return False
    before = text[:-1]
    return not before or before[-1].isspace() or text.endswith("❯")


def lines_of(tail: object) -> list[str] | None:
    """The lines of a terminal read, which Orca may give as a list or as one text, or None for anything else."""
    if isinstance(tail, str):
        return tail.splitlines()
    return tail if isinstance(tail, list) and all(isinstance(line, str) for line in tail) else None


def only_prompts(tail: object) -> bool:
    """True when the non-blank lines of `tail` are all bare prompts, apart from a shell's login banner, and one exists."""
    lines = lines_of(tail)
    if lines is None:
        return False
    shown = [line for line in lines if line.strip() and not line.lstrip().startswith(BANNER)]
    return bool(shown) and all(is_bare_prompt(line) for line in shown)


def read_terminal(run: Run, handle: str, screen: bool) -> dict | None:
    arguments = ["terminal", "read", "--terminal", handle, *(["--screen"] if screen else [])]
    payload = run(*arguments)
    try:
        terminal = payload["result"]["terminal"]
    except (KeyError, TypeError):
        return None
    if not isinstance(terminal, dict) or terminal.get("status") != "running" or terminal.get("draft"):
        return None
    if screen and terminal.get("source") != "screen":
        return None
    return terminal


def never_used(run: Run, handle: str) -> bool:
    """Read the output, then the screen last, so typing that began in between still shows; judge both."""
    stream = read_terminal(run, handle, screen=False)
    if stream is None or not only_prompts(stream.get("tail")):
        return False
    screen = read_terminal(run, handle, screen=True)
    return screen is not None and only_prompts(screen.get("tail")) and len(
        [line for line in lines_of(screen["tail"]) if line.strip()]) == 1


def sibling_terminals(run: Run, own_handle: str) -> list[dict]:
    """Return the terminals of the worktree that holds `own_handle`, or none when that terminal is not listed."""
    payload = run("terminal", "list")
    try:
        terminals = payload["result"]["terminals"]
    except (KeyError, TypeError):
        return []
    if not isinstance(terminals, list):
        return []
    terminals = [item for item in terminals if isinstance(item, dict) and isinstance(item.get("handle"), str)]
    own = next((item for item in terminals if item["handle"] == own_handle), None)
    if own is None or not isinstance(own.get("worktreeId"), str):
        return []
    return [item for item in terminals if item.get("worktreeId") == own["worktreeId"]]


def close_unused(run: Run, own_handle: str, budget: float = BUDGET_SECONDS) -> list[str]:
    """Close each never-used shell terminal of the own worktree except the own one; return the closed handles."""
    deadline = time.monotonic() + budget
    closed: list[str] = []
    for terminal in sibling_terminals(run, own_handle):
        if time.monotonic() > deadline:
            break
        handle = terminal["handle"]
        if handle == own_handle or terminal.get("agentIdentity"):
            continue
        if never_used(run, handle) and run("terminal", "close", "--terminal", handle) is not None:
            closed.append(handle)
    return closed
