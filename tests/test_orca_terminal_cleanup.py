"""Tell a never-used shell terminal from a used one, for the worktree cleanup run."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import orca_terminal_cleanup  # noqa: E402

PROMPT = "demo % "


class TailShapeTest(unittest.TestCase):
    def test_로그인_안내_줄이_앞에_붙은_출력이나_줄바꿈으로_이은_한_덩어리_글도_프롬프트뿐이면_쓴_적_없는_것으로_본다(self):
        """Orca가 출력을 목록이 아닌 글 하나로 주거나 셸이 `Last login` 줄을 먼저 찍어도 쓴 적 없는 셸이 열린 채 남지 않는다."""
        # Given
        banner = "Last login: Mon Nov 23 09:00:00 on ttys001"

        # When / Then
        self.assertTrue(orca_terminal_cleanup.only_prompts(f"{banner}\n{PROMPT}"))
        self.assertTrue(orca_terminal_cleanup.only_prompts([banner, PROMPT]))
        self.assertFalse(orca_terminal_cleanup.only_prompts([banner]))
        self.assertFalse(orca_terminal_cleanup.only_prompts(f"{banner}\n{PROMPT}ls"))


class PromptShapeTest(unittest.TestCase):
    def test_프롬프트_모양_판정은_입력이_붙은_줄을_거른다(self):
        """% $ # > ❯로 끝나는 빈 입력줄만 프롬프트이고 글자가 붙은 줄, 빈 줄은 아니다."""
        # Given
        lines = {"user@host repo % ": True, "$": True, "~/repo ❯": True, "demo % ls": False, "demo % 5%": False,
                 "": False, "total 4": False}

        # When
        judged = {line: orca_terminal_cleanup.is_bare_prompt(line) for line in lines}

        # Then
        self.assertEqual(judged, lines)


if __name__ == "__main__":
    unittest.main()
