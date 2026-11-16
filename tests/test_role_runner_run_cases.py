from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("role_runner_run_cases", REPO_ROOT / "evals/role-runner-scratch/run_cases.py")
driver = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = driver
spec.loader.exec_module(driver)

FAKE_RUNNER = '''
import json, sys
from pathlib import Path

argv = sys.argv
result = Path(argv[argv.index("--result") + 1])
base = result.parent
mutate = (base / "mutate.flag").exists()
rollout = base / "rollout.jsonl"
role = argv[1]
if role == "reviewer":
    calls = [("python -m pytest -q", "FAILED tests/test_pricing.py::test_bulk_discount - assert 4950 == 5000")]
    answer = "The discount starts at eleven units; test_bulk_discount shows it."
else:
    calls = [("python3 - <<'EOF'\\nprint(1)\\nEOF", "3075")]
    answer = "The total is 3075."
lines = []
for command, output in calls:
    lines.append(json.dumps({"type": "response_item", "payload": {"type": "function_call", "arguments": json.dumps({"cmd": command})}}))
    lines.append(json.dumps({"type": "response_item", "payload": {"type": "function_call_output", "output": output}}))
rollout.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
result.write_text(answer, encoding="utf-8")
if mutate:
    (Path.cwd() / "stray.txt").write_text("x", encoding="utf-8")
print(json.dumps({"verified": True, "evidence": {"rollout": rollout.as_posix()}, "exit": 0}))
'''


class EvidencePathTest(unittest.TestCase):
    def test_검증된_상태_줄의_rollout_또는_transcript_경로를_돌려준다(self):
        """given 잡음 뒤에 검증된 상태 줄이 있는 출력 when 증거 경로를 읽으면 then rollout, 없으면 transcript 경로를 돌려준다."""
        # given
        codex = 'note\n{"verified": true, "evidence": {"rollout": "/tmp/work/r.jsonl"}, "exit": 0}\n'
        claude = '{"verified": true, "evidence": {"transcript": "/tmp/work/t.jsonl"}, "exit": 0}\n'

        # when
        paths = (driver.evidence_path(codex), driver.evidence_path(claude))

        # then
        self.assertEqual(("/tmp/work/r.jsonl", "/tmp/work/t.jsonl"), paths)

    def test_검증되지_않았거나_경로가_없거나_상태_줄이_없으면_오류다(self):
        """given 검증 실패, 경로 없음, 상태 줄 없음의 출력 when 증거 경로를 읽으면 then 각각 ValueError로 이유를 알린다."""
        # given
        outputs = (
            '{"verified": false, "evidence": {"error": "x"}, "exit": 4}',
            '{"verified": true, "evidence": {"turns": 1}, "exit": 0}',
            "no json here",
        )

        # when / then
        for text in outputs:
            with self.subTest(text=text), self.assertRaises(ValueError):
                driver.evidence_path(text)


class DryRunTest(unittest.TestCase):
    def test_dry_run은_세_사례의_명령을_출력하고_폴더를_만들지_않는다(self):
        """given 없는 작업 폴더 when --dry-run으로 실행하면 then 5에서 7의 시드, 실행, 검사 명령이 출력되고 작업 폴더는 생기지 않는다."""
        # given
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp) / "work"
            out = io.StringIO()

            # when
            with contextlib.redirect_stdout(out):
                code = driver.main(["--dry-run", "--workdir", str(workdir)])

            # then
            text = out.getvalue()
            self.assertEqual(0, code)
            self.assertFalse(workdir.exists())
            self.assertIn("reviewer --model gpt-6.1-sol --validation", text)
            self.assertIn("reviewer --model claude-opus-5-5 --validation", text)
            self.assertIn("seed " + str(workdir / "demo-6") + " --with-env", text)
            self.assertNotIn("--with-env", text.split("case 6")[0])
            scout_run = next(line for line in text.splitlines() if " scout" in line and "role_runner.py" in line)
            self.assertNotIn("--validation", scout_run)
            self.assertEqual(3, text.count("demo.py check"))

    def test_선택한_사례만_계획한다(self):
        """given 사례 7만 고른 인자 when --dry-run으로 실행하면 then 사례 7의 명령만 출력된다."""
        # given
        out = io.StringIO()

        # when
        with contextlib.redirect_stdout(out):
            code = driver.main(["7", "--dry-run", "--workdir", "/tmp/work"])

        # then
        self.assertEqual(0, code)
        self.assertIn("case 7:", out.getvalue())
        self.assertNotIn("case 5:", out.getvalue())


class RunCaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workdir = Path(self.temp.name)
        self.runner = self.workdir / "fake_runner.py"
        self.runner.write_text(FAKE_RUNNER, encoding="utf-8")

    def test_가짜_실행기의_기록으로_사례_5와_7이_통과한다(self):
        """given 조건을 만족하는 기록을 남기는 가짜 실행기 when 사례 5와 7을 실행하면 then 두 사례 모두 통과로 보고하고 종료 코드 0이다."""
        # given
        out = io.StringIO()

        # when
        with contextlib.redirect_stdout(out):
            code = driver.main(["5", "7", "--workdir", str(self.workdir), "--runner", str(self.runner)])

        # then
        results = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(0, code)
        self.assertEqual([(5, True), (7, True)], [(item["case"], item["pass"]) for item in results])

    def test_저장소를_바꾸면_사례가_실패하고_종료_코드_1이다(self):
        """given 저장소에 파일을 남기는 가짜 실행기 when 사례 7을 실행하면 then 스냅샷 변경 실패가 보고되고 종료 코드 1이다."""
        # given
        (self.workdir / "mutate.flag").write_text("", encoding="utf-8")
        out = io.StringIO()

        # when
        with contextlib.redirect_stdout(out):
            code = driver.main(["7", "--workdir", str(self.workdir), "--runner", str(self.runner)])

        # then
        result = json.loads(out.getvalue())
        self.assertEqual(1, code)
        self.assertFalse(result["pass"])
        self.assertIn("git status --porcelain --ignored changed", result["failures"])


if __name__ == "__main__":
    unittest.main()
