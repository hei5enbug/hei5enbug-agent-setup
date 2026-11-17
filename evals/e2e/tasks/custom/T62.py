"""Custom checks for T62: the hook closes the never-used shell terminal at the first prompt and touches no other terminal."""

from __future__ import annotations

import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "handoff_shared.py"
    module = types.ModuleType("handoff_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module



def never_used_closed_first(ctx):
    h, problems = shared(ctx), []
    calls = h.calls_of(ctx)
    closed = h.succeeded(calls, ("terminal", "close"), terminal="term_idle")
    if "term_idle" in h.terminal_handles(h.state_of(ctx)):
        problems.append("the never-used terminal is still open")
    if not closed:
        problems.append("no close of the never-used terminal succeeded")
    else:
        other = [index for index, call in enumerate(calls) if h.pair(call) not in h.HOOK_PAIRS]
        if other and other[0] < closed[0][0]:
            problems.append("the terminal was closed only after the session's own Orca calls began")
    return h.verdict(problems, "closed before the session's first Orca call")


def other_terminals_untouched(ctx):
    h, problems = shared(ctx), []
    state, calls = h.state_of(ctx), h.calls_of(ctx)
    for handle in ("term_typed", "term_demo_a"):
        if handle not in h.terminal_handles(state):
            problems.append(f"{handle} was closed")
        sent = h.touched(calls, handle)
        if sent:
            problems.append(f"{handle} received a command: {sent[:2]}")
    return h.verdict(problems, "the terminal with typed input and the session's own terminal are untouched")
