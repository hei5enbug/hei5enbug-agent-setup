"""Offline tests for the p3 measurement tooling: list prices of the comparison candidates and the absolute codex path."""
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals" / "e2e"))

from harness import cli, pricing  # noqa: E402

REQUEST = {"input": 100_000, "cache_read": 100_000, "cache_write": 0, "output": 50_000}


class CodexPricesTest(unittest.TestCase):
    def test_gpt_6_2_sol과_gpt_6_luna는_공식_정가로_계산한다(self):
        """2026-11-20 정가표(1M 토큰당 입력/캐시/출력): 6.2-sol 2.00/0.10/10.00, 6-luna 0.10/0.01/0.50."""
        self.assertAlmostEqual(pricing.codex_cost("gpt-6.2-sol", REQUEST), 0.71)
        self.assertAlmostEqual(pricing.codex_cost("gpt-6-luna", REQUEST), 0.036)

    def test_272K를_넘는_요청은_장문맥_정가로_계산한다(self):
        """입력 합이 272K를 넘으면 6.2-sol은 4.00/0.20/15.00, 6-luna는 0.20/0.02/0.75이다."""
        big = {"input": 300_000, "cache_read": 0, "cache_write": 0, "output": 1_000_000}
        self.assertAlmostEqual(pricing.codex_cost("gpt-6.2-sol", big), 16.2)
        self.assertAlmostEqual(pricing.codex_cost("gpt-6-luna", big), 0.81)


class CapCandidatesTest(unittest.TestCase):
    def cap_with(self, value):
        env = {key: val for key, val in os.environ.items() if key != "HARNESS_ALLOW_CANDIDATES"}
        if value is not None:
            env["HARNESS_ALLOW_CANDIDATES"] = value
        code = "import sys; sys.path.insert(0, %r); from harness import config; print(sorted(config.MODEL_CAP))" % str(ROOT / "evals" / "e2e")
        return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True).stdout

    def test_환경_변수가_없으면_상한은_그대로다(self):
        self.assertNotIn("gpt-6.2-sol", self.cap_with(None))
        self.assertNotIn("gpt-6-luna", self.cap_with("0"))

    def test_환경_변수가_1이면_비교_후보가_상한에_들어온다(self):
        shown = self.cap_with("1")
        self.assertIn("gpt-6.2-sol", shown)
        self.assertIn("gpt-6-luna", shown)
        self.assertIn("gpt-6.1-sol", shown)


class CodexBinTest(unittest.TestCase):
    def test_가짜_codex가_PATH_앞에_있어도_하네스는_진짜_codex_경로를_쓴다(self):
        """작업 env가 PATH 앞에 가짜 codex를 두기 전에 하네스가 codex를 절대 경로로 확정한다."""
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "real" / "codex"
            real.parent.mkdir()
            real.write_text("#!/bin/sh\n")
            real.chmod(real.stat().st_mode | stat.S_IXUSR)
            args = cli.build_parser().parse_args(["run", "--campaign", "x", "--variants", "v", "--run-root", tmp])
            old = os.environ["PATH"]
            os.environ["PATH"] = f"{real.parent}:{old}"
            try:
                cfg = cli.config_from(args)
            finally:
                os.environ["PATH"] = old
            self.assertEqual(cfg.codex_bin, str(real))

    def test_codex가_없으면_이름을_그대로_둔다(self):
        args = cli.build_parser().parse_args(["run", "--campaign", "x", "--variants", "v"])
        old = os.environ["PATH"]
        os.environ["PATH"] = "/nonexistent"
        try:
            cfg = cli.config_from(args)
        finally:
            os.environ["PATH"] = old
        self.assertEqual(cfg.codex_bin, "codex")


if __name__ == "__main__":
    unittest.main()
