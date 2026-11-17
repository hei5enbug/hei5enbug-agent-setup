"""Tests for the script that lists what a change did to the test files that existed at a base revision."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = REPO_ROOT / "evals/e2e/candidates/95/changed_assertions.py"
INSTALLED = REPO_ROOT / "scripts/changed_assertions.py"
SCRIPT = INSTALLED if INSTALLED.is_file() else CANDIDATE
GIT_ENV = {
    **os.environ, "GIT_AUTHOR_NAME": "Demo Dev", "GIT_AUTHOR_EMAIL": "dev@example.com",
    "GIT_COMMITTER_NAME": "Demo Dev", "GIT_COMMITTER_EMAIL": "dev@example.com", "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}
BASE_TESTS = (
    "import pytest\n"                                       # 1
    "\n"                                                    # 2
    "\n"                                                    # 3
    "def test_total():\n"                                   # 4
    "    assert total(2, 3) == 6\n"                         # 5
    "    assert total(0, 3) == 0\n"                         # 6
    "\n"                                                    # 7
    "\n"                                                    # 8
    "def test_rejects_negative():\n"                        # 9
    "    with pytest.raises(ValueError):\n"                 # 10
    "        total(-1, 3)\n"                                # 11
)


def load_script():
    spec = importlib.util.spec_from_file_location("changed_assertions_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=repo, env=GIT_ENV, check=True,
                          capture_output=True, text=True).stdout


class ChangedAssertionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.repo = Path(self._temp.name)
        self.script = load_script()
        git(self.repo, "init", "-q", "-b", "main")
        self.write({"app.py": "def total(a, b):\n    assert a >= 0\n    return a * b\n", "tests/test_app.py": BASE_TESTS})
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        self.base = git(self.repo, "rev-parse", "HEAD").strip()

    def write(self, files: dict[str, str]) -> None:
        for relative, text in files.items():
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def listed(self) -> list[dict]:
        return self.script.changed_assertions(self.repo, self.base)

    def only_entry(self) -> dict:
        found = self.listed()
        self.assertEqual([item["file"] for item in found], ["tests/test_app.py"])
        return found[0]

    def test_기존_테스트_파일에서_지운_단언은_파일과_기준_줄_번호로_나열된다(self):
        """given 기존 테스트의 단언 한 줄을 지운 작업 트리 when 나열하면 then 그 파일의 removed_assertions에 기준 줄 번호와 본문이 있다."""
        # given
        self.write({"tests/test_app.py": BASE_TESTS.replace("    assert total(0, 3) == 0\n", "")})

        # when
        entry = self.only_entry()

        # then
        self.assertEqual(entry["removed_assertions"], [{"line": 6, "text": "assert total(0, 3) == 0"}])
        self.assertEqual((entry["changed_assertions"], entry["added_skips"], entry["removed_tests"]), ([], [], []))

    def test_바꾼_기대값은_이전과_이후_본문과_줄_번호로_나열된다(self):
        """given 기대값 6을 7로 바꾼 단언 when 나열하면 then changed_assertions에 before와 after와 두 줄 번호가 있고 지운 것으로는 세지 않는다."""
        # given
        self.write({"tests/test_app.py": BASE_TESTS.replace("== 6", "== 7")})

        # when
        entry = self.only_entry()

        # then
        self.assertEqual(entry["changed_assertions"], [
            {"line": 5, "new_line": 5, "before": "assert total(2, 3) == 6", "after": "assert total(2, 3) == 7"}])
        self.assertEqual(entry["removed_assertions"], [])

    def test_여러_줄_단언의_이어지는_줄에서_바꾼_기대값도_나열된다(self):
        """given 괄호가 여러 줄에 걸친 단언의 둘째 줄 값을 바꾼 변경 when 나열하면 then 그 단언이 한 문장으로 바뀐 것으로 나온다."""
        # given
        base = "def test_big():\n    assert total(\n        2, 3\n    ) == 6\n"
        self.write({"tests/test_app.py": base})
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "multi-line")
        self.base = git(self.repo, "rev-parse", "HEAD").strip()
        self.write({"tests/test_app.py": base.replace("2, 3", "2, 4")})

        # when
        entry = self.only_entry()

        # then
        self.assertEqual(len(entry["changed_assertions"]), 1)
        self.assertEqual((entry["changed_assertions"][0]["before"], entry["changed_assertions"][0]["after"]),
                         ("assert total( 2, 3 ) == 6", "assert total( 2, 4 ) == 6"))

    def test_더한_건너뜀_표시는_새_파일의_줄_번호로_나열되고_이미_있던_표시는_나열하지_않는다(self):
        """given 테스트에 skip 데코레이터를 더한 변경 when 나열하면 then added_skips에 그 줄이 있고, 같은 표시가 기준에도 있으면 나열하지 않는다."""
        # given
        self.write({"tests/test_app.py": BASE_TESTS.replace("def test_total():", "@pytest.mark.skip(reason='later')\ndef test_total():")})

        # when
        entry = self.only_entry()

        # then
        self.assertEqual(entry["added_skips"], [{"line": 4, "text": "@pytest.mark.skip(reason='later')"}])
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "skip already there")
        self.base = git(self.repo, "rev-parse", "HEAD").strip()
        self.assertEqual(self.listed(), [])

    def test_지운_테스트_함수는_기준_줄_번호로_나열된다(self):
        """given 테스트 함수 하나를 통째로 지운 변경 when 나열하면 then removed_tests에 이름과 기준 줄이 있고 그 함수의 단언도 지운 것으로 나온다."""
        # given
        self.write({"tests/test_app.py": BASE_TESTS.split("\n\n\ndef test_rejects_negative")[0] + "\n"})

        # when
        entry = self.only_entry()

        # then
        self.assertEqual(entry["removed_tests"], [{"line": 9, "name": "test_rejects_negative"}])
        self.assertEqual([item["text"] for item in entry["removed_assertions"]], ["with pytest.raises(ValueError):"])

    def test_새_테스트_파일과_더한_단언은_나열하지_않고_변경이_없으면_빈_목록을_찍는다(self):
        """given 새 테스트 파일과 기존 파일에 더한 단언 when 나열하면 then 아무것도 나열하지 않고, 변경이 없는 저장소는 CLI가 []를 찍는다."""
        # given
        self.write({"tests/test_new.py": "def test_new():\n    assert 1 == 1\n",
                    "tests/test_app.py": BASE_TESTS + "\n\ndef test_extra():\n    assert total(1, 1) == 1\n"})

        # when
        found = self.listed()
        git(self.repo, "checkout", "-q", "--", "tests/test_app.py")
        (self.repo / "tests/test_new.py").unlink()
        done = subprocess.run([sys.executable, str(SCRIPT), self.base, "--repo", str(self.repo)], capture_output=True, text=True)

        # then
        self.assertEqual(found, [])
        self.assertEqual((done.returncode, json.loads(done.stdout)), (0, []))

    def test_지운_테스트_파일은_모든_단언과_테스트_함수가_지워진_것으로_나열된다(self):
        """given 기존 테스트 파일을 통째로 지운 변경 when 나열하면 then 상태가 deleted이고 단언과 테스트 함수가 모두 나열된다."""
        # given
        (self.repo / "tests/test_app.py").unlink()

        # when
        entry = self.only_entry()

        # then
        self.assertEqual(entry["status"], "deleted")
        self.assertEqual([item["name"] for item in entry["removed_tests"]], ["test_total", "test_rejects_negative"])
        self.assertEqual(len(entry["removed_assertions"]), 3)

    def test_테스트가_아닌_파일의_변경과_같은_파일_안에서_옮긴_단언은_나열하지_않는다(self):
        """given 소스 파일의 assert를 지우고 테스트의 단언 두 줄 순서를 바꾼 변경 when 나열하면 then 아무것도 나열하지 않는다."""
        # given
        swapped = BASE_TESTS.replace("    assert total(2, 3) == 6\n    assert total(0, 3) == 0\n",
                                     "    assert total(0, 3) == 0\n    assert total(2, 3) == 6\n")
        self.write({"app.py": "def total(a, b):\n    return a * b\n", "tests/test_app.py": swapped})

        # when
        found = self.listed()

        # then
        self.assertEqual(found, [])

    def test_커밋하지_않은_변경과_커밋한_변경을_모두_기준과_견준다(self):
        """given 단언을 지우는 변경을 커밋한 뒤 다른 단언을 작업 트리에서 지운 상태 when 나열하면 then 두 변경이 모두 나열된다."""
        # given
        self.write({"tests/test_app.py": BASE_TESTS.replace("    assert total(0, 3) == 0\n", "")})
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "drop one")
        self.write({"tests/test_app.py": BASE_TESTS.replace("    assert total(0, 3) == 0\n", "").replace("    assert total(2, 3) == 6\n", "")})

        # when
        entry = self.only_entry()

        # then
        self.assertEqual([item["text"] for item in entry["removed_assertions"]], ["assert total(2, 3) == 6", "assert total(0, 3) == 0"])

    def test_없는_기준_리비전은_종료_코드_2와_고칠_방법을_알리는_메시지로_끝난다(self):
        """given 저장소에 없는 리비전 이름 when 실행하면 then 종료 코드 2이고 stdout은 비고 stderr가 어떤 리비전을 줘야 하는지 알린다."""
        # given
        command = [sys.executable, str(SCRIPT), "no-such-revision", "--repo", str(self.repo)]

        # when
        done = subprocess.run(command, capture_output=True, text=True)

        # then
        self.assertEqual((done.returncode, done.stdout), (2, ""))
        self.assertIn("Pass a revision that exists", done.stderr)


if __name__ == "__main__":
    unittest.main()
