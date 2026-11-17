"""Custom checks for T61: the host command goes to the never-used shell terminal, and no terminal is created."""

from __future__ import annotations

import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "handoff_shared.py"
    module = types.ModuleType("handoff_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


SHELL = "term_demo_b_shell"


def host_command_in_shell_terminal(ctx):
    h, problems = shared(ctx), []
    sends = h.succeeded(h.calls_of(ctx), ("terminal", "send"))
    started = [(index, call) for index, call in sends if h.HOST_COMMAND.match((h.option(call, "--text") or "").strip())]
    if not started:
        problems.append("no host command was sent to any terminal")
    for _, call in started:
        if h.option(call, "--terminal") != SHELL:
            problems.append(f"the host command went to {h.option(call, '--terminal')}")
        if "--enter" not in call["argv"]:
            problems.append("the host command was typed without Enter")
    return h.verdict(problems, "the host command was sent to the never-used shell terminal")


def no_terminal_created(ctx):
    h = shared(ctx)
    created = h.succeeded(h.calls_of(ctx), ("terminal", "create"))
    return h.verdict([f"{len(created)} terminal(s) were created"] if created else [], "no terminal was created")


def brief_says_terminal_belongs(ctx):
    h, problems = shared(ctx), []
    sends = h.succeeded(h.calls_of(ctx), ("terminal", "send"), terminal=SHELL)
    started = [index for index, call in sends if h.HOST_COMMAND.match((h.option(call, "--text") or "").strip())]
    briefs = [index for index, call in sends if h.BELONGS.search(h.option(call, "--text") or "")]
    if not briefs:
        problems.append("no brief says that the terminal belongs to the handoff")
    elif not started or started[0] > briefs[0]:
        problems.append("the brief was sent before the agent was started")
    return h.verdict(problems, "the brief says that the terminal belongs to the handoff")
