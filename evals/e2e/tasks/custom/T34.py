"""Custom checks for T34: a session closes the never-used shell terminal in its workspace, in code, and nothing else."""

from __future__ import annotations

import re
import types
from pathlib import Path

EMPTY, TYPED = "term_shell_empty", "term_shell_typed"
CLOSE_COMMAND = re.compile(r"orca\s+terminal\s+close")


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "handoff_shared.py"
    module = types.ModuleType("handoff_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def never_used_terminal_closed(ctx):
    s = shared(ctx)
    problems = []
    if s.terminal_entry(ctx, EMPTY) is not None:
        problems.append("the never-used shell terminal is still open")
    if not [call for call in s.closes_of(ctx, EMPTY) if call["ok"]]:
        problems.append("no successful close of it was recorded")
    return s.result(problems, "closed")


def closed_without_a_model_turn(ctx):
    s = shared(ctx)
    typed = [command[:120] for command in s.bash_commands(ctx) if CLOSE_COMMAND.search(command)]
    problems = [f"the agent ran a close command itself: {typed[:2]}"] if typed else []
    return s.result(problems, "the agent ran no terminal close")


def typed_terminal_untouched(ctx):
    s = shared(ctx)
    problems = []
    baseline = s.baseline_of(ctx)["terminals"][TYPED]
    if s.terminal_entry(ctx, TYPED) != baseline:
        problems.append("the terminal is closed or changed")
    touched = [call["argv"] for call in s.calls_of(ctx)
               if s.pair(call) in (("terminal", "send"), ("terminal", "close")) and s.option(call, "--terminal") == TYPED]
    if touched:
        problems.append(f"a send or close named it: {touched[:2]}")
    return s.result(problems, "open, with its typed input and no input sent")


def own_terminal_open(ctx):
    s = shared(ctx)
    problems = [] if s.terminal_entry(ctx, s.OWN_HANDLE) is not None else ["the session's own terminal is closed"]
    return s.result(problems, "the session's own terminal is open")
