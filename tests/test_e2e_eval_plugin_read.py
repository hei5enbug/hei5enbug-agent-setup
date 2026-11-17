"""Tests that a Claude Code trial of the end-to-end evaluation harness can read the plugin it tests and its own tool outputs, and nothing more."""

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
SESSION = "11111111-2222-4333-8444-555555555555"
OTHER_SESSION = "99999999-8888-4777-8666-555555555555"


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


class ToolResultsDecisionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.folder = self.base / "work" / "run-1"
        self.config = self.base / "claude-config"
        self.project = self.config / "projects" / "-work-run-1-repo"
        self.results = self.project / SESSION / "tool-results"
        self.sibling = self.project / OTHER_SESSION / "tool-results"
        self.other_project = self.config / "projects" / "-work-run-2-repo" / SESSION / "tool-results"
        for folder in (self.folder / "repo", self.results, self.sibling, self.other_project):
            folder.mkdir(parents=True)
        for file in (self.results / "out.txt", self.sibling / "out.txt", self.other_project / "out.txt", self.project / f"{SESSION}.jsonl",
                     self.config / "settings.json", self.config / ".credentials.json", self.project / "memory.md"):
            file.write_text("x", encoding="utf-8")

    def decide(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        arguments = {"tool_name": tool_name, "input": tool_input}
        return approval_mcp.decision(arguments, str(self.folder), str(self.folder / "repo"), None, str(self.results))["behavior"]

    def test_세션_자신의_tool_results_폴더_안_읽기_도구는_허용한다(self):
        """Read의 file_path와 Grep, Glob의 path가 그 세션의 tool-results 폴더 안이면 allow이고, 읽기 범위 옵션이 붙어도 같다."""
        # given
        target = str(self.results / "out.txt")

        # when
        results = [
            self.decide("Read", {"file_path": target, "offset": 40}),
            self.decide("Grep", {"pattern": "x", "path": str(self.results)}),
            self.decide("Glob", {"pattern": "*.txt", "path": str(self.results)}),
        ]

        # then
        self.assertEqual(results, ["allow"] * 3)

    def test_tool_results_폴더에는_쓰기를_허용하지_않는다(self):
        """Write, Edit, MultiEdit, NotebookEdit는 그 폴더 안 경로도 deny이다."""
        # given
        target = str(self.results / "out.txt")

        # when
        results = [self.decide(tool, {"file_path": target}) for tool in ("Write", "Edit", "MultiEdit")]
        results.append(self.decide("NotebookEdit", {"notebook_path": str(self.results / "n.ipynb")}))

        # then
        self.assertEqual(results, ["deny"] * 4)

    def test_다른_세션_프로젝트_그_밖의_설정_폴더_파일은_읽어도_거부한다(self):
        """같은 프로젝트의 다른 세션 폴더, 다른 프로젝트의 같은 세션 번호 폴더, 기록 파일, 설정, 자격 증명, 메모리는 모두 deny이다."""
        # given
        targets = [self.sibling / "out.txt", self.other_project / "out.txt", self.project / f"{SESSION}.jsonl",
                   self.config / "settings.json", self.config / ".credentials.json", self.project / "memory.md"]

        # when
        results = [self.decide("Read", {"file_path": str(path)}) for path in targets]
        results.append(self.decide("Grep", {"pattern": "x", "path": str(self.config)}))
        results.append(self.decide("Glob", {"pattern": "*", "path": str(self.project)}))

        # then
        self.assertEqual(results, ["deny"] * 8)

    def test_tool_results_폴더를_상위_경로나_심볼릭_링크로_벗어나는_읽기는_거부한다(self):
        """..로 다른 세션 폴더에 닿는 경로와 폴더 안 링크가 설정 폴더를 가리키는 경로는 deny이고, 폴더 안을 가리키는 링크는 allow이다."""
        # given
        (self.results / "to-config").symlink_to(self.config, target_is_directory=True)
        (self.results / "to-self").symlink_to(self.results / "out.txt")
        escaped = str(self.results / ".." / ".." / OTHER_SESSION / "tool-results" / "out.txt")

        # when
        results = [
            self.decide("Read", {"file_path": escaped}),
            self.decide("Read", {"file_path": str(self.results / "to-config" / "settings.json")}),
            self.decide("Read", {"file_path": str(self.results / "to-self")}),
        ]

        # then
        self.assertEqual(results, ["deny", "deny", "allow"])

    def test_폴더를_넘기지_않으면_읽기도_작업_폴더_안으로만_허용한다(self):
        """tool-results 폴더가 없는 승인 서버는 그 폴더 읽기를 deny한다."""
        # given
        arguments = {"tool_name": "Read", "input": {"file_path": str(self.results / "out.txt")}}

        # when
        result = approval_mcp.decision(arguments, str(self.folder), str(self.folder / "repo"))

        # then
        self.assertEqual(result["behavior"], "deny")


class ToolResultsWiringTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def test_폴더는_설정_폴더_프로젝트_이름_세션_번호로_정해진다(self):
        """작업 위치 경로의 영숫자 아닌 글자를 -로 바꾼 이름이 프로젝트 폴더가 되고, 200자를 넘으면 폴더를 정하지 않는다."""
        # given
        config = self.root / ".claude"
        repo = self.root / "state.d" / "runs" / "work" / "T01-after-r1" / "repo"
        repo.mkdir(parents=True)
        (self.root / ("a" * 200)).mkdir()

        # when
        found = command.tool_results_root(config, repo, SESSION)
        too_long = command.tool_results_root(config, self.root / ("a" * 200), SESSION)

        # then
        project = "".join(char if char.isascii() and char.isalnum() else "-" for char in str(repo))
        self.assertEqual(found, config / "projects" / project / SESSION / "tool-results")
        self.assertIn("-state-d-runs-work-T01-after-r1-repo", project)
        self.assertIsNone(too_long)

    def test_실행이_쓰는_명령과_mcp_json은_같은_세션의_폴더를_가리킨다(self):
        """--session-id 값이 mcp.json의 EVAL_TOOL_RESULTS_ROOT 안 세션 폴더 이름과 같고 폴더는 설정 폴더 아래 tool-results이다."""
        # given
        spec = matrix.make_spec(self.root, "camp", "T99", "after", 1)
        variant = command.validate_variant({"name": "after", "ref": "HEAD"})
        config = self.root / "claude-config"

        # when
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(config)}):
            argv = runner.write_run_files(spec, TASK, variant, "prompt", command.HarnessConfig(run_root=self.root), {"path": "/tmp/p"})

        # then
        env = json.loads((spec.result_dir / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["eval_approver"]["env"]
        results = Path(env["EVAL_TOOL_RESULTS_ROOT"])
        self.assertEqual(argv[argv.index("--session-id") + 1], results.parent.name)
        self.assertEqual((results.name, results.parent.parent.parent), ("tool-results", config / "projects"))
        self.assertTrue(results.parent.parent.name.endswith("work-T99-after-r1-repo"))

    def test_드라이런은_실행마다_세션_번호와_그_세션의_tool_results_폴더를_보인다(self):
        """드라이런의 --session-id 값과 approver env의 EVAL_TOOL_RESULTS_ROOT 세션 폴더가 같고, 두 실행의 세션 번호는 서로 다르다."""
        # given
        tasks_root = self.root / "tasks"
        tasks_root.mkdir()
        (tasks_root / "T99.md").write_text("prompt", encoding="utf-8")
        cfg = command.HarnessConfig(run_root=self.root / "runs", tasks_root=tasks_root)
        variants = {name: command.validate_variant({"name": name, "ref": "HEAD"}) for name in ("before", "after")}
        specs = campaign.build_specs(cfg, "camp", ["T99"], ["before", "after"], 1)
        out = io.StringIO()

        # when
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/home/test/.claude"}):
            campaign.print_plan(out, cfg, specs, {"T99": TASK}, variants)

        # then
        lines = out.getvalue().splitlines()
        pairs = []
        for index, line in enumerate(lines):
            if line.startswith("approver env: "):
                argv = lines[index - 1].split()
                root = json.loads(line.removeprefix("approver env: "))["EVAL_TOOL_RESULTS_ROOT"]
                pairs.append((argv[argv.index("--session-id") + 1], root))
        self.assertEqual(len(pairs), 2)
        self.assertTrue(all(root.startswith("/home/test/.claude/projects/") and root.endswith(f"/{session}/tool-results") for session, root in pairs))
        self.assertNotEqual(pairs[0][0], pairs[1][0])

    def test_변형은_세션_번호_플래그를_바꾸려_하면_거부한다(self):
        """extra_args의 --session-id는 하네스가 정한 값을 바꾸지 못하도록 거부한다."""
        # given
        variant = {"name": "after", "ref": "HEAD", "extra_args": ["--session-id", SESSION]}

        # when / then
        with self.assertRaises(command.ConfigError):
            command.validate_variant(variant)


class PilotCheckPluginReadTest(unittest.TestCase):
    PLUGIN = "/tmp/work/export"

    def seed(self, root: Path, approvals: list[dict[str, Any]], results_root: str | None = None) -> None:
        spec = matrix.make_spec(root, "camp", "T13", "baseline", 1)
        if results_root is not None:
            matrix.write_json(spec.result_dir / "mcp.json", command.mcp_config(
                spec.result_dir / "approvals.jsonl", spec.work_dir, spec.repo, self.PLUGIN, results_root))
        matrix.write_json(spec.result_dir / "run.json", {"run_id": spec.run_id, "status": "complete", "plugin": {"path": self.PLUGIN}})
        (spec.result_dir / "stream.jsonl").write_text(json.dumps({"type": "result", "is_error": False}) + "\n", encoding="utf-8")
        (spec.result_dir / "approvals.jsonl").write_text("".join(json.dumps(item) + "\n" for item in approvals), encoding="utf-8")

    def check(self, approvals: list[dict[str, Any]], results_root: str | None = None) -> tuple[int, str]:
        with tempfile.TemporaryDirectory() as tmp:
            self.seed(Path(tmp), approvals, results_root)
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

    def test_자신의_tool_results_폴더_안_읽기를_거부한_기록이_있으면_상대_경로로_실패하고_없으면_통과한다(self):
        """mcp.json이 가리키는 폴더 안 Read deny는 FAIL 줄에 폴더 기준 상대 경로를 남기고, 폴더 밖 deny와 안의 allow만 있으면 PASS이다."""
        # given
        results = "/home/test/.claude/projects/-work-run-1-repo/s1/tool-results"
        denied = [self.request("Read", "file_path", f"{results}/b2z9.txt", "deny")]
        clean = [self.request("Read", "file_path", "/home/test/.claude/settings.json", "deny"),
                 self.request("Read", "file_path", f"{results}/b2z9.txt", "allow")]

        # when
        failed_code, failed = self.check(denied, results)
        _, passed = self.check(clean, results)

        # then
        self.assertEqual(failed_code, 1)
        self.assertIn("T13-baseline-r1", failed)
        self.assertIn("FAIL no denied read inside the session's tool-results folder: b2z9.txt", failed)
        self.assertIn("PASS no denied read inside the session's tool-results folder", passed)

    def test_폴더를_모르는_실행도_tool_results_읽기_거부가_있으면_실패시킨다(self):
        """mcp.json에 폴더가 없으면 tool-results 폴더 이름이 든 Read deny를 경로 그대로 FAIL 줄에 남긴다."""
        # given
        path = "/home/test/.claude/projects/-long/s1/tool-results/b2z9.txt"

        # when
        _, text = self.check([self.request("Read", "file_path", path, "deny")])

        # then
        self.assertIn(f"FAIL no denied read inside the session's tool-results folder: {path}", text)


if __name__ == "__main__":
    unittest.main()
