"""Shared by the custom checks of T29 and T30: read the first `text_review.py review` run of the agent.

A run counts when its Bash result holds the review's JSON line, also inside the `output` field of a wrapper object that
Codex tool results use; a call with `--help` is not a run. `stage` is "check" when the text check stopped the
review before the reviewer ran, and "review" when the reviewer answered.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

RAN_REVIEW = re.compile(r"text_review\.py[\"']?\s+review\b")
HELP_FLAG = re.compile(r"\s(?:--help|-h)(?:\s|$)")


def read(ctx, relative):
    path = Path(ctx.repo) / relative
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None


def collect(value, found):
    """Add every dict with a `stage` found in `value`, reading JSON text held in a string field such as a wrapper's `output`."""
    if isinstance(value, dict):
        if "stage" in value:
            found.append(value)
            return
        for item in value.values():
            collect(item, found)
    elif isinstance(value, str):
        payloads(value, found)


def payloads(result_text, found=None):
    found = [] if found is None else found
    for line in str(result_text).splitlines():
        start = line.find("{")
        if start < 0:
            continue
        try:
            collect(json.loads(line[start:]), found)
        except ValueError:
            continue
    return found


def first_review(ctx):
    """The JSON payload of the agent's first review run, or a reason why there is none."""
    for call in ctx.view.get("tool_calls", []):
        command = str(call.get("input", {}).get("command", ""))
        if call.get("name") != "Bash" or not RAN_REVIEW.search(command) or HELP_FLAG.search(command):
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
