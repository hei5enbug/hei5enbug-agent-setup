#!/usr/bin/env python3
"""미결 질문 Markdown 파일의 기계적인 형식 제한을 검사한다."""

from __future__ import annotations

import re
import sys
from pathlib import Path


MAX_LINE_CHARS = 200
MAX_ISSUE_LINES = 100
ISSUE_PATTERN = re.compile(r"^##\s+\d+\.\s+\S")
CHOICE_PATTERN = re.compile(r"^\s*(\d+)\.\s+\*\*.+\*\*\s*$")
QUESTION_HEADING = "### 질문"
CHOICES_HEADING = "### 선택지"
ANSWER_HEADING = "### 답변"
EMPTY_ANSWER_BLOCK = ["```", "", "```"]


def read_text(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    return Path(source).read_text(encoding="utf-8")


def nonempty(lines: list[str]) -> list[str]:
    return [line for line in lines if line.strip()]


def trim_blank_lines(lines: list[str]) -> list[str]:
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def validate(source: str) -> list[str]:
    lines = read_text(source).splitlines()
    errors: list[str] = []

    for number, line in enumerate(lines, start=1):
        if len(line) > MAX_LINE_CHARS:
            errors.append(
                f"{number}번째 줄이 {len(line)}자로 {MAX_LINE_CHARS}자를 넘습니다."
            )

    starts = [index for index, line in enumerate(lines) if ISSUE_PATTERN.match(line)]
    if not starts:
        errors.append("'## 번호. 문제 제목' 형식의 미결 문제가 없습니다.")
        return errors

    for issue_number, start in enumerate(starts, start=1):
        end = starts[issue_number] if issue_number < len(starts) else len(lines)
        section = lines[start:end]
        if len(section) > MAX_ISSUE_LINES:
            errors.append(
                f"{issue_number}번 문제가 {len(section)}줄로 "
                f"{MAX_ISSUE_LINES}줄을 넘습니다."
            )

        positions: dict[str, int] = {}
        for heading in (QUESTION_HEADING, CHOICES_HEADING, ANSWER_HEADING):
            matches = [index for index, line in enumerate(section) if line == heading]
            if len(matches) != 1:
                errors.append(
                    f"{issue_number}번 문제에는 '{heading}'이 정확히 한 번 있어야 합니다."
                )
            else:
                positions[heading] = matches[0]

        if len(positions) != 3:
            continue

        question_at = positions[QUESTION_HEADING]
        choices_at = positions[CHOICES_HEADING]
        answer_at = positions[ANSWER_HEADING]
        if not question_at < choices_at < answer_at:
            errors.append(
                f"{issue_number}번 문제의 질문, 선택지, 답변 순서가 올바르지 않습니다."
            )
            continue

        if not nonempty(section[question_at + 1 : choices_at]):
            errors.append(f"{issue_number}번 문제의 질문 설명이 비어 있습니다.")

        choice_block = section[choices_at + 1 : answer_at]
        choice_matches = [
            (index, match)
            for index, line in enumerate(choice_block)
            if (match := CHOICE_PATTERN.match(line))
        ]
        choice_starts = [index for index, _ in choice_matches]
        choice_numbers = [int(match.group(1)) for _, match in choice_matches]
        if not 2 <= len(choice_starts) <= 5:
            errors.append(
                f"{issue_number}번 문제의 선택지는 2개에서 5개까지 있어야 합니다."
            )
        else:
            expected_numbers = list(range(1, len(choice_numbers) + 1))
            if choice_numbers != expected_numbers:
                errors.append(
                    f"{issue_number}번 문제의 선택지는 1번부터 순서대로 번호를 붙여야 합니다."
                )
            for choice_number, choice_start in enumerate(choice_starts, start=1):
                choice_end = (
                    choice_starts[choice_number]
                    if choice_number < len(choice_starts)
                    else len(choice_block)
                )
                if not nonempty(choice_block[choice_start + 1 : choice_end]):
                    errors.append(
                        f"{issue_number}번 문제의 {choice_number}번 선택지 설명이 비어 있습니다."
                    )

        answer_body = trim_blank_lines(section[answer_at + 1 :])
        if answer_body != EMPTY_ANSWER_BLOCK:
            errors.append(
                f"{issue_number}번 문제의 답변 칸은 언어 이름과 내용이 없는 "
                "여러 줄 코드 블록이어야 합니다."
            )

    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("사용법: validate_questions.py <질문 파일 또는 ->", file=sys.stderr)
        return 2

    try:
        errors = validate(sys.argv[1])
    except (OSError, UnicodeError) as error:
        print(f"파일을 읽을 수 없습니다: {error}", file=sys.stderr)
        return 2

    if errors:
        for error in errors:
            print(f"오류: {error}", file=sys.stderr)
        return 1

    print("질문 파일 검사를 통과했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
