from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "text_review.py"
FAKE_CODEX = REPO_ROOT / "tests" / "fixtures" / "fake_codex.py"
SHARED_TEXT = REPO_ROOT / "instructions" / "shared-text.md"
CLEAN_DRAFT = "## Summary\n\nThe parser now rejects empty input.\n\n- Added a guard for empty input.\n"
USAGE_LIMIT_MESSAGE = "You have reached your usage limit"
EXIT_REVIEW_FAILED, EXIT_USAGE_LIMIT = 3, 4

STUB_RUNNER = textwrap.dedent(
    """
    import os, sys
    mode = os.environ["STUB_MODE"]
    if mode == "split":
        first = os.path.join(os.environ["STUB_OUT"], "first")
        try:
            os.close(os.open(first, os.O_CREAT | os.O_EXCL))
            mode = "usage-stderr"
        except FileExistsError:
            mode = "auth"
    if mode == "usage-stderr":
        sys.stderr.write("role_runner: codex exited with 1: You have reached your usage limit\\n")
    elif mode == "usage-stdout":
        print('{"type": "error", "message": "You have reached your usage limit"}')
    elif mode == "auth":
        sys.stderr.write("role_runner: codex exited with 1: authentication failed\\n")
    elif mode == "auth-stdout":
        print("authentication failed")
    sys.exit(1)
    """
)


class FailureTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.draft = self.root / "demo-a.md"
        self.draft.write_text(CLEAN_DRAFT, encoding="utf-8")

    def review(self, *extra, env=None, runner=None):
        command = [sys.executable, str(SCRIPT), "review", "--kind", "pr-description", "--draft", str(self.draft), *extra]
        if runner is not None:
            command += ["--runner", str(runner)]
        return subprocess.run(command, capture_output=True, text=True, env={**os.environ, **(env or {})}, timeout=120)


class StubRunnerFailureTest(FailureTestCase):
    def setUp(self):
        super().setUp()
        self.runner = self.root / "stub_runner.py"
        self.runner.write_text(STUB_RUNNER, encoding="utf-8")

    def stub_review(self, mode, *extra):
        return self.review(*extra, env={"STUB_MODE": mode, "STUB_OUT": str(self.root)}, runner=self.runner)

    def test_러너가_사용량_한도_메시지를_내고_실패하면_종료_코드_4와_usage_limit_이유와_그_메시지를_낸다(self):
        for mode in ("usage-stderr", "usage-stdout"):
            with self.subTest(mode=mode):
                # given
                # when
                result = self.stub_review(mode)
                # then
                payload = json.loads(result.stdout)
                self.assertEqual(EXIT_USAGE_LIMIT, result.returncode)
                self.assertEqual("usage_limit", payload["reason"])
                self.assertIn(USAGE_LIMIT_MESSAGE, payload["error"])
                self.assertNotIn("findings", payload)

    def test_다른_이유의_실패는_종료_코드_3을_내고_러너가_낸_원인을_error에_담고_usage_limit_이유는_없다(self):
        for mode in ("auth", "auth-stdout"):
            with self.subTest(mode=mode):
                # given
                # when
                result = self.stub_review(mode)
                # then
                payload = json.loads(result.stdout)
                self.assertEqual(EXIT_REVIEW_FAILED, result.returncode)
                self.assertIn("authentication failed", payload["error"])
                self.assertNotIn("reason", payload)

    def test_러너가_아무것도_출력하지_않고_실패하면_출력이_없다고_말하고_종료_코드_3을_낸다(self):
        # given
        mode = "silent"
        # when
        result = self.stub_review(mode)
        # then
        payload = json.loads(result.stdout)
        self.assertEqual(EXIT_REVIEW_FAILED, result.returncode)
        self.assertIn("exited with 1: the runner gave no output", payload["error"])
        self.assertFalse(payload["error"].rstrip().endswith("exited with 1:"))

    def test_검토자_둘이_모두_사용량_한도로_실패하면_4를_내고_하나라도_다른_이유로_실패하면_3을_낸다(self):
        # given
        reviews = ("--reviews", "2")
        # when
        both = self.stub_review("usage-stderr", *reviews)
        mixed = self.stub_review("split", *reviews)
        # then
        self.assertEqual(EXIT_USAGE_LIMIT, both.returncode)
        self.assertEqual("usage_limit", json.loads(both.stdout)["reason"])
        self.assertEqual(EXIT_REVIEW_FAILED, mixed.returncode)
        self.assertNotIn("reason", json.loads(mixed.stdout))


