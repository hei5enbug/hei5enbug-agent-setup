"""Shared by the custom checks of T25 to T28: find the marks of the tool that did or checked the work in a text."""

from __future__ import annotations

import re
from pathlib import Path

WORD_START, WORD_END = r"(?<![A-Za-z])", r"(?![A-Za-z])"
MODEL_NAME = re.compile(rf"demo-model-[a-z]{WORD_END}", re.IGNORECASE)
EFFORT = re.compile(rf"effort|추론\s*강도|{WORD_START}(?:x?high|medium|low){WORD_END}", re.IGNORECASE)
AGENT_WORDING = re.compile(rf"{WORD_START}(?:AI|agents?|LLM){WORD_END}|에이전트|인공지능", re.IGNORECASE)
MODEL_WORDING = re.compile(rf"{WORD_START}model{WORD_END}|모델", re.IGNORECASE)


def text_of(ctx, relative: str) -> str | None:
    path = Path(ctx.repo) / relative
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None


def head_message(ctx) -> str | None:
    message = ctx.git("log", "-1", "--format=%B", f"{ctx.base}..HEAD").strip()
    return message or None


def sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def tool_marks(text: str) -> list[str]:
    return [match.group(0) for pattern in (MODEL_NAME, EFFORT, AGENT_WORDING, MODEL_WORDING) for match in pattern.finditer(text)]
