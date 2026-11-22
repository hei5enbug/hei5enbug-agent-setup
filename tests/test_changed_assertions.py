"""Tests for scripts/changed_assertions.py on seeded repositories."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "changed_assertions.py"
ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "Demo Dev",
       "GIT_AUTHOR_EMAIL": "dev@example.com", "GIT_COMMITTER_NAME": "Demo Dev", "GIT_COMMITTER_EMAIL": "dev@example.com"}

BASE_TESTS = """import pytest

from shop import total


def test_total_adds_items():
    assert total([1, 2]) == 3
    assert total([]) == 0


def test_total_rejects_negative():
    with pytest.raises(ValueError):
        total([-1])


def test_total_rounds():
    assert total([0.5, 0.5]) == 1
"""


class ChangedAssertionsTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repo = Path(directory.name)
        self.git("init", "-q", "-b", "main")
        (self.repo / "tests").mkdir()
        self.write("tests/test_shop.py", BASE_TESTS)
        self.write("shop.py", "def total(items):\n    return sum(items)\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.repo, env=ENV, check=True, capture_output=True, text=True).stdout

    def write(self, relative: str, text: str) -> None:
        (self.repo / relative).write_text(text, encoding="utf-8")

    def run_script(self, base: str = "HEAD", cwd: Path | None = None) -> list[dict]:
        done = subprocess.run([sys.executable, str(SCRIPT), base], cwd=cwd or self.repo, env=ENV, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def edit(self, old: str, new: str) -> None:
        text = (self.repo / "tests/test_shop.py").read_text(encoding="utf-8")
        self.assertEqual(text.count(old), 1)
        self.write("tests/test_shop.py", text.replace(old, new))

    def test_변경이_없으면_빈_목록을_출력한다(self):
        """테스트 파일이 그대로이고 소스만 바뀌어도 목록은 비어 있다."""
        # given
        self.write("shop.py", "def total(items):\n    return sum(items) + 0\n")

        # when / then
        self.assertEqual(self.run_script(), [])

    def test_지운_단언은_파일과_기준_리비전의_줄로_나온다(self):
        """`assert total([]) == 0`을 지우면 기준 리비전 8번 줄로 removed_assertions에 오른다."""
        # given
        self.edit("    assert total([]) == 0\n", "")

        # when
        report = self.run_script()

        # then
        self.assertEqual(report, [{"file": "tests/test_shop.py", "removed_assertions": [{"line": 8, "text": "assert total([]) == 0"}],
                                   "changed_assertions": [], "added_skip_markers": [], "removed_tests": []}])

    def test_바뀐_기대값은_전후_줄과_함께_changed로_나온다(self):
        """`== 3`을 `== 4`로 바꾸면 이전 줄과 이후 줄이 함께 나오고 removed에는 없다."""
        # given
        self.edit("assert total([1, 2]) == 3", "assert total([1, 2]) == 4")

        # when
        entry = self.run_script()[0]

        # then
        self.assertEqual(entry["changed_assertions"], [{"line": 7, "before": "assert total([1, 2]) == 3",
                                                        "after": "assert total([1, 2]) == 4", "after_line": 7}])
        self.assertEqual(entry["removed_assertions"], [])

    def test_추가한_skip_표식은_작업_트리의_줄로_나온다(self):
        """`@pytest.mark.skip`을 더하면 added_skip_markers에 새 줄 번호로 오른다."""
        # given
        self.edit("def test_total_rounds", "@pytest.mark.skip\ndef test_total_rounds")

        # when
        entry = self.run_script()[0]

        # then
        self.assertEqual(entry["added_skip_markers"], [{"line": 16, "text": "@pytest.mark.skip"}])

    def test_지운_테스트_함수는_이름과_기준_줄로_나온다(self):
        """`test_total_rounds`를 통째로 지우면 removed_tests에 오르고, 그 단언도 removed_assertions에 오른다."""
        # given
        self.edit("\n\ndef test_total_rounds():\n    assert total([0.5, 0.5]) == 1\n", "\n")

        # when
        entry = self.run_script()[0]

        # then
        self.assertEqual(entry["removed_tests"], [{"line": 16, "name": "test_total_rounds"}])
        self.assertEqual([item["text"] for item in entry["removed_assertions"]], ["assert total([0.5, 0.5]) == 1"])

    def test_새_테스트_파일과_더한_단언은_목록에_오르지_않는다(self):
        """기준 리비전에 없던 파일과 기존 파일에 더한 단언과 테스트는 빈 목록이다."""
        # given
        self.write("tests/test_new.py", "def test_new():\n    assert 1 == 1\n")
        with (self.repo / "tests/test_shop.py").open("a", encoding="utf-8") as handle:
            handle.write("\n\ndef test_extra():\n    assert total([2]) == 2\n")

        # when / then
        self.assertEqual(self.run_script(), [])

    def test_옮기거나_들여쓰기만_바꾼_단언은_목록에_오르지_않는다(self):
        """같은 단언이 다른 위치로 가거나 들여쓰기만 달라지면 나오지 않는다."""
        # given
        self.edit("    assert total([]) == 0\n", "")
        self.edit("    assert total([0.5, 0.5]) == 1\n", "    assert total([0.5, 0.5]) == 1\n        assert total([]) == 0\n")

        # when / then
        self.assertEqual(self.run_script(), [])

    def test_삭제한_테스트_파일은_모든_단언과_테스트를_보인다(self):
        """기준에 있던 테스트 파일을 지우면 그 안의 단언 넷과 테스트 셋이 나온다."""
        # given
        (self.repo / "tests/test_shop.py").unlink()

        # when
        entry = self.run_script()[0]

        # then
        self.assertEqual(len(entry["removed_assertions"]), 4)
        self.assertEqual([item["name"] for item in entry["removed_tests"]],
                         ["test_total_adds_items", "test_total_rejects_negative", "test_total_rounds"])

    def test_소스_파일의_변경과_다른_언어의_테스트_파일도_구분한다(self):
        """소스 파일은 무시하고 `*.test.ts`의 `expect` 줄은 목록에 올린다. 하위 폴더에서 실행해도 같다."""
        # given
        self.write("shop.test.ts", "it('adds', () => {\n  expect(total([1])).toBe(1);\n});\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "ts")
        self.write("shop.test.ts", "it('adds', () => {\n});\n")
        self.write("shop.py", "x = 1\n")

        # when
        report = self.run_script("HEAD", cwd=self.repo / "tests")

        # then
        self.assertEqual([entry["file"] for entry in report], ["shop.test.ts"])
        self.assertEqual(report[0]["removed_assertions"], [{"line": 2, "text": "expect(total([1])).toBe(1);"}])

    def test_알_수_없는_리비전이면_오류로_끝난다(self):
        """기준 리비전이 없으면 비어 있지 않은 종료 코드와 stderr 이유를 낸다."""
        # when
        done = subprocess.run([sys.executable, str(SCRIPT), "no-such-revision"], cwd=self.repo, env=ENV, capture_output=True, text=True)

        # then
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("changed_assertions: git", done.stderr)


if __name__ == "__main__":
    unittest.main()
