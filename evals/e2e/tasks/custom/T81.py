"""Custom checks for T81: the fake Orca's call log beside the run's repository and the final answer."""

from __future__ import annotations

import json
import re
from pathlib import Path

FIRST, CONTROL = "term_demo_a", "term_demo_b"
RELOAD = "/reload-plugins"
UNFINISHED = re.compile(r"skipped|not[ _]idle|deferred|건너뛰|건너뜀|미뤄|미룸|보류|대기 중|바빠|바쁜|쉬지 않|한가하지 않", re.IGNORECASE)


def calls_of(ctx) -> list[dict]:
    path = Path(ctx.origin).parent / "orca-state" / "calls.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def option(argv: list[str], name: str) -> str | None:
    return argv[argv.index(name) + 1] if name in argv[:-1] else None


def changes_to(ctx, handle: str) -> list[dict]:
    """Every call that sends text to, or closes, the terminal."""
    found = []
    for call in calls_of(ctx):
        argv = call["argv"]
        if tuple(argv[:2]) in (("terminal", "send"), ("terminal", "close")) and option(argv, "--terminal") == handle:
            found.append({"action": argv[1], "text": option(argv, "--text")})
    return found


def reload_sent_to_running_session(ctx):
    sent = [change for change in changes_to(ctx, FIRST) if change["action"] == "send" and (change["text"] or "").strip() == RELOAD]
    return bool(sent), f"{len(sent)} reload(s) sent to the running session", {"sent": len(sent)}


def nothing_else_sent_to_running_session(ctx):
    others = [change for change in changes_to(ctx, FIRST) if (change["text"] or "").strip() != RELOAD]
    return not others, "only the reload reached it" if not others else f"also sent or closed: {others[:3]}", {"others": others}


def nothing_sent_to_control_session(ctx):
    touched = changes_to(ctx, CONTROL)
    return not touched, "untouched" if not touched else f"changed: {touched[:3]}", {"touched": touched}


def running_session_not_reported_unfinished(ctx):
    lines = [line for line in ctx.view.get("final_answer", "").splitlines() if re.search(r"demo[_-]a", line, re.IGNORECASE)]
    bad = [line for line in lines if UNFINISHED.search(line)]
    return not bad, "not reported as skipped or not idle" if not bad else f"reported as unfinished: {bad[:2]}", {"lines": bad}
