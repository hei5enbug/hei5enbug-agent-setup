#!/usr/bin/env python3
"""이슈 초안 검사 스크립트의 종류별 탐지, 세션 값, 단어 목록 탐색, 출력 형식, 종료 코드를 검사한다."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = SKILL.parents[1]
SCRIPT = SKILL / "scripts" / "scan_draft.py"
PRIVATE_WORD = "example" + "-corp"
HOME_PATH = "/home/" + "jdoe" + "/project"
SECRET = "ghp" + "_" + "a" * 24
EMAIL = "jdoe" + "@" + "mailhost" + ".io"


class CheckDraftCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.env = {
            **{k: v for k, v in os.environ.items() if not k.startswith(("HEI5ENBUG_", "CLAUDE_", "CODEX_"))},
            "HOME": str(self.base / "h"),
            "CLAUDE_CONFIG_DIR": str(self.base / "claude"),
            "CODEX_HOME": str(self.base / "codex"),
        }

    def run_script(self, draft: str, *args: str, script: Path = SCRIPT) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(script), *args], input=draft, text=True, capture_output=True,
                              env=self.env, cwd=self.base)

    def declare_words(self, root: Path, words: list[str]) -> Path:
        root.mkdir(parents=True)
        (root / "public-boundary.json").write_text(
            json.dumps({"version": 1, "private_words_file": "words.txt"}), encoding="utf-8")
        (root / "words.txt").write_text("\n".join(words) + "\n", encoding="utf-8")
        return root

    def install_words(self, words: list[str]) -> None:
        root = self.declare_words(self.base / "installs" / "demo-private", words)
        listing = self.base / "claude" / "plugins" / "installed_plugins.json"
        listing.parent.mkdir(parents=True)
        listing.write_text(json.dumps({"plugins": {"demo-private@m": [{"installPath": str(root)}]}}), encoding="utf-8")


class CheckDraftTests(CheckDraftCase):
    def test_깨끗한_초안은_clean과_종료_코드_0을_낸다(self) -> None:
        """찾은 것이 없으면 status clean, 빈 findings, 읽은 목록 0개로 끝난다."""
        # given
        draft = "The skill asked for a fix.\nSee ABC-123 on example.com.\n"

        # when
        result = self.run_script(draft)

        # then
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"status": "clean", "findings": [], "private_word_lists": 0, "problems": []},
                         json.loads(result.stdout))

    def test_홈_경로와_비밀_값과_이메일을_줄과_종류로만_알린다(self) -> None:
        """종류별로 줄 번호와 종류만 내고 찾은 값은 출력에 없다."""
        # given
        draft = f"first\npath {HOME_PATH}\nkey {SECRET}\nmail {EMAIL}\n"

        # when
        result = self.run_script(draft)

        # then
        self.assertEqual(1, result.returncode)
        data = json.loads(result.stdout)
        self.assertEqual("matches", data["status"])
        self.assertEqual([(2, "home-path"), (3, "github-token"), (4, "email")],
                         [(item["line"], item["kind"]) for item in data["findings"]])
        for leaked in ("jdoe", SECRET, "mailhost"):
            self.assertNotIn(leaked, result.stdout)

    def test_세션_값은_대소문자와_상관없이_단어_단위로_맞추고_인덱스를_알린다(self) -> None:
        """--value는 대소문자를 가리지 않는 단어 일치이고 몇 번째 값인지만 알린다."""
        # given
        draft = "Acme Widgets shipped\nacmewidgets is not a match\nticket DEMO-7 here\n"

        # when
        result = self.run_script(draft, "--value", "acme widgets", "--value", "demo")

        # then
        self.assertEqual(1, result.returncode)
        findings = json.loads(result.stdout)["findings"]
        self.assertEqual([{"line": 1, "kind": "session-value", "value": 0},
                          {"line": 3, "kind": "session-value", "value": 1}], findings)

    def test_설치된_플러그인_선언의_단어를_찾고_단어는_출력하지_않는다(self) -> None:
        """발견한 모든 목록을 읽어 비공개 단어를 잡고, 읽은 목록 수를 알린다."""
        # given
        self.install_words([PRIVATE_WORD])

        # when
        result = self.run_script(f"we use {PRIVATE_WORD.upper()} daily\n")

        # then
        self.assertEqual(1, result.returncode)
        data = json.loads(result.stdout)
        self.assertEqual([{"line": 1, "kind": "private-word"}], data["findings"])
        self.assertEqual(1, data["private_word_lists"])
        self.assertNotIn(PRIVATE_WORD, (result.stdout + result.stderr).lower())

    def test_플러그인_루트로_받은_설치되지_않은_플러그인의_선언도_읽는다(self) -> None:
        """--plugin-root로 받은 이슈 대상 플러그인이 설치 목록에 없어도 그 선언의 비공개 단어를 잡는다."""
        # given
        owner = self.declare_words(self.base / "checkout" / "demo-owner", [PRIVATE_WORD])
        draft = f"we use {PRIVATE_WORD} daily\n"

        # when
        without = self.run_script(draft)
        with_root = self.run_script(draft, "--plugin-root", str(owner))

        # then
        self.assertEqual((0, 1), (without.returncode, with_root.returncode), with_root.stderr)
        data = json.loads(with_root.stdout)
        self.assertEqual([{"line": 1, "kind": "private-word"}], data["findings"])
        self.assertEqual(1, data["private_word_lists"])

    def test_없는_플러그인_루트는_사용법_오류다(self) -> None:
        """--plugin-root가 폴더가 아니면 아무것도 검사하지 않고 종료 코드 2로 끝난다."""
        # given
        missing = self.base / "missing"

        # when
        result = self.run_script("text\n", "--plugin-root", str(missing))

        # then
        self.assertEqual(2, result.returncode)
        self.assertEqual("", result.stdout)

    def test_읽을_수_없는_선언은_unavailable과_종료_코드_3으로_알린다(self) -> None:
        """단어 목록을 쓸 수 없으면 깨끗하다고 하지 않고 문제를 이름으로 알린다."""
        # given
        self.install_words([PRIVATE_WORD])
        (self.base / "installs" / "demo-private" / "words.txt").unlink()

        # when
        result = self.run_script("a clean draft\n")

        # then
        self.assertEqual(3, result.returncode)
        data = json.loads(result.stdout)
        self.assertEqual("unavailable", data["status"])
        self.assertTrue(data["problems"][0].startswith("demo-private: "))

    def test_스캐너를_불러올_수_없으면_unavailable과_종료_코드_3이다(self) -> None:
        """플러그인 루트에 .githooks가 없으면 unavailable로 끝난다."""
        # given
        copy = self.base / "copy"
        shutil.copytree(SKILL, copy / "skills" / "skill-issue-creator", ignore=shutil.ignore_patterns("__pycache__"))

        # when
        result = self.run_script("text\n", script=copy / "skills" / "skill-issue-creator" / "scripts" / "scan_draft.py")

        # then
        self.assertEqual(3, result.returncode)
        self.assertEqual("unavailable", json.loads(result.stdout)["status"])

    def test_사용법_오류는_종료_코드_2이다(self) -> None:
        """알 수 없는 옵션이나 빈 --value는 종료 코드 2다."""
        # given
        cases = (("--bogus",), ("--value", ""), ("--value",))

        # when
        results = [self.run_script("text\n", *args) for args in cases]

        # then
        self.assertEqual([2, 2, 2], [result.returncode for result in results])

    def test_플러그인_루트는_세_단계_위_폴더를_가리킨다(self) -> None:
        """스크립트가 올라가서 찾는 폴더에 정본 스캐너가 있다."""
        # given
        scanner = PLUGIN_ROOT / ".githooks" / "public_boundary.py"

        # when
        exists = scanner.is_file()

        # then
        self.assertTrue(exists)


if __name__ == "__main__":
    unittest.main()
