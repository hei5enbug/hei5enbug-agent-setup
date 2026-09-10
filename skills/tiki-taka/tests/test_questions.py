#!/usr/bin/env python3
"""미결 질문 파일 검사기의 기계적 규칙과 코드 울타리 처리를 검사한다."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_questions.py"

VALID_ISSUE = textwrap.dedent(
    """
    ## 1. 재시도 횟수를 어떻게 정할까

    ### 질문

    실패한 요청을 몇 번까지 다시 보낼지 정해야 합니다.

    ### 선택지

    1. **세 번까지 재시도**
       대부분의 일시적 오류를 넘길 수 있고 지연이 크지 않습니다.

    2. **재시도하지 않음**
       구현이 단순하지만 일시적 오류에 그대로 실패합니다.

    ### 답변

    ```

    ```
    """
).lstrip()

FENCED_ISSUE = textwrap.dedent(
    """
    ## 1. 설정 파일 형식

    ### 질문

    아래 예시처럼 설정을 적을지 정해야 합니다.

    ```yaml
    ## 2. 이 줄은 예시일 뿐이다
    ### 질문
    1. **가짜 선택지**
    ```

    ### 선택지

    1. **YAML 유지**
       기존 도구와 맞고 읽기 쉽습니다.

    2. **JSON으로 변경**
       검증기가 많지만 주석을 쓸 수 없습니다.

    ### 답변

    ```

    ```
    """
).lstrip()


class ValidateQuestionsTest(unittest.TestCase):
    def run_validator(self, content: str) -> subprocess.CompletedProcess[str]:
        with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8", delete=False) as handle:
            handle.write(content)
            path = handle.name
        try:
            return subprocess.run(
                [sys.executable, str(SCRIPT), path],
                text=True,
                capture_output=True,
                check=False,
            )
        finally:
            Path(path).unlink(missing_ok=True)

    def test_valid_file_passes(self) -> None:
        result = self.run_validator(VALID_ISSUE)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_headings_inside_code_fence_are_ignored(self) -> None:
        result = self.run_validator(FENCED_ISSUE)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_two_real_issues_are_both_checked(self) -> None:
        second = VALID_ISSUE.replace("## 1. 재시도 횟수를 어떻게 정할까", "## 2. 두 번째 문제")
        broken_second = second.replace("### 선택지\n", "")
        result = self.run_validator(VALID_ISSUE + "\n" + broken_second)
        self.assertEqual(result.returncode, 1)
        self.assertIn("2번 문제", result.stderr)

    def test_missing_issue_heading_fails(self) -> None:
        result = self.run_validator("# 제목만\n\n내용\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("미결 문제가 없습니다", result.stderr)

    def test_non_empty_answer_block_fails(self) -> None:
        result = self.run_validator(VALID_ISSUE.replace("```\n\n```", "```\n답\n```"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("답변 칸", result.stderr)

    def test_long_line_fails(self) -> None:
        result = self.run_validator(VALID_ISSUE.replace("지연이 크지 않습니다.", "가" * 210))
        self.assertEqual(result.returncode, 1)
        self.assertIn("200자를 넘습니다", result.stderr)


if __name__ == "__main__":
    unittest.main()
