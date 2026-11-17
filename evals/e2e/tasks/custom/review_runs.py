"""Shared by the custom checks of T32 and T33: read the result of the review the agent ran on a seeded draft."""

from __future__ import annotations

import json
import re

REVIEW_COMMAND = re.compile(r"text_review\.py[\"']?\s+review\b")


def result_of(text: str) -> dict | None:
    for line in reversed(text.splitlines()):
        start = line.find('{"stage"')
        if start < 0:
            continue
        try:
            payload = json.loads(line[start:])
        except ValueError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def reached_reviewer(payload: dict) -> bool:
    return payload.get("stage") == "review" and "error" not in payload and isinstance(payload.get("findings"), list)


def first_review(ctx, draft_name: str) -> tuple[dict | None, str]:
    """The first review of the seeded draft that reached the reviewer, or None with the reason it did not."""
    stages = []
    for call in ctx.view.get("tool_calls", []):
        command = str(call.get("input", {}).get("command", ""))
        if call.get("name") != "Bash" or not REVIEW_COMMAND.search(command) or draft_name not in command:
            continue
        payload = result_of(str(call.get("result_text", "")))
        if payload is not None and reached_reviewer(payload):
            return payload, "reached the reviewer"
        stages.append(str(payload.get("stage")) if payload else "no result")
    return None, f"no review of {draft_name} reached the reviewer; runs ended at: {stages}" if stages else \
        f"text_review.py review was never run on {draft_name}"


def removable_quoting(payload: dict, names: tuple[str, ...]) -> list[dict]:
    return [item for item in payload["findings"] if isinstance(item, dict) and item.get("type") == "removable"
            and any(name in str(item.get("quote", "")) for name in names)]
