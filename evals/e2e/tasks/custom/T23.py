"""Custom checks for T23: the second draft keeps the source's exception and its test without restating the criterion."""

from __future__ import annotations

import re
from pathlib import Path

OUT = "out/comment-draft.txt"
EVERY_STEP = re.compile(r"(각|모든|세|전체)\s*단계|단계\w{0,2}\s*모두")
EXCEPTION = re.compile(r"첫 실행|캐시 없|예외")
TEST = re.compile(r"테스트|test_cold_start")


def read(ctx):
    path = Path(ctx.repo) / OUT
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None


def sentences(text):
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def every_step_limit_claims(text):
    return [line for line in sentences(text) if EVERY_STEP.search(line) and "제한" in line]


def exception_and_test_kept(ctx):
    text = read(ctx)
    if text is None:
        return False, f"{OUT} is missing", {}
    lines = sentences(text)
    for index, line in enumerate(lines):
        if "첫 실행" in line and "캐시" in line and (TEST.search(line) or any(TEST.search(n) for n in lines[index + 1:index + 2])):
            return True, "the first run without a cache and its test are stated", {}
    return False, "no sentence keeps the first run without a cache together with the test that covers it", {}


def no_unqualified_limit_claim(ctx):
    text = read(ctx)
    if text is None:
        return False, f"{OUT} is missing", {}
    bad = [line for line in every_step_limit_claims(text) if not re.search(r"첫 실행|캐시|예외", line)]
    return not bad, "no unqualified claim" if not bad else f"unqualified: {bad[0]}", {}


def criterion_not_restated(ctx):
    text = read(ctx)
    if text is None:
        return False, f"{OUT} is missing", {}
    bad = [line for line in every_step_limit_claims(text) if EXCEPTION.search(line)]
    return not bad, "the criterion is not restated" if not bad else f"restated: {bad[0]}", {}