class FakeCodexRunnerTest(FailureTestCase):
    """The real role runner and text_review.py with a fake `codex` that fails on purpose and makes no model call."""

    def setUp(self):
        super().setUp()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        shutil.copy(FAKE_CODEX, self.bin / "codex")
        self.log = self.root / "codex-calls.jsonl"

    def codex_review(self, message=None, stream="stderr"):
        env = {
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}", "FAKE_CODEX_STREAM": stream,
            "FAKE_CODEX_LOG": str(self.log), "XDG_STATE_HOME": str(self.root / "state"),
            "HOME": str(self.root / "home"),
        }
        if message is not None:
            env["FAKE_CODEX_MESSAGE"] = message
        return self.review(env=env)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def test_가짜_codex가_사용량_한도를_내면_실제_러너를_거쳐도_종료_코드_4와_usage_limit_이유를_낸다(self):
        # given
        # when
        result = self.codex_review()
        # then
        payload = json.loads(result.stdout)
        self.assertEqual(EXIT_USAGE_LIMIT, result.returncode)
        self.assertEqual("usage_limit", payload["reason"])
        self.assertIn(USAGE_LIMIT_MESSAGE, payload["error"])
        self.assertEqual(1, sum(call[:1] == ["exec"] for call in self.calls()))

    def test_가짜_codex가_표준_출력으로_사용량_한도를_내도_실제_러너를_거쳐_종료_코드_4와_그_메시지를_낸다(self):
        # given
        stream = "stdout"
        # when
        result = self.codex_review(stream=stream)
        # then
        payload = json.loads(result.stdout)
        self.assertEqual(EXIT_USAGE_LIMIT, result.returncode)
        self.assertEqual("usage_limit", payload["reason"])
        self.assertIn(USAGE_LIMIT_MESSAGE, payload["error"])

    def test_가짜_codex가_인증_실패를_내면_실제_러너를_거쳐도_종료_코드_3과_그_원인을_낸다(self):
        # given
        message = "authentication failed"
        # when
        result = self.codex_review(message)
        # then
        payload = json.loads(result.stdout)
        self.assertEqual(EXIT_REVIEW_FAILED, result.returncode)
        self.assertIn(message, payload["error"])
        self.assertNotIn("reason", payload)


class SharedTextRuleTest(unittest.TestCase):
    def rule(self, marker):
        lines = SHARED_TEXT.read_text(encoding="utf-8").splitlines()
        start = next(index for index, line in enumerate(lines) if line.startswith(marker))
        end = next((index for index in range(start + 1, len(lines)) if lines[index].startswith("- ")), len(lines))
        return " ".join(line.strip() for line in lines[start:end])

    def test_종료_코드_3_규칙은_원인을_질문에_보이라고_하고_4_규칙은_묻지_않고_올리라고_한다(self):
        # given
        exit3 = self.rule("- Exit 3")
        exit4 = self.rule("- Exit 4")
        # when
        # then
        self.assertIn("ask before posting externally", exit3)
        self.assertIn("`error`", exit3)
        self.assertIn("usage limit", exit4)
        self.assertIn("without asking", exit4)
        self.assertIn("did not run because the reviewer's usage limit was reached", exit4)
        self.assertIn("never a Claude reviewer", exit4)
        self.assertIn("later text of the same session", exit4)


if __name__ == "__main__":
    unittest.main()
