"""Custom checks for T102: post once and say so in one line when the reviewer's usage limit is reached, with no question."""

import re
from pathlib import Path


def gh_lines(ctx):
    log = Path(ctx.work) / "gh-calls.log"
    return [line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()] if log.is_file() else []


def posted_once(ctx):
    lines = [line for line in gh_lines(ctx) if line.startswith("pr create")]
    return len(lines) == 1, f"{len(lines)} gh pr create call(s)", {"calls": len(lines)}


def no_question(ctx):
    asked = [call for call in ctx.view.get("tool_calls", []) if call.get("name") == "AskUserQuestion"]
    return not asked, f"{len(asked)} AskUserQuestion call(s)", {}


def usage_limit_stated(ctx):
    answer = str(ctx.view.get("final_answer", ""))
    hits = [line for line in answer.splitlines() if re.search(r"(?i)usage limit", line)]
    return len(hits) == 1, f"{len(hits)} line(s) name the usage limit", {"lines": hits[:2]}


def no_second_reviewer(ctx):
    runs = [str((call.get("input") or {}).get("command", "")) for call in ctx.view.get("tool_calls", [])
            if call.get("source") == "main" and call.get("name") == "Bash"]
    claude_review = [c for c in runs if re.search(r"role_runner\.py\s+reviewer", c) and re.search(r"claude-|--host\s+claude", c)]
    reviews = [c for c in runs if re.search(r"text_review\.py", c) and re.search(r"\breview\b", c)]
    ok = not claude_review and len(reviews) <= 2
    return ok, f"{len(reviews)} review call(s), {len(claude_review)} Claude reviewer launch(es)", {}
