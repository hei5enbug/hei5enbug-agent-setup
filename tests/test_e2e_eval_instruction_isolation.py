"""Tests that a Claude Code trial of the end-to-end evaluation harness loads no user-level memory, rule, or auto memory."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals/e2e"))

from harness import command, environment, matrix, metrics, pilot_check, runner  # noqa: E402

VARIANT_PLUGIN = {"name": "hei5enbug-agent-setup", "source": "hei5enbug-agent-setup@inline", "path": "/tmp/work/export"}
USER_RULE = "/home/test/.claude/rules/common/coding-style.md"
PROJECT_FILE = "/tmp/work/repo/AGENTS.md"
TASK = {"limits": {"wall_seconds": 60, "max_budget_usd": 7}, "env": {}}


def init_event(memory_paths: dict[str, str] | None = None) -> dict[str, Any]:
    event: dict[str, Any] = {"type": "system", "subtype": "init", "session_id": "s-1", "permissionMode": "auto", "plugins": [VARIANT_PLUGIN]}
    return {**event, "memory_paths": memory_paths} if memory_paths is not None else event


def instructions(*files: tuple[str, str]) -> dict[str, Any]:
    return {"type": "attachment", "attachment": {"type": "instructions", "files": [{"path": path, "type": kind, "content": "x"} for path, kind in files]}}


class CommandAndEnvironmentTest(unittest.TestCase):
    def setUp(self):
        self.variant = command.validate_variant({"name": "after", "ref": "HEAD"})
        self.cfg = command.HarnessConfig()

    def argv(self) -> list[str]:
        return command.build_command(self.cfg, TASK, self.variant, "prompt", "/tmp/p", Path("/tmp/run"))

    def overrides(self, variant: dict[str, Any], host: str) -> dict[str, str]:
        spec = matrix.make_spec(Path("/tmp/runs"), "camp", "T13", "after", 1, host)
        return runner.agent_overrides(spec, TASK, variant, self.cfg, Path("/tmp/work/tmp"))

    def test_명령줄은_사용자_설정_출처를_빼고_프로젝트와_로컬만_읽는다(self):
        """--setting-sources 값이 project,local이라 사용자 메모리와 규칙이 올라오지 않고 pilot-check도 문제를 찾지 못한다."""
        # given
        # when
        argv = self.argv()

        # then
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "project,local")
        self.assertEqual(pilot_check.command_problems(argv), [])
        self.assertIn("--settings", argv)

    def test_변형이_설정_출처_플래그를_바꾸려_하면_거부한다(self):
        """extra_args에 --setting-sources를 적으면 두 형태 모두 ConfigError이다."""
        # given
        spaced = {"name": "v", "ref": "HEAD", "extra_args": ["--setting-sources", "user"]}
        joined = {"name": "v", "ref": "HEAD", "extra_args": ["--setting-sources=user,project"]}

        # when / then
        for variant in (spaced, joined):
            with self.assertRaises(command.ConfigError):
                command.validate_variant(variant)

    def test_pilot_check는_사용자_출처를_읽는_명령줄과_출처_플래그_없는_명령줄을_실패시킨다(self):
        """user가 들어 있거나 플래그가 없는 명령줄은 각각 이유가 문제 목록에 남는다."""
        # given
        argv = self.argv()
        with_user = [("user,project" if item == "project,local" else item) for item in argv]
        without = argv[:argv.index("--setting-sources")] + argv[argv.index("--setting-sources") + 2:]

        # when
        user_problems, missing_problems = pilot_check.command_problems(with_user), pilot_check.command_problems(without)

        # then
        self.assertEqual(user_problems, ["user setting source loaded"])
        self.assertEqual(missing_problems, ["missing --setting-sources"])

    def test_Claude_Code_실행_환경은_자동_메모리를_끄고_변형_환경이_되살릴_수_없다(self):
        """변형 env가 CLAUDE_CODE_DISABLE_AUTO_MEMORY=0을 적어도 Claude Code 실행에서는 1이고, Codex 실행은 변형 값을 그대로 둔다."""
        # given
        variant = command.validate_variant({"name": "v", "ref": "HEAD", "env": {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "0"}})

        # when
        claude_env, codex_env = self.overrides(variant, "claude"), self.overrides(variant, "codex")

        # then
        self.assertEqual(claude_env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"], "1")
        self.assertEqual(codex_env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"], "0")

    def test_env_json은_Claude_Code_실행에만_격리_방법과_남은_한계를_적는다(self):
        """격리 기록을 넘기면 출처 목록, 환경 변수, 한계가 env.json 내용에 들어가고 넘기지 않으면 키가 없다."""
        # given
        base = {"claude_version": "x"}
        isolation = runner.INSTRUCTION_ISOLATION

        # when
        claude = environment.run_snapshot(base, {}, [], isolation)
        codex = environment.run_snapshot(base, {}, [])

        # then
        record = claude["instruction_isolation"]
        self.assertEqual((record["setting_sources"], record["env"]), ("project,local", {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}))
        self.assertTrue(record["known_limits"])
        self.assertNotIn("instruction_isolation", codex)


class PilotCheckInstructionTest(unittest.TestCase):
    def seed(self, root: Path, main: list[dict[str, Any]], init: dict[str, Any], isolated: bool = True) -> Path:
        spec = matrix.make_spec(root, "camp", "T13", "baseline", 1)
        folder = spec.result_dir
        matrix.write_json(folder / "run.json", {"run_id": spec.run_id, "status": "complete", "plugin": {"path": VARIANT_PLUGIN["path"]}})
        stream = [init, {"type": "result", "is_error": False}]
        (folder / "stream.jsonl").write_text("\n".join(json.dumps(event) for event in stream) + "\n", encoding="utf-8")
        (folder / "transcripts").mkdir()
        (folder / "transcripts" / "main.jsonl").write_text("\n".join(json.dumps(event) for event in main) + "\n", encoding="utf-8")
        argv = command.build_command(command.HarnessConfig(), TASK, command.validate_variant({"name": "b", "ref": "HEAD"}), "p", "/tmp/p", folder)
        matrix.write_json(folder / "command.json", {"argv": argv})
        matrix.write_json(folder / "env.json", {"instruction_isolation": runner.INSTRUCTION_ISOLATION} if isolated else {})
        return folder

    def check(self, main: list[dict[str, Any]], init: dict[str, Any], isolated: bool = True) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            self.seed(Path(tmp), main, init, isolated)
            out = io.StringIO()
            pilot_check.pilot_check(Path(tmp), "camp", frozenset(), out)
            return out.getvalue()

    def test_사용자_규칙_파일을_읽은_기록은_실패하고_파일_경로를_밝힌다(self):
        """사용자 규칙 파일이 지침 첨부에 있으면 FAIL 줄에 그 경로가 나오고 프로젝트 파일만 있으면 PASS이다."""
        # given
        dirty = [instructions((USER_RULE, "User"), (PROJECT_FILE, "Project"))]
        clean = [instructions((PROJECT_FILE, "Project"))]

        # when
        dirty_out, clean_out = self.check(dirty, init_event()), self.check(clean, init_event())

        # then
        self.assertIn(f"FAIL no user-level memory or rule file loaded: {USER_RULE}", dirty_out)
        self.assertNotIn(PROJECT_FILE, dirty_out)
        self.assertIn("PASS no user-level memory or rule file loaded", clean_out)

    def test_init_이벤트에_자동_메모리_경로가_있으면_실패한다(self):
        """memory_paths.auto가 있는 실행은 FAIL 줄에 그 경로가 나오고 없는 실행은 PASS이다."""
        # given
        memory = {"auto": "/home/test/.claude/projects/demo/memory/"}

        # when
        dirty_out, clean_out = self.check([], init_event(memory)), self.check([], init_event())

        # then
        self.assertIn(f"FAIL no auto memory path in the init event: {memory['auto']}", dirty_out)
        self.assertIn("PASS no auto memory path in the init event", clean_out)

    def test_env_json에_자동_메모리_끔이_없으면_실패한다(self):
        """격리 기록이 없는 env.json은 자동 메모리 끔 항목이 FAIL이고 있으면 PASS이다."""
        # given
        # when
        without, with_record = self.check([], init_event(), isolated=False), self.check([], init_event())

        # then
        self.assertIn("FAIL auto memory switched off for the run", without)
        self.assertIn("PASS auto memory switched off for the run", with_record)

    def test_지침_첨부가_아닌_이벤트는_무시하고_사용자_파일만_모은다(self):
        """다른 형태의 이벤트가 섞여 있어도 오류 없이 사용자 파일 경로만 반환한다."""
        # given
        events = [instructions((USER_RULE, "User")), {"type": "user"}, {"attachment": "text"}]

        # when
        found = metrics.user_instruction_files(events)

        # then
        self.assertEqual(found, [USER_RULE])


if __name__ == "__main__":
    unittest.main()
