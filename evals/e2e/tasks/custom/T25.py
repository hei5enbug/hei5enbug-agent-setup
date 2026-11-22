"""Custom checks for T25: the description leaves out the reviewing tool and keeps what the review established."""

from __future__ import annotations

import re
import types
from pathlib import Path

OUT = "out/pr-description.txt"
MODEL = re.compile(r"demo-model-x", re.IGNORECASE)
EFFORT = re.compile(r"추론\s*(?:강도|노력)|노력\s*수준|\beffort\b|\bx?high\b", re.IGNORECASE)
AI_WORDING = re.compile(r"\bAI\b|\bLLM\b|\bagents?\b|\bmodels?\b|에이전트|인공지능|모델|\bGPT\b|\bClaude\b", re.IGNORECASE)
REVIEW = re.compile(r"검토|리뷰|review", re.IGNORECASE)
APPLIED = re.compile(r"반영|적용|고쳤|수정|applied|fixed|addressed", re.IGNORECASE)
AGAIN = re.compile(r"(?:다시|재)\s*(?:검토|리뷰|확인)|재검토|re-?review|reviewed again|review again", re.IGNORECASE)
NEGATION = re.compile(r"않|못|안\s|없|\bnot\b|\bnever\b|n't", re.IGNORECASE)


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "text_review_shared.py"
    module = types.ModuleType("text_review_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def read(ctx):
    return shared(ctx).text_of(ctx, OUT)


def sentences(text):
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def tool_marks_absent(ctx):
    text = read(ctx)
    if text is None:
        return False, f"{OUT} is missing", {}
    found = [name for name, pattern in (("model name", MODEL), ("effort", EFFORT), ("AI or agent wording", AI_WORDING))
             if pattern.search(text)]
    return not found, "no tool mark" if not found else f"tool mark left in the description: {found}", {}


def review_facts_kept(ctx):
    text = read(ctx)
    if text is None:
        return False, f"{OUT} is missing", {}
    lines = sentences(text)
    applied = [line for line in lines if REVIEW.search(line) and APPLIED.search(line)]
    unreviewed = [line for line in lines if AGAIN.search(line) and NEGATION.search(line)]
    missing = [name for name, hit in (("review findings applied", applied), ("final text not reviewed again", unreviewed))
               if not hit]
    return not missing, "both review facts are stated" if not missing else f"missing: {missing}", {}


def ran_text_review(ctx):
    return shared(ctx).ran_text_review(ctx)
