"""Shared helpers for the stored question input tasks: what the run read, what it said, and the question it asked."""

from __future__ import annotations

import json
import re

TRANSCRIPT = "demo-session.jsonl"
ESCAPE_SEQUENCE = re.compile(r"\\u[0-9a-fA-F]{4}")
NEGATION = re.compile(r"않|없|아니|never|\bno\b|\bnot\b|n't|말[고라자]|지 마")


def read_transcript(view) -> bool:
    """Whether a main-session tool call other than a write named the transcript file before the run ended."""
    return any(TRANSCRIPT in json.dumps(call.get("input"), ensure_ascii=False) for call in view.get("tool_calls", [])
               if call.get("source", "main") == "main" and call.get("name") not in ("Write", "Edit"))


def said(view) -> list[str]:
    """Every line the main session wrote to the user: each assistant text and the final answer."""
    texts = [*view.get("assistant_texts", []), view.get("final_answer", "")]
    return [line for text in texts for line in str(text).splitlines() if line.strip()]


def affirmed(view, pattern: str) -> list[str]:
    """The lines that match `pattern` and carry no negation, so a line that denies the statement does not count."""
    return [line for line in said(view) if re.search(pattern, line) and not NEGATION.search(line)]
