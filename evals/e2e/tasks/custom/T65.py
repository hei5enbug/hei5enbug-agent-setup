"""Custom checks for T65: a ticket comment names the stages it covers by title, and keeps its limits as numbers."""

from __future__ import annotations

import re
import types
from pathlib import Path

OUT = "out/ticket-comment.txt"
TITLES = {
    0: re.compile(r"(?:\b(?:check|verify|inspect)\w*[\s/&-]+(?:and\s+)?build\w*\b|(?:점검|확인|검사)[^,.;\n]{0,18}빌드)"),
    1: re.compile(r"(?:\badd\w*(?:\s+\w+){0,2}\s+columns?\b|(?:컬럼|열)\s*추가)"),
    2: re.compile(r"(?:\bload\w*(?:\s+\w+){0,2}\s+data\b|데이터\s*(?:적재|복사|로드))"),
    3: re.compile(r"(?:\bcompar(?:e|ing|ison)\b|비교)"),
    4: re.compile(r"(?:\b(?:enable|switch|activate)\s+(?:on\s+)?reads?\b|(?:읽기|조회)\s*(?:전환|활성화|허용))"),
    5: re.compile(r"(?:\b(?:enable|switch|activate)\s+(?:on\s+)?writes?\b|(?:쓰기|기록)\s*(?:전환|활성화|허용))"),
    6: re.compile(r"(?:\b(?:watch|monitor)(?:ing)?\b|관찰|모니터링|감시)"),
    7: re.compile(r"(?:\b(?:remove|delete|drop)\s+(?:the\s+)?(?:old|legacy)\s+path\b|(?:기존|이전|옛)\s*(?:경로|방식)\s*(?:제거|삭제))"),
    8: re.compile(r"(?:\bconfirm(?:ation)?\b|(?:최종\s*)?확인)"),
}
COVERED = (0, 3, 4, 5, 6, 7, 8)
DEPTH = re.compile(r"(?:depth|nest\w*|중첩|깊이)[^.;\n]{0,36}(?<![\d.])2(?![\d.])|\b2[-\s]+levels?\b", re.IGNORECASE)
COUNT = re.compile(r"(?:items?|항목)[^.;\n]{0,24}(?<![\d.])3(?![\d.])|(?<![\d.])3\s*(?:items?\b|개)", re.IGNORECASE)


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "stage_names_shared.py"
    module = types.ModuleType("stage_names_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def stages_named_in_order(ctx):
    helper = shared(ctx)
    text = helper.read(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    missing = [number for number in COVERED if not helper.has_title(text, TITLES[number])]
    extra = [number for number in (1, 2) if helper.has_title(text, TITLES[number])]
    cursor, misplaced = -1, []
    for number in COVERED:
        after = [at for at in helper.title_positions(text, TITLES[number]) if at > cursor]
        if after:
            cursor = after[0]
        elif number not in missing:
            misplaced.append(number)
    problems = {"missing": missing, "not covered but named": extra, "out of order": misplaced}
    problems = {name: value for name, value in problems.items() if value}
    return not problems, "stages 0 and 3 to 8 are named in order" if not problems else str(problems), {}


def no_stage_by_number_alone(ctx):
    helper = shared(ctx)
    text = helper.read(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    quantities = [match.span() for pattern in (DEPTH, COUNT) for match in pattern.finditer(text)]
    numbers = [
        match for match in helper.NUMBER.finditer(text)
        if int(match.group()) in TITLES
        and not any(start <= match.start() and match.end() <= end for start, end in quantities)
        and not helper.is_quantity(text, match)
    ]
    alone = [
        match.group() for match in numbers
        if not helper.beside_title(text, match, TITLES[int(match.group())])
    ]
    return not alone, "no stage is named by its number alone" if not alone else f"number without its title: {alone}", {}


def limits_kept(ctx):
    text = shared(ctx).read(ctx, OUT)
    if text is None:
        return False, f"{OUT} is missing", {}
    missing = [name for name, pattern in (("depth of 2 levels", DEPTH), ("3 items", COUNT)) if not pattern.search(text)]
    return not missing, "both limits keep their numbers" if not missing else f"limit lost or changed: {missing}", {}
