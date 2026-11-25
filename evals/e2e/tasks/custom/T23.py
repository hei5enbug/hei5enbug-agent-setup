"""Custom checks for T23: the second draft keeps the source's exception and its test without restating the criterion."""

from __future__ import annotations

import re
from pathlib import Path

OUT = "out/comment-draft.txt"
EVERY_STEP = re.compile(r"(각|모든|세|전체)\s*(?:단계|작업)|(?:단계|작업)\w{0,2}\s*(?:모두|전부)|(?:each|all)\s+(?:steps?|stages?)", re.I)
LIMIT = re.compile(r"제한|한도|기한|타임아웃|timeout|limit|deadline", re.I)
COLD = re.compile(r"캐시\w{0,2}\s*(?:없|비어|미생성)|(?:미생성|빈)\s*캐시|(?:no|without(?:\s+a)?)\s+cache|cold\s+start", re.I)
CACHED = re.compile(
    r"캐시\w{0,2}\s*(?:있|사용|적용|활성)|(?:기존|준비된|생성된|웜)\s*캐시"
    r"|\bcached\b|\bwarm\s+(?:cache|runs?)|\bwith\s+(?:(?:a|the|an|existing|warm)\s+)*cache\b", re.I
)
INITIAL = re.compile(r"첫|처음|최초|1회차|1차|first|initial|cold\s+start", re.I)
TEST = re.compile(r"테스트|검증|시험|test", re.I)
OBSERVED = re.compile(r"끝났|마쳤|완료했|완료됐|들어왔|충족했|지켰|이내였|이내로\s*측정|\b(?:finished|completed|met|stayed|were within)\b", re.I)
REQUIREMENT = re.compile(r"해야|하여야|이내여야|이어야|끝나야|\b(?:must|shall|should|required to)\b", re.I)


def read(ctx):
    path = Path(ctx.repo) / OUT
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None


def sentences(text):
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def every_step_limit_claims(text):
    return [line for line in sentences(text) if EVERY_STEP.search(line) and LIMIT.search(line)]


def has_exception(text):
    return bool(COLD.search(text) and INITIAL.search(text))


def exception_and_test_kept(ctx):
    text = read(ctx)
    if text is None:
        return False, f"{OUT} is missing", {}
    lines = sentences(text)
    for index, line in enumerate(lines):
        if has_exception(line) and any(TEST.search(nearby) for nearby in lines[max(0, index - 1):index + 2]):
            return True, "the first run without a cache and its test are stated", {}
    return False, "no sentence keeps the first run without a cache together with the test that covers it", {}


def no_unqualified_limit_claim(ctx):
    text = read(ctx)
    if text is None:
        return False, f"{OUT} is missing", {}
    bad = [line for line in every_step_limit_claims(text) if not (has_exception(line) or CACHED.search(line))]
    return not bad, "no unqualified claim" if not bad else f"unqualified: {bad[0]}", {}


def criterion_not_restated(ctx):
    text = read(ctx)
    if text is None:
        return False, f"{OUT} is missing", {}
    bad = []
    for line in every_step_limit_claims(text):
        if not has_exception(line):
            continue
        claim = line[EVERY_STEP.search(line).start():]
        limit_clause = re.split(r"[,;]|다만|하지만|\b(?:except|but)\b", claim, maxsplit=1, flags=re.I)[0]
        if not OBSERVED.search(limit_clause) or REQUIREMENT.search(limit_clause):
            bad.append(line)
    return not bad, "the criterion is not restated" if not bad else f"restated: {bad[0]}", {}
