"""Shared by the custom checks of T29 and T30: read the first `text_review.py review` run of the agent.

A run counts when its Bash result holds the review's JSON line. `stage` is "check" when the text check stopped the
review before the reviewer ran, and "review" when the reviewer answered.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

RAN_REVIEW = re.compile(r"text_review\.py[\"']?\s+review\b")


def read(ctx, relative):
    path = Path(ctx.repo) / relative
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None


def payloads(result_text):
    found = []
    for line in str(result_text).splitlines():
        start = line.find("{")
        if start < 0:
            continue
        try:
            value = json.loads(line[start:])
        except ValueError:
            continue
        if isinstance(value, dict) and "stage" in value:
            found.append(value)
    return found


def first_review(ctx):
    """The JSON payload of the agent's first review run, or a reason why there is none."""
    for call in ctx.view.get("tool_calls", []):
        if call.get("name") != "Bash" or not RAN_REVIEW.search(str(call.get("input", {}).get("command", ""))):
            continue
        found = payloads(call.get("result_text", ""))
        if not found:
            return None, "the first review run printed no result line"
        return found[-1], ""
    return None, "text_review.py review was never run"


def reached_reviewer(payload, kind):
    if payload["stage"] != "review":
        return f"the review stopped at the {payload['stage']} stage"
    if payload.get("kind") != kind:
        return f"the first review used kind {payload.get('kind')}, not {kind}"
    return ""


def quoting(payload, names, finding_type):
    return [item for item in payload.get("findings", []) if isinstance(item, dict)
            and item.get("type") == finding_type and any(name in str(item.get("quote", "")) for name in names)]
