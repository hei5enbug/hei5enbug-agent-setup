"""Tests for the Codex host of the end-to-end evaluation harness and for the model cap of a measurement."""

from __future__ import annotations

import builtins
import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals/e2e"))

from harness import caps, cli, codex_host, command, matrix, rubric, runner  # noqa: E402
from harness.config import HarnessConfig  # noqa: E402

WITHIN_CAP_ENV = {"CLAUDE_PLUGIN_OPTION_REVIEW_MODEL": "gpt-6.1-sol", "HEI5ENBUG_REVIEW_MODEL": "gpt-6.1-sol"}
AUTH_SENTINEL = "SENTINEL-NEVER-READ"

FAKE_CODEX = """#!{python}
import json, os, stat, sys
log = os.environ["FAKE_CODEX_LOG"]
dev_null = os.stat("/dev/null")
stdin = os.fstat(0)
with open(log, "a", encoding="utf-8") as stream:
    stream.write(json.dumps({{
        "argv": sys.argv[1:], "CODEX_HOME": os.environ.get("CODEX_HOME"), "ZDOTDIR": os.environ.get("ZDOTDIR"),
        "HOME": os.environ.get("HOME"), "stdin_is_dev_null": stat.S_ISCHR(stdin.st_mode) and stdin.st_rdev == dev_null.st_rdev,
        "has_orca": any(name.startswith("ORCA_") for name in os.environ), "cwd": os.getcwd(),
        "zdotdir_entries": sorted(os.listdir(os.environ["ZDOTDIR"])) if os.environ.get("ZDOTDIR") else None,
    }}) + "\\n")
if sys.argv[1:2] == ["exec"]:
    day = os.path.join(os.environ["CODEX_HOME"], "sessions", "2026", "11", "13")
    os.makedirs(day, exist_ok=True)
    rows = json.load(open(os.environ["FAKE_ROLLOUT"]))
    with open(os.path.join(day, "rollout-main.jsonl"), "w", encoding="utf-8") as rollout:
        rollout.write("".join(json.dumps(row) + "\\n" for row in rows))
    print(json.dumps({{"type": "thread.started"}}))
    print(json.dumps({{"type": "turn.completed"}}))
"""


def rollout_rows(model: str = "gpt-6.1-sol", effort: str = "high", cli_version: str = "0.167.2",
                 start: str = "2026-11-13T01:00:00Z", answer: str = "done") -> list[dict[str, Any]]:
    usage = {"input_tokens": 10000, "cached_input_tokens": 2000, "cache_write_input_tokens": 0, "output_tokens": 500,
             "reasoning_output_tokens": 0, "total_tokens": 10500}
    return [
        {"type": "session_meta", "payload": {"timestamp": start, "cwd": "/tmp/work/repo", "cli_version": cli_version}},
        {"type": "turn_context", "payload": {"model": model, "effort": effort, "approval_policy": "never",
                                             "sandbox_policy": {"type": "workspace-write"}}},
        {"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": usage, "last_token_usage": usage}}},
        {"type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": answer}},
    ]


