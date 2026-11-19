"""Korean-subject history, then a staged src/demo.py change beside an unstaged README.md edit and an untracked .env."""

from __future__ import annotations

import sys
from pathlib import Path

from commit_common import README_WIP, SECRET_LINE, STAGED_DEMO, add_history, git, write

HISTORY = (
    "feat: 인사말 함수 추가",
    "fix: 빈 입력에서 예외가 나던 문제 수정",
    "docs: 사용 예시 설명 보완",
    "test: 인사말 경계 사례 검증 추가",
    "refactor: 문자열 조합 방식 정리",
    "fix: 공백만 있는 이름 처리 보완",
    "chore: 개발 문서 목록 갱신",
    "feat: 이름 기본값 옵션 추가",
)


def main(repo: str) -> None:
    root = Path(repo)
    add_history(root, HISTORY)
    write(root, "src/demo.py", STAGED_DEMO)
    git(root, "add", "--", "src/demo.py")
    readme = root / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + README_WIP, encoding="utf-8")
    write(root, ".env", SECRET_LINE + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
