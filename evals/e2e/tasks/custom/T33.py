"""Custom checks for T33: a handoff to a workspace whose only terminal is a never-used shell terminal."""

from __future__ import annotations

import types
from pathlib import Path

SHELL = "term_shell_b"


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "handoff_shared.py"
    module = types.ModuleType("handoff_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def host_sends(ctx, s) -> list[dict]:
    return [call for call in s.calls_named(ctx, "terminal", "send") if s.HOST_COMMAND.match(s.option(call, "--text") or "")]


def no_terminal_created(ctx):
    s = shared(ctx)
    created = s.calls_named(ctx, "terminal", "create", ok_only=False)
    problems = [f"a terminal was created: {created[0]['argv']}"] if created else []
    return s.result(problems, "no terminal was created")


def host_command_sent_to_the_shell(ctx):
    s = shared(ctx)
    sends = host_sends(ctx, s)
    problems = []
    if not sends:
        problems.append("no host command was sent")
    wrong = [s.option(call, "--terminal") for call in sends if s.option(call, "--terminal") != SHELL]
    if wrong:
        problems.append(f"a host command went to a terminal other than the never-used shell: {wrong}")
    if sends and not any(call["argv"].count("--enter") for call in sends):
        problems.append("the host command was typed but never submitted")
    return s.result(problems, "the host command went to the never-used shell terminal")


def brief_says_terminal_belongs_to_handoff(ctx):
    s = shared(ctx)
    terminal = s.terminal_entry(ctx, SHELL)
    briefs = [text for text in (terminal or {}).get("received", []) if s.BELONGS.search(text)]
    problems = [] if briefs else ["no brief sent to that terminal says it belongs to the handoff"]
    return s.result(problems, "the brief says the terminal belongs to the handoff")


def brief_names_reply_terminal(ctx):
    s = shared(ctx)
    terminal = s.terminal_entry(ctx, SHELL)
    briefs = [text for text in (terminal or {}).get("received", []) if s.OWN_HANDLE in text]
    problems = [] if briefs else ["no brief sent to that terminal names the terminal to report to"]
    return s.result(problems, "the brief names the terminal to report to")
