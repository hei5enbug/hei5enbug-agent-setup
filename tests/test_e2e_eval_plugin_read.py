"""Tests that a Claude Code trial of the end-to-end evaluation harness can read the plugin it tests and nothing more."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals/e2e"))

from harness import approval_mcp, campaign, command, matrix, pilot_check, runner  # noqa: E402

TASK = {"id": "T99", "fixture": "f", "prompt_file": "T99.md", "limits": {"wall_seconds": 60, "max_budget_usd": 7}}
PLUGIN_RULE_FILE = "instructions/implementation-execution.md"


class PluginReadDecisionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.folder = self.base / "work" / "run-1"
        self.plugin = self.base / "plugins" / "aaaaaaa" / "demo-plugin"
        self.sibling = self.base / "plugins" / "bbbbbbb" / "demo-plugin"
        for folder in (self.folder / "repo", self.plugin / "instructions", self.sibling / "instructions", self.base / "outside"):
            folder.mkdir(parents=True)
        (self.plugin / PLUGIN_RULE_FILE).write_text("rule", encoding="utf-8")

    def decide(self, tool_name: str, tool_input: dict[str, Any], cwd: Path | None = None) -> str:
        arguments = {"tool_name": tool_name, "input": tool_input}
        return approval_mcp.decision(arguments, str(self.folder), str(cwd or self.folder / "repo"), str(self.plugin))["behavior"]

    def test_플러그인_폴더_안의_읽기_도구는_허용한다(self):
        """Read의 file_path와 Grep, Glob의 path가 내보낸 플러그인 폴더 안이면 allow이고, 상대 경로도 작업 위치를 기준으로 푼다."""
        # given
        target = str(self.plugin / PLUGIN_RULE_FILE)
        relative = os.path.relpath(self.plugin / PLUGIN_RULE_FILE, self.folder / "repo")

        # when
        results = [
            self.decide("Read", {"file_path": target}), self.decide("Read", {"file_path": relative}),
            self.decide("Grep", {"pattern": "rule", "path": str(self.plugin / "instructions")}),
            self.decide("Glob", {"pattern": "*.md", "path": str(self.plugin)}),
        ]

        # then
        self.assertEqual(results, ["allow"] * 4)

    def test_플러그인_폴더_안이라도_파일을_바꾸는_도구는_거부한다(self):
        """Edit, Write, MultiEdit, NotebookEdit는 플러그인 폴더 안 경로도 deny이고 사유가 읽기 전용임을 밝힌다."""
        # given
        target = str(self.plugin / PLUGIN_RULE_FILE)

        # when
        results = [self.decide(tool, {"file_path": target}) for tool in ("Edit", "Write", "MultiEdit")]
        results.append(self.decide("NotebookEdit", {"notebook_path": str(self.plugin / "n.ipynb")}))
        message = approval_mcp.decision({"tool_name": "Write", "input": {"file_path": target}}, str(self.folder), None, str(self.plugin))["message"]

        # then
        self.assertEqual(results, ["deny"] * 4)
        self.assertIn("only Read, Grep, and Glob", message)

    def test_다른_변형의_플러그인과_작업_폴더_밖의_읽기는_거부한다(self):
        """같은 이름의 다른 sha 내보내기, 바깥 폴더, 그 폴더를 가리키는 Grep과 Glob의 path가 모두 deny이다."""
        # given
        other = str(self.sibling / PLUGIN_RULE_FILE)
        elsewhere = str(self.base / "outside" / "notes.md")

        # when
        results = [
            self.decide("Read", {"file_path": other}), self.decide("Read", {"file_path": elsewhere}),
            self.decide("Grep", {"pattern": "x", "path": str(self.sibling)}), self.decide("Glob", {"pattern": "*", "path": str(self.base / "outside")}),
        ]

        # then
        self.assertEqual(results, ["deny"] * 4)

    def test_플러그인_폴더를_상위_경로나_심볼릭_링크로_벗어나는_읽기는_거부한다(self):
        """..로 형제 내보내기에 닿는 경로와 플러그인 안 링크가 밖을 가리키는 경로는 deny이고, 안을 가리키는 링크는 allow이다."""
        # given
        (self.plugin / "to-outside").symlink_to(self.base / "outside", target_is_directory=True)
        (self.plugin / "to-sibling").symlink_to(self.sibling, target_is_directory=True)
        (self.plugin / "to-self").symlink_to(self.plugin / "instructions", target_is_directory=True)
        escaped = str(self.plugin / "instructions" / ".." / ".." / "bbbbbbb" / "demo-plugin" / "instructions")

        # when
        results = [
            self.decide("Read", {"file_path": escaped}), self.decide("Read", {"file_path": str(self.plugin / "to-outside" / "a.md")}),
            self.decide("Read", {"file_path": str(self.plugin / "to-sibling" / "instructions")}),
            self.decide("Read", {"file_path": str(self.plugin / "to-self" / "implementation-execution.md")}),
        ]

        # then
        self.assertEqual(results, ["deny", "deny", "deny", "allow"])

    def test_플러그인_폴더를_넘기지_않으면_읽기도_작업_폴더_안으로만_허용한다(self):
        """읽기 전용 폴더가 없는 승인 서버는 플러그인 폴더 읽기를 예전처럼 deny한다."""
        # given
        arguments = {"tool_name": "Read", "input": {"file_path": str(self.plugin / PLUGIN_RULE_FILE)}}

        # when
        result = approval_mcp.decision(arguments, str(self.folder), str(self.folder / "repo"))

        # then
        self.assertEqual(result["behavior"], "deny")


class PluginReadWiringTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def test_실행이_쓰는_mcp_json은_그_변형의_플러그인_폴더를_읽기_루트로_담는다(self):
        """write_run_files가 쓴 mcp.json의 EVAL_READ_ROOT가 실행의 플러그인 경로이고 작업 폴더와 다르다."""
        # given
        spec = matrix.make_spec(self.root, "camp", "T99", "after", 1)
        plugin = {"path": str(self.root / "plugins" / "abc1234" / "demo-plugin")}
        variant = command.validate_variant({"name": "after", "ref": "HEAD"})

        # when
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.root / "profile")}):
            runner.write_run_files(spec, TASK, variant, "prompt", command.HarnessConfig(run_root=self.root), plugin)

        # then
        env = json.loads((spec.result_dir / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["eval_approver"]["env"]
        self.assertEqual(env["EVAL_READ_ROOT"], plugin["path"])
        self.assertEqual(env["EVAL_RUN_FOLDER"], str(spec.work_dir))

    def test_드라이런은_변형마다_자기_플러그인_폴더를_승인_서버_환경에_보인다(self):
        """두 변형의 드라이런 출력에서 각 실행의 --plugin-dir 값과 approver env의 EVAL_READ_ROOT가 같고 서로 다르다."""
        # given
        tasks_root = self.root / "tasks"
        tasks_root.mkdir()
        (tasks_root / "T99.md").write_text("prompt", encoding="utf-8")
        cfg = command.HarnessConfig(run_root=self.root / "runs", tasks_root=tasks_root)
        variants = {name: command.validate_variant({"name": name, "ref": ref}) for name, ref in (("before", "HEAD~1"), ("after", "HEAD"))}
        specs = campaign.build_specs(cfg, "camp", ["T99"], ["before", "after"], 1)
        out = io.StringIO()

        # when
        campaign.print_plan(out, cfg, specs, {"T99": TASK}, variants)

        # then
        lines = out.getvalue().splitlines()
        pairs = []
        for index, line in enumerate(lines):
            if line.startswith("approver env: "):
                argv = lines[index - 1].split()
                pairs.append((argv[argv.index("--plugin-dir") + 1], json.loads(line.removeprefix("approver env: "))["EVAL_READ_ROOT"]))
        self.assertEqual(len(pairs), 2)
        self.assertTrue(all(plugin == read_root for plugin, read_root in pairs))
        self.assertNotEqual(pairs[0][0], pairs[1][0])


class PilotCheckPluginReadTest(unittest.TestCase):
    PLUGIN = "/tmp/work/export"

    def seed(self, root: Path, approvals: list[dict[str, Any]]) -> None:
        spec = matrix.make_spec(root, "camp", "T13", "baseline", 1)
        matrix.write_json(spec.result_dir / "run.json", {"run_id": spec.run_id, "status": "complete", "plugin": {"path": self.PLUGIN}})
        (spec.result_dir / "stream.jsonl").write_text(json.dumps({"type": "result", "is_error": False}) + "\n", encoding="utf-8")
        (spec.result_dir / "approvals.jsonl").write_text("".join(json.dumps(item) + "\n" for item in approvals), encoding="utf-8")

    def check(self, approvals: list[dict[str, Any]]) -> tuple[int, str]:
        with tempfile.TemporaryDirectory() as tmp:
            self.seed(Path(tmp), approvals)
            out = io.StringIO()
            code = pilot_check.pilot_check(Path(tmp), "camp", frozenset(), out)
            return code, out.getvalue()

    @staticmethod
    def request(tool: str, key: str, path: str, decision: str) -> dict[str, Any]:
        return {"tool_name": tool, "input": {key: path}, "decision": decision}

    def test_자신의_플러그인_안_읽기를_거부한_기록이_있으면_실행_번호와_상대_경로로_실패한다(self):
        """플러그인 안 Read와 Grep의 deny는 FAIL 줄에 플러그인 기준 상대 경로를 남기고, 실행 번호 줄도 나온다."""
        # given
        denied = [self.request("Read", "file_path", f"{self.PLUGIN}/instructions/testing.md", "deny"),
                  self.request("Grep", "path", f"{self.PLUGIN}/skills", "deny")]

        # when
        code, text = self.check(denied)

        # then
        self.assertEqual(code, 1)
        self.assertIn("T13-baseline-r1", text)
        self.assertIn("FAIL no denied read inside the exported plugin: instructions/testing.md, skills", text)

    def test_플러그인_밖_거부나_쓰기_거부나_허용된_읽기만_있으면_통과한다(self):
        """밖 경로의 Read deny, 플러그인 안 Write deny, 플러그인 안 Read allow는 모두 이 항목에서 PASS이다."""
        # given
        clean = [self.request("Read", "file_path", "/tmp/work/elsewhere/a.md", "deny"),
                 self.request("Write", "file_path", f"{self.PLUGIN}/instructions/testing.md", "deny"),
                 self.request("Read", "file_path", f"{self.PLUGIN}/instructions/testing.md", "allow")]

        # when
        _, with_log = self.check(clean)
        _, without_log = self.check([])

        # then
        self.assertIn("PASS no denied read inside the exported plugin", with_log)
        self.assertIn("PASS no denied read inside the exported plugin", without_log)


if __name__ == "__main__":
    unittest.main()
