"""Shared by the custom checks of the requirements agreement tasks: what the scripted user was asked, and in what order.

A run of these tasks keeps `view["conversation"]`: the exchanges of the scripted user, each with the decisions its question
matched, and one ordered timeline of the agent's texts, its calls, and those exchanges. Positions below are indexes in that
timeline, so "before" and "between" mean what the agent did in that order. A run without a log has no exchange.
"""

from __future__ import annotations

import re

from harness import timeline

ASK_TOOL = "AskUserQuestion"


def conversation(ctx):
    held = ctx.view.get("conversation") or {}
    return list(held.get("exchanges") or []), list(held.get("timeline") or [])


def asked_with_tool(ctx) -> bool:
    return any(call.get("name") == ASK_TOOL for call in ctx.view.get("tool_calls", []))


def question_count(ctx) -> int:
    exchanges, _ = conversation(ctx)
    return len(exchanges)


def about(exchanges, decision):
    """Exchanges whose question matched the decision, in order."""
    return [item for item in exchanges if decision in (item.get("matched") or [])]


def where(items, exchange):
    return timeline.position_of(items, exchange["index"])


def edits_between(items, start, end):
    """Edit calls strictly between two positions."""
    return [item for item in items[start + 1:end] if item["type"] == "call" and timeline.is_edit_call(item)]


def first_edit(items, after=0):
    return timeline.first_edit(items, after)


def approvals(exchanges, outcome=None):
    return [item for item in exchanges if item.get("approval") is not None and (outcome is None or item["approval"] is outcome)]


def has_text(items, pattern, start=0, end=None):
    expression = re.compile(pattern)
    return any(expression.search(item["text"]) for item in items[start:end] if item["type"] == "text")


def no_question(ctx):
    """No question of any kind reached the scripted user, and the question tool was never called."""
    count = question_count(ctx)
    return count == 0 and not asked_with_tool(ctx), f"{count} exchange(s); question tool used: {asked_with_tool(ctx)}", {"exchanges": count}


def question_before_edit(ctx, decision):
    exchanges, items = conversation(ctx)
    held = about(exchanges, decision)
    if not held:
        return False, f"no question matched {decision}", {}
    position, edit = where(items, held[0]), first_edit(items)
    return edit is None or (position is not None and position < edit), f"question at {position}, first edit at {edit}", {}


def second_question_after_quiet_gap(ctx, decision):
    """A second question about the decision, and no edit between the first and the second."""
    exchanges, items = conversation(ctx)
    held = about(exchanges, decision)
    if len(held) < 2:
        return False, f"{len(held)} question(s) matched {decision}, need 2", {}
    first, second = where(items, held[0]), where(items, held[1])
    edits = edits_between(items, first, second)
    return not edits, f"{len(edits)} edit(s) between the first answer and the second question", {}
