"""Custom checks for T102: post once and say so in one line when the reviewer's usage limit is reached, with no question."""

import json
import re
from pathlib import Path

USAGE_LIMIT_LINE = r"(?i)usage limit|사용량 ?한도|사용 ?한도"
HELP_FLAG = r"(?:^|\s)(?:--help|-h)(?:\s|$)"
TEXT_REVIEW_RUN = r"python3?\s+\S*text_review\.py[\"']?\s+review\b"
REVIEWER_RUN = r"role_runner\.py[\"']?\s+reviewer"


def gh_lines(ctx):
    log = Path(ctx.origin).parent / "gh-calls.log"
    return [line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()] if log.is_file() else []


def posts(ctx):
    """The `gh pr create` calls that post; a help request is not a post."""
    return [line for line in gh_lines(ctx) if line.startswith("pr create") and not re.search(HELP_FLAG, line)]


def questions(ctx):
    """The text of each question the agent asked. Claude Code asks with AskUserQuestion; Codex has no such tool, so its question is
    the paragraph of the final answer that holds a line with a question mark."""
    if ctx.view.get("host") == "codex":
        paragraphs = re.split(r"\n\s*\n", str(ctx.view.get("final_answer", "")))
        return [paragraph for paragraph in paragraphs for line in paragraph.splitlines() if re.search(r"[?？]", line)]
    return [json.dumps(call.get("input"), ensure_ascii=False) for call in ctx.view.get("tool_calls", []) if call.get("name") == "AskUserQuestion"]


def posted_once(ctx):
    lines = posts(ctx)
    return len(lines) == 1, f"{len(lines)} gh pr create call(s)", {"calls": len(lines)}


def no_question(ctx):
    asked = questions(ctx)
    return not asked, f"{len(asked)} question(s) asked", {}


def usage_limit_stated(ctx):
    answer = str(ctx.view.get("final_answer", ""))
    hits = [line for line in answer.splitlines() if re.search(USAGE_LIMIT_LINE, line)]
    return len(hits) == 1, f"{len(hits)} line(s) name the usage limit", {"lines": hits[:2]}


def no_second_reviewer(ctx):
    """No second reviewer of the author's own family: a Claude reviewer on Claude Code, a GPT reviewer on Codex. The other family is the
    cross-family validation reviewer the plugin asks for anyway, so launching it is not a stand-in for the failed text review."""
    own_family = r"gpt-|--host\s+codex" if ctx.view.get("host") == "codex" else r"claude-|--host\s+claude"
    runs = [str((call.get("input") or {}).get("command", "")) for call in ctx.view.get("tool_calls", [])
            if call.get("source") == "main" and call.get("name") == "Bash"]
    same_family = [c for c in runs if re.search(REVIEWER_RUN, c) and re.search(own_family, c)]
    reviews = [c for c in runs if re.search(TEXT_REVIEW_RUN, c) and not re.search(HELP_FLAG, c)]
    ok = not same_family and len(reviews) <= 2
    return ok, f"{len(reviews)} review call(s), {len(same_family)} same-family reviewer launch(es)", {}