def write_rollout(directory: Path, name: str, rows: list[dict[str, Any]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def write_variants(root: Path, variants: dict[str, dict[str, Any]]) -> Path:
    folder = root / "variants"
    folder.mkdir(parents=True, exist_ok=True)
    for name, body in variants.items():
        (folder / f"{name}.json").write_text(json.dumps({"name": name, "ref": "HEAD", **body}), encoding="utf-8")
    return folder


def run_cli(*args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(args))
    return code, out.getvalue(), err.getvalue()


class DryRunHostsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.variants = write_variants(self.root, {"baseline": {"env": WITHIN_CAP_ENV}})

    def plan(self, hosts: str) -> str:
        code, out, err = run_cli("run", "--campaign", "demo", "--hosts", hosts, "--tasks", "T08", "--dry-run",
                                 "--run-root", str(self.root / "runs"), "--variants-root", str(self.variants))
        self.assertEqual((code, err), (0, ""))
        return out

    def test_두_호스트를_고르면_같은_내보내기_개정에_각자의_고정_모델_명령을_출력한다(self):
        """--hosts claude,codex 드라이런은 Claude 명령과 Codex 명령을 하나씩 출력하고 둘 다 같은 내보낸 플러그인 경로를 쓴다."""
        # given / when
        out = self.plan("claude,codex")

        # then
        lines = out.splitlines()
        claude = next(line for line in lines if line.startswith("claude -p"))
        codex = next(line for line in lines if " codex exec " in line)
        self.assertIn("--model claude-opus-5-5 --effort high", claude)
        self.assertIn("-m gpt-6.1-sol", codex)
        self.assertIn("model_reasoning_effort=\"high\"", codex)
        plugin = claude.split("--plugin-dir ")[1].split(" ")[0]
        self.assertIn(f"codex plugin marketplace add {plugin}", out)

    def test_호스트를_생략하면_Claude_실행만_계획되고_실행_번호와_결과_경로가_예전과_같다(self):
        """--hosts 기본값은 claude라서 run id와 결과 폴더에 호스트가 들어가지 않는다."""
        # given / when
        out = self.plan("claude")

        # then
        self.assertIn("T08-baseline-r1", out)
        self.assertNotIn("codex", out)
        self.assertIn("results/T08/baseline/rep1/settings.json", out)

    def test_알_수_없는_호스트는_거부한다(self):
        """--hosts에 모르는 이름이 있으면 종료 코드 1과 허용 호스트 목록을 알린다."""
        # given / when
        code, _, err = run_cli("run", "--campaign", "demo", "--hosts", "claude,gemini", "--tasks", "T08", "--dry-run",
                               "--run-root", str(self.root / "runs"), "--variants-root", str(self.variants))

        # then
        self.assertEqual(code, 1)
        self.assertIn("claude, codex", err)


class RunLayoutTest(unittest.TestCase):
    def test_Codex_실행만_호스트가_실행_번호와_결과_경로에_들어간다(self):
        """Claude 실행의 경로는 기존 그대로이고 Codex 실행은 <변형>/codex/ 아래이며 run id를 다시 해석할 수 있다."""
        # given
        root = Path("/tmp/runs")

        # when
        claude = matrix.make_spec(root, "c", "T08", "baseline", 2)
        codex = matrix.make_spec(root, "c", "T08", "baseline", 2, "codex")

        # then
        self.assertEqual(claude.result_dir, root / "c/results/T08/baseline/rep2")
        self.assertEqual(codex.result_dir, root / "c/results/T08/baseline/codex/rep2")
        self.assertEqual((claude.run_id, codex.run_id), ("T08-baseline-r2", "T08-baseline-codex-r2"))
        self.assertEqual(matrix.parse_run_id(codex.run_id), ("T08", "baseline", 2, "codex"))
        self.assertEqual(matrix.parse_run_id(claude.run_id), ("T08", "baseline", 2, "claude"))

    def test_변형_이름이_codex로_끝나면_run_id가_모호해져서_거부한다(self):
        """'-codex'로 끝나는 변형 이름은 ConfigError다."""
        # given / when / then
        with self.assertRaises(command.ConfigError):
            command.validate_variant({"name": "fast-codex", "ref": "HEAD"})


class ModelCapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def reject(self, body: dict[str, Any]) -> str:
        variants = write_variants(self.root, {"probe": body})
        code, out, err = run_cli("run", "--campaign", "demo", "--hosts", "claude,codex", "--tasks", "T08", "--dry-run",
                                 "--run-root", str(self.root / "runs"), "--variants", "probe", "--variants-root", str(variants))
        self.assertEqual((code, out), (1, ""))
        return err

    def test_Claude_메인_모델이_상한_밖이면_역할과_상한을_알리고_거부한다(self):
        """claude-fable-5-2를 메인으로 한 변형은 메인 세션 역할과 허용 모델 목록이 담긴 메시지로 거부된다."""
        # given / when
        message = self.reject({"env": WITHIN_CAP_ENV, "models": {"claude": "claude-fable-5-2"}})

        # then
        self.assertIn("main session (Claude Code)", message)
        self.assertIn("claude-fable-5-2", message)
        self.assertIn("model cap (claude-haiku-5-5, claude-opus-5-5, claude-sonnet-5-5, gpt-5.6-luna, gpt-6.1-sol)", message)

    def test_Codex_메인_모델이_상한_밖이면_역할과_상한을_알리고_거부한다(self):
        """gpt-6-astra를 Codex 메인으로 한 변형은 거부된다."""
        # given / when
        message = self.reject({"env": WITHIN_CAP_ENV, "models": {"codex": "gpt-6-astra"}})

        # then
        self.assertIn("main session (Codex)", message)
        self.assertIn("gpt-6-astra", message)
        self.assertIn("model cap", message)

    def test_review_model을_기본값으로_두면_두_호스트_모두_역할과_상한을_알리고_거부한다(self):
        """매니페스트 기본값 gpt-6-astra를 그대로 두는 변형은 Claude Code와 Codex 양쪽 review 역할로 거부된다."""
        # given / when
        message = self.reject({})

        # then
        self.assertIn("role review (Claude Code", message)
        self.assertIn("role review (Codex", message)
        self.assertIn("gpt-6-astra", message)
        self.assertIn("model cap", message)

    def test_review_model을_한쪽_호스트에만_상한_안으로_정하면_다른_호스트는_거부한다(self):
        """Claude용 환경 변수만 정한 변형은 Codex 쪽 review 역할로 거부된다."""
        # given / when
        message = self.reject({"env": {"CLAUDE_PLUGIN_OPTION_REVIEW_MODEL": "gpt-6.1-sol"}})

        # then
        self.assertIn("role review (Codex", message)
        self.assertNotIn("role review (Claude Code", message)

    def test_변형이_환경_변수로_상한_밖_모델을_정하면_그_옵션_역할로_거부한다(self):
        """review_model을 gpt-6-astra로 명시한 변형도 거부된다."""
        # given / when
        message = self.reject({"env": {**WITHIN_CAP_ENV, "HEI5ENBUG_REVIEW_MODEL": "gpt-6-astra"}})

        # then
        self.assertIn("review (Codex, option HEI5ENBUG_REVIEW_MODEL)", message)

    def test_루브릭_채점_모델이_상한_밖이면_채점_역할로_거부한다(self):
        """RUBRIC_MODEL이 상한 밖으로 바뀌면 변형이 문제없어도 캠페인이 시작되지 않는다."""
        # given
        variants = write_variants(self.root, {"probe": {"env": WITHIN_CAP_ENV}})

        # when
        with mock.patch.object(rubric, "RUBRIC_MODEL", "gpt-6-astra"):
            code, _, err = run_cli("run", "--campaign", "demo", "--tasks", "T08", "--dry-run", "--variants", "probe",
                                   "--run-root", str(self.root / "runs"), "--variants-root", str(variants))

        # then
        self.assertEqual(code, 1)
        self.assertIn("rubric grader", err)
        self.assertIn("gpt-6-astra", err)

    def test_저장소의_기본_변형과_루브릭_모델은_상한_안이다(self):
        """커밋된 baseline 변형과 루브릭 채점 모델은 검사를 통과한다."""
        # given
        cfg = HarnessConfig()
        variant = command.load_variant(cfg.variants_root, "baseline")

        # when
        problems = caps.check_variant(cfg, variant) + caps.check_graders()

        # then
        self.assertEqual(problems, [])


class FakeCodexRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.user_home = self.root / "user-codex"
        self.user_home.mkdir()
        (self.user_home / "auth.json").write_text(AUTH_SENTINEL, encoding="utf-8")
        (self.user_home / "config.toml").write_text("model = 'gpt-6-astra'\n", encoding="utf-8")
        self.fake = self.root / "fake_codex"
        self.fake.write_text(FAKE_CODEX.format(python=sys.executable), encoding="utf-8")
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IEXEC)
        self.log = self.root / "calls.jsonl"
        self.rollout = self.root / "rollout.json"
        self.rollout.write_text(json.dumps(rollout_rows()), encoding="utf-8")
        plugin = self.root / "export" / "hei5enbug-agent-setup"
        (plugin / ".agents/plugins").mkdir(parents=True)
        (plugin / ".agents/plugins/marketplace.json").write_text('{"name": "hei5enbug"}', encoding="utf-8")
        self.plugin = {"ref": "HEAD", "sha": "abc", "path": str(plugin)}
        tasks = self.root / "tasks"
        (tasks / "prompts").mkdir(parents=True)
        (tasks / "prompts" / "T08.txt").write_text("--version 옵션을 붙여줘\n", encoding="utf-8")
        self.task = {"id": "T08", "fixture": "demo", "prompt_file": "prompts/T08.txt", "limits": {"wall_seconds": 30, "max_budget_usd": 1}}
        self.variant = command.validate_variant({"name": "baseline", "ref": "HEAD", "env": WITHIN_CAP_ENV})
        self.cfg = HarnessConfig(run_root=self.root / "runs", tasks_root=tasks, codex_bin=str(self.fake),
                                 extra_env={"FAKE_CODEX_LOG": str(self.log), "FAKE_ROLLOUT": str(self.rollout)})
        self.spec = matrix.make_spec(self.cfg.run_root, "c", "T08", "baseline", 1, "codex")
        env = {"CODEX_HOME": str(self.user_home), "ORCA_TERMINAL_HANDLE": "term-1", "ZDOTDIR": "/home/test/zsh"}
        patch_env = mock.patch.dict(os.environ, env)
        patch_env.start()
        self.addCleanup(patch_env.stop)
        os.environ.pop("HARNESS_CODEX_AUTH_HOME", None)
        graders = SimpleNamespace(materialize_fixture=lambda task, fixtures, tasks_root, dest: (Path(dest).mkdir(parents=True), "base1")[1],
                                  grade_run=lambda *args: {"checks": [], "success": True, "correctness": 1.0,
                                                           "test_pass_rate": 1.0, "regressions": 0, "constraints": []})
        patch_graders = mock.patch.object(runner, "load_graders", return_value=graders)
        patch_graders.start()
        self.addCleanup(patch_graders.stop)

    def calls(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def execute(self) -> dict[str, Any]:
        opened: list[str] = []
        real_open = builtins.open

        def spy(file, *args, **kwargs):
            opened.append(str(file))
            return real_open(file, *args, **kwargs)

        with mock.patch.object(builtins, "open", spy), mock.patch("io.open", spy):
            run = runner.execute_run(self.spec, self.task, self.variant, self.plugin, self.cfg, {"codex_version": "codex-cli 0.167.2"})
        self.opened = opened
        return run

    def test_실행은_자격_증명을_링크만_하고_내보낸_폴더에서만_설치하며_ZDOTDIR과_stdin을_격리한다(self):
        """auth.json은 심볼릭 링크로만 이어지고 열리지 않으며, 설치는 내보낸 폴더로만 하고, exec는 빈 ZDOTDIR과 /dev/null stdin으로 돈다."""
        # given / when
        run = self.execute()

        # then
        home = self.spec.result_dir / "codex-home"
        link = home / "auth.json"
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), str(self.user_home / "auth.json"))
        self.assertFalse([path for path in self.opened if path.endswith("auth.json")])
        market, add, exec_call = self.calls()
        self.assertEqual(market["argv"], ["plugin", "marketplace", "add", self.plugin["path"]])
        self.assertEqual(add["argv"], ["plugin", "add", "hei5enbug-agent-setup@hei5enbug"])
        self.assertEqual(exec_call["argv"][:7], ["exec", "--json", "-m", "gpt-6.1-sol", "-c", 'model_reasoning_effort="high"',
                                                 "--dangerously-bypass-hook-trust"])
        self.assertEqual(exec_call["argv"][-2:], ["--", "--version 옵션을 붙여줘"])
        self.assertIn("workspace-write", exec_call["argv"])
        for call in (market, add, exec_call):
            self.assertEqual(call["CODEX_HOME"], str(home))
            self.assertEqual(call["ZDOTDIR"], str(self.spec.result_dir / "zdotdir"))
            self.assertEqual(call["zdotdir_entries"], [])
            self.assertTrue(call["stdin_is_dev_null"])
            self.assertFalse(call["has_orca"])
        self.assertEqual(exec_call["cwd"], str(self.spec.repo.resolve()))
        self.assertEqual(run["status"], "complete")
        self.assertEqual(run["host"], "codex")

    def test_사용자의_Codex_설정_파일은_실행_폴더로_복사되지_않는다(self):
        """실행용 CODEX_HOME에는 자격 증명 링크와 이 실행이 만든 것만 있고 사용자의 config.toml은 없다."""
        # given / when
        self.execute()

        # then
        names = {item.name for item in (self.spec.result_dir / "codex-home").iterdir()}
        self.assertNotIn("config.toml", names)
        self.assertEqual((self.user_home / "config.toml").read_text(encoding="utf-8"), "model = 'gpt-6-astra'\n")

    def test_자격_증명_파일이_없으면_에이전트를_시작하지_않고_infra_failed로_기록한다(self):
        """auth.json이 없으면 codex를 한 번도 부르지 않고 설정 실패를 기록한다."""
        # given
        (self.user_home / "auth.json").unlink()

        # when
        run = self.execute()

        # then
        self.assertEqual(run["status"], "infra_failed")
        self.assertIn("auth.json", run["error"])
        self.assertFalse(self.log.exists())

    def test_HARNESS_CODEX_AUTH_HOME이_있으면_그_폴더의_자격_증명을_잇는다(self):
        """환경 변수로 다른 폴더를 가리키면 링크 대상이 그 폴더의 auth.json이다."""
        # given
        other = self.root / "other-home"
        other.mkdir()
        (other / "auth.json").write_text("x", encoding="utf-8")
        os.environ["HARNESS_CODEX_AUTH_HOME"] = str(other)

        # when
        self.execute()

        # then
        self.assertEqual(os.readlink(self.spec.result_dir / "codex-home" / "auth.json"), str(other / "auth.json"))


class CodexRecordsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        tasks = self.root / "tasks"
        tasks.mkdir()
        self.cfg = HarnessConfig(run_root=self.root / "runs", tasks_root=tasks)
        self.spec = matrix.make_spec(self.cfg.run_root, "c", "T08", "baseline", 1, "codex")
        self.spec.repo.mkdir(parents=True)
        self.task = {"id": "T08", "limits": {"wall_seconds": 30, "max_budget_usd": 1}}
        self.graders = SimpleNamespace(grade_run=lambda *args: {"checks": [], "success": True, "correctness": 1.0,
                                                                "test_pass_rate": 1.0, "regressions": 0, "constraints": []})
        self.run = {"run_id": self.spec.run_id, "task": "T08", "variant": "baseline", "rep": 1, "status": "complete",
                    "wall_seconds": 42.5, "plugin": {"path": "/tmp/p"}, "base_commit": "b", "host": "codex",
                    "expected_model": "gpt-6.1-sol"}
        matrix.write_json(self.spec.result_dir / "run.json", self.run)
        matrix.write_json(self.spec.result_dir / "env.json", {"codex_version": "codex-cli 0.167.2"})

    def metrics(self) -> dict[str, Any]:
        return json.loads((self.spec.result_dir / "metrics.json").read_text(encoding="utf-8"))

    def test_롤아웃에서_시간_토큰_비용과_세션_모델_노력을_기록한다(self):
        """시드한 롤아웃에서 wall_seconds, Codex 토큰과 목록가 비용, env.json의 CLI 버전과 모델과 노력이 만들어진다."""
        # given
        write_rollout(self.spec.result_dir / "codex", "rollout-main.jsonl", rollout_rows(answer="최종 보고"))

        # when
        result = runner.analyze(self.spec, self.task, self.run, self.cfg, self.graders)

        # then
        self.assertEqual(result["wall_seconds"], 42.5)
        self.assertEqual(result["host"], "codex")
        self.assertAlmostEqual(result["cost"]["codex_list_cost_usd_estimate"], (8000 * 2.0 + 2000 * 0.10 + 500 * 10.0) / 1_000_000)
        self.assertEqual(result["tokens"]["codex"]["codex:main"]["gpt-6.1-sol"]["output"], 500)
        self.assertEqual(result["cost"]["claude_list_cost_usd"], 0.0)
        self.assertEqual(result["session"], {"model": "gpt-6.1-sol", "effort": "high", "approval_policy": "never",
                                             "sandbox": "workspace-write"})
        self.assertTrue(result["success"])
        env = json.loads((self.spec.result_dir / "env.json").read_text(encoding="utf-8"))
        self.assertEqual((env["codex_cli_version"], env["codex_session_model"], env["codex_session_effort"]),
                         ("0.167.2", "gpt-6.1-sol", "high"))
        view = json.loads((self.spec.result_dir / "view.json").read_text(encoding="utf-8"))
        self.assertEqual(view["final_answer"], "최종 보고")

    def test_상한_밖_모델이_롤아웃에_답했으면_실행을_실패로_표시하고_모델과_역할을_남긴다(self):
        """자식 롤아웃의 turn_context가 gpt-6-astra이면 채점이 통과여도 success=false와 cap_violation이 metrics.json과 run.json에 남는다."""
        # given
        write_rollout(self.spec.result_dir / "codex", "rollout-main.jsonl", rollout_rows())
        write_rollout(self.spec.result_dir / "codex", "rollout-child.jsonl",
                      rollout_rows(model="gpt-6-astra", start="2026-11-13T01:05:00Z"))

        # when
        updated = runner.regrade_run(self.spec, self.task, self.cfg, self.graders)

        # then
        expected = [{"model": "gpt-6-astra", "role": "codex:unknown"}]
        self.assertFalse(self.metrics()["success"])
        self.assertEqual(self.metrics()["cap_violation"], expected)
        self.assertEqual(updated["cap_violation"], expected)
        self.assertEqual(json.loads((self.spec.result_dir / "run.json").read_text(encoding="utf-8"))["cap_violation"], expected)

    def test_상한_안_모델만_답했으면_cap_violation_필드가_없다(self):
        """위반이 없으면 metrics.json에 cap_violation이 생기지 않는다."""
        # given
        write_rollout(self.spec.result_dir / "codex", "rollout-main.jsonl", rollout_rows())

        # when
        runner.analyze(self.spec, self.task, self.run, self.cfg, self.graders)

        # then
        self.assertNotIn("cap_violation", self.metrics())

    def test_스트림의_사용량_한도_오류는_한도_사유로_읽고_정상_완료와_구분한다(self):
        """turn.failed의 quota 메시지는 usage_limit 사유가 되고, turn.completed만 있으면 완료이며 사유가 없다."""
        # given
        failed = [{"type": "turn.failed", "error": {"message": "You hit your usage limit"}}]
        completed = [{"type": "turn.completed"}]

        # when
        limited, done = codex_host.stream_state(failed), codex_host.stream_state(completed)

        # then
        self.assertEqual((limited["completed"], limited["usage_limit"]), (False, "You hit your usage limit"))
        self.assertEqual((done["completed"], done["usage_limit"]), (True, None))

    def test_역할_러너_상태_줄과_Claude_스트림_모델도_상한_밖이면_위반으로_잡는다(self):
        """role_runner 상태 줄의 model과 결과 메시지 modelUsage의 모델이 상한 밖이면 각 역할 이름과 함께 돌려준다."""
        # given
        status = json.dumps({"role": "reviewer", "runner": "codex", "model": "gpt-6-astra", "exit": 0})
        calls = [{"result_text": f"/tmp/x\n{status}"}]
        stream = [{"type": "result", "modelUsage": {"claude-opus-5-5": {}, "claude-fable-5-2[1m]": {}}}]

        # when
        found = caps.scan_run(stream_events=stream, by_source={}, tool_calls=calls, rollouts=[])

        # then
        self.assertEqual(found, [{"model": "claude-fable-5-2", "role": "main session or subagent (stream modelUsage)"},
                                 {"model": "gpt-6-astra", "role": "role_runner:reviewer"}])


if __name__ == "__main__":
    unittest.main()
