"""Shared helpers for the scout cases T150 to T152: read the scout's result from the main session's Agent call."""

import re

AGENT_TOOLS = ("Agent", "Task")


def scout_calls(ctx):
    return [call for call in ctx.view.get("tool_calls", [])
            if call.get("source") == "main" and call.get("name") in AGENT_TOOLS
            and str((call.get("input") or {}).get("subagent_type") or "").split(":")[-1] == "scout"]


def scout_text(ctx):
    calls = scout_calls(ctx)
    return str(calls[0].get("result_text", "")) if calls else ""


HAND_BACK_FRAME = re.compile(r"\A\s*\[Subagent hand-back\].*?The report follows:[ \t]*\n", re.DOTALL)
STATUS_WORD = re.compile(r"\W*(?:status\W{0,4})?([A-Za-z]+)", re.IGNORECASE)


def report_body(text):
    """The scout's own report: without the hand-back frame the host puts before it, and with its two-space indent removed."""
    body = HAND_BACK_FRAME.sub("", text, count=1)
    return "\n".join(line[2:] if line.startswith("  ") else line for line in body.split("\n")) if body != text else text


def first_word(text):
    """The status word a report starts with, read after the hand-back frame and an optional `Status:` label."""
    match = STATUS_WORD.match(report_body(text))
    return match.group(1).lower() if match else ""


def ran_once(ctx):
    calls = scout_calls(ctx)
    ok = len(calls) == 1 and not calls[0].get("is_error") and bool(str(calls[0].get("result_text", "")).strip())
    return ok, f"{len(calls)} scout call(s)", {"calls": len(calls)}
