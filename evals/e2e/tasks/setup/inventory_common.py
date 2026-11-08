"""Shared helpers of the inventory-service setup scripts: file writing, a commit, and the team's writing rules."""

from __future__ import annotations

import subprocess
from pathlib import Path

WRITING_RULES = """# Writing rules

Each text follows the rules of the place it is posted to. Posted texts are read as they are, so they hold only
what the reader needs to decide or act.

## Pull request description

- Say what changes in behavior and what a reviewer should check. Leave out what the diff already shows: lists of
  new files, columns, tables, or functions, and the order of calls that the code makes.
- Do not put a ticket key in the body. The branch name carries it.
- Give only the latest result of each check, not one line per commit.

## Review reply

- Answer the question that was asked, with the reason, in the first sentence.
- Do not restate the comment or the code.
"""

WRITING_RULES_KO = """# 작성 규칙

> 영어 원본: [docs/writing-rules.md](../../../docs/writing-rules.md). 이 문서는 번역본이며 원본보다 우선하지 않습니다.

글마다 올리는 곳의 규칙을 따릅니다. 올린 글은 그대로 읽히므로, 독자가 판단하거나 행동하는 데 필요한 내용만 담습니다.

## 풀 리퀘스트 설명

- 동작이 무엇이 바뀌는지와 리뷰어가 무엇을 확인해야 하는지를 적습니다. diff가 이미 보여 주는 내용은 뺍니다. 새 파일,
  컬럼, 테이블, 함수의 목록과 코드가 하는 호출 순서가 그렇습니다.
- 본문에 티켓 키를 적지 않습니다. 브랜치 이름이 티켓 키를 담습니다.
- 검사마다 가장 최근 결과만 적고, 커밋마다 한 줄씩 적지 않습니다.

## 리뷰 답글

- 물어본 내용에 대한 답을 이유와 함께 첫 문장에 적습니다.
- 코멘트나 코드를 다시 풀어 쓰지 않습니다.
"""


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def commit(root: Path, message: str) -> None:
    for command in (["git", "add", "-A"], ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
                                            "commit", "-q", "-m", message]):
        subprocess.run(command, cwd=root, check=True, capture_output=True)


def add_writing_rules(root: Path) -> None:
    write(root, "docs/writing-rules.md", WRITING_RULES)
    write(root, "docs/ko/docs/writing-rules.ko.md", WRITING_RULES_KO)
    commit(root, "docs: add the writing rules")
