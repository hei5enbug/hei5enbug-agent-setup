"""Custom checks for T160: a read-only lookup through a stub `aside`, answered with the status and its source only."""

from __future__ import annotations

import json
from pathlib import Path

SKILL = "aside-browser-tasks"
AGENT = "browser-reader"
TRACE_MARKER = "TRACE-NOISE"
WRITE_WORDS = ("screenshot", ".click(", ".fill(", "method: 'POST'", 'method: "POST"', "submit")


def aside_calls(ctx) -> list[list[str]]:
    path = Path(ctx.origin).parent / "aside.log"
    if not path.is_file():
        return []
    return [json.loads(line)["argv"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def is_main(call) -> bool:
    return call.get("parent") is None and call.get("source", "main") == "main"


def skill_invoked(ctx):
    calls = [call for call in ctx.view.get("tool_calls", []) if call.get("name") == "Skill"
             and str((call.get("input") or {}).get("skill", "")).endswith(SKILL)]
    return bool(calls), f"{len(calls)} call(s) of the {SKILL} skill", {}


def aside_ran(ctx):
    calls = aside_calls(ctx)
    return bool(calls), f"{len(calls)} aside call(s)", {}


def no_trace_in_answer(ctx):
    answer = str(ctx.view.get("final_answer", ""))
    return TRACE_MARKER not in answer, "the answer holds no tool trace" if TRACE_MARKER not in answer else (
        "the answer holds the stub's tool trace"), {}


def read_only(ctx):
    writes = [call for call in aside_calls(ctx) if any(word in " ".join(call) for word in WRITE_WORDS)]
    return not writes, f"{len(writes)} aside call(s) that write or take a screenshot", {"writes": writes}


def browser_reader_used(ctx):
    agents = [item for item in ctx.view.get("delegations", []) if str(item.get("type", "")).endswith(AGENT)]
    return bool(agents), f"{len(agents)} {AGENT} delegation(s)", {}


def main_ran_no_aside(ctx):
    commands = [str((call.get("input") or {}).get("command", "")) for call in ctx.view.get("tool_calls", [])
                if call.get("name") == "Bash" and is_main(call)]
    ran = [text for text in commands if "aside " in text]
    return not ran, f"{len(ran)} main-session command(s) that run aside", {}
