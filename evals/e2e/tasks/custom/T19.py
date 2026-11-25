"""Custom checks for T19: the restart fact stays, the sentence nobody acts on goes, and the page fits its budget."""

from __future__ import annotations

import re
import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "text_review_shared.py"
    module = types.ModuleType("text_review_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


OUT = "out/wiki-page.txt"
BUDGET = 1500
API = re.compile(r"(?<![A-Za-z0-9_-])demo-api(?![A-Za-z0-9_-])")
RESTART = re.compile(r"재\s*(?:시작|기동|구동)|다시\s*(?:시작|기동|구동|실행|켜|띄우)|\bre[- ]?(?:start|launch)\b", re.I)
FLAG = re.compile(r"demo-flag|플래그|\bflag\b", re.I)
DOES_NOT_READ = re.compile(
    r"(?:읽|참조|조회|확인|보|받)(?:하)?지\s*(?:않|못)|(?:안|못)\s*(?:읽|참조|조회|확인|보|받)|"
    r"(?:does not|doesn.t|never)\s*(?:directly\s+)?(?:read|consult|check|use)|"
    r"(?:외면|무시)|\bignor(?:e|es|ing)\b",
    re.I,
)
STARTUP_CONFIG_ONLY = re.compile(
    r"(?:설정\s*파일|config(?:uration)?\s*file).{0,24}(?:만|only)|"
    r"(?:만|only).{0,24}(?:설정\s*파일|config(?:uration)?\s*file)",
    re.I,
)


def restart_fact_kept(ctx):
    text = shared(ctx).text_of(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    kept = any(API.search(sentence) and RESTART.search(sentence) for sentence in re.split(r"[\n.!?]", text))
    return kept, "restart fact kept" if kept else "the demo-api restart fact is missing", {}


def unneeded_sentence_removed(ctx):
    text = shared(ctx).text_of(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    kept = any(
        API.search(line) and ((FLAG.search(line) and DOES_NOT_READ.search(line)) or STARTUP_CONFIG_ONLY.search(line))
        for line in text.splitlines()
    )
    return not kept, "the does-not-read sentence is still there" if kept else "the sentence is gone", {}


def within_budget(ctx):
    text = shared(ctx).text_of(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    length = len(text.strip())
    return length <= BUDGET, f"{length} characters, budget {BUDGET}", {"length": length}


def text_review_clean(ctx):
    helper = shared(ctx)
    return helper.review(ctx, "shared-document", helper.existing(ctx, OUT), rules="docs/writing-rules.md",
                         sources=("notes/wiki-draft.txt",), budget=BUDGET)


def ran_text_review(ctx):
    return shared(ctx).ran_text_review(ctx)
