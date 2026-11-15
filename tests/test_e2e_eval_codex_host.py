"""Tests for the Codex host of the end-to-end evaluation harness and for the model cap of a measurement."""

from __future__ import annotations

import builtins
import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals/e2e"))

from harness import (  # noqa: E402
    caps, cli, codex_calls, codex_host, codex_trust, collect, command, graders, matrix, metrics, rubric, runner,
)
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
        "guard": [os.environ.get("CLAUDE_PLUGIN_OPTION_APPROVAL_GUARD"), os.environ.get("HEI5ENBUG_APPROVAL_GUARD")],
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


PLUGIN_ID = codex_trust.hook_trust_module().PLUGIN_ID
HOOK_FILE = "/tmp/plugin/hooks/hooks.json"


def demo_hook(name: str, status: str, plugin: str = PLUGIN_ID) -> dict[str, Any]:
    return {"pluginId": plugin, "key": f"{plugin}:{name}", "trustStatus": status, "currentHash": f"sha256:{name}",
            "sourcePath": HOOK_FILE}


class FakeAppServer:
    """Stands in for `app_server_calls`: the first session lists `before`, every later one lists `after`."""

    def __init__(self, before: list[dict[str, Any]], after: list[dict[str, Any]] | None = None):
        self.before, self.after, self.sessions = before, before if after is None else after, []

    def __call__(self, command: list[str], env: dict[str, str], cwd: str, calls: list[tuple[str, dict]], timeout: float) -> list:
        self.sessions.append({"command": command, "codex_home": env.get("CODEX_HOME"), "calls": list(calls)})
        hooks = self.before if len(self.sessions) == 1 else self.after
        return [{"data": [{"cwd": params["cwds"][0], "hooks": hooks}]} if method == "hooks/list" else {} for method, params in calls]

    def writes(self) -> list[dict[str, Any]]:
        return [params for session in self.sessions for method, params in session["calls"] if method == "config/value/write"]


def patch_app_server(server: Any) -> Any:
    return mock.patch.object(codex_trust.hook_trust_module(), "app_server_calls", server)


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
        patch_server = patch_app_server(FakeAppServer([demo_hook("start", "trusted")]))
        patch_server.start()
        self.addCleanup(patch_server.stop)

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
        self.assertEqual(exec_call["argv"][exec_call["argv"].index("-s") + 1], "danger-full-access")
        for call in (market, add, exec_call):
            self.assertEqual(call["CODEX_HOME"], str(home))
            self.assertEqual(call["ZDOTDIR"], str(self.spec.result_dir / "zdotdir"))
            self.assertEqual(call["zdotdir_entries"], [".zprofile"])
            self.assertTrue(call["stdin_is_dev_null"])
            self.assertFalse(call["has_orca"])
        self.assertEqual(exec_call["cwd"], str(self.spec.repo.resolve()))
        self.assertEqual(run["status"], "complete")
        self.assertEqual(run["host"], "codex")

    def test_Codex_실행의_에이전트_환경은_승인_가드를_두_변수_모두_false로_끈다(self):
        """Codex에는 ask를 대신 답하는 승인 도구가 없으므로 측정 실행은 변형이 정하지 않아도 가드를 끈 환경으로 시작한다."""
        # given / when
        self.execute()

        # then
        exec_call = self.calls()[-1]
        self.assertEqual(exec_call["guard"], ["false", "false"])

    def test_변형의_env가_정한_가드_값은_하네스_기본값보다_우선한다(self):
        """변형이 HEI5ENBUG_APPROVAL_GUARD를 다른 값으로 정하면 그 값이 에이전트 환경에 들어가고 다른 변수는 기본값을 지킨다."""
        # given
        self.variant = command.validate_variant({"name": "baseline", "ref": "HEAD",
                                                 "env": {**WITHIN_CAP_ENV, "HEI5ENBUG_APPROVAL_GUARD": "true"}})

        # when
        self.execute()

        # then
        self.assertEqual(self.calls()[-1]["guard"], ["false", "true"])

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


class PreparedHomeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        user_home = self.root / "user-codex"
        user_home.mkdir()
        (user_home / "auth.json").write_text(AUTH_SENTINEL, encoding="utf-8")
        self.user_home = user_home
        fake = self.root / "fake_codex"
        fake.write_text(FAKE_CODEX.format(python=sys.executable), encoding="utf-8")
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        plugin = self.root / "export" / "hei5enbug-agent-setup"
        (plugin / ".agents/plugins").mkdir(parents=True)
        (plugin / ".agents/plugins/marketplace.json").write_text('{"name": "hei5enbug"}', encoding="utf-8")
        self.plugin_dir = str(plugin)
        self.cfg = HarnessConfig(run_root=self.root / "runs", codex_bin=str(fake))
        self.result_dir = self.root / "result"
        self.result_dir.mkdir()
        self.env = {**os.environ, **codex_host.host_env(self.result_dir), "FAKE_CODEX_LOG": str(self.root / "calls.jsonl")}

    def prepare(self, server: FakeAppServer, env: dict[str, str] | None = None) -> dict[str, Any]:
        with patch_app_server(server):
            return codex_host.prepare_home(self.cfg, self.result_dir, self.plugin_dir, env or self.env, self.user_home)

    def setup_record(self) -> dict[str, Any]:
        return json.loads((self.result_dir / "codex-setup.json").read_text(encoding="utf-8"))


class CodexShellPathTest(PreparedHomeCase):
    @unittest.skipUnless(shutil.which("zsh"), "zsh is not installed")
    def test_실행의_ZDOTDIR로_시작한_zsh_로그인_셸은_실행이_정한_PATH를_그대로_쓴다(self):
        """macOS path_helper가 /etc/zprofile에서 PATH를 다시 정렬해도 로그인 셸의 PATH는 실행 환경의 PATH와 정확히 같다."""
        # given
        run_path = "/tmp/demo-bin:/usr/bin:/bin:/tmp/demo-tools"
        self.prepare(FakeAppServer([demo_hook("start", "trusted")]), {**self.env, "PATH": run_path})
        shell_env = {"ZDOTDIR": str(self.result_dir / "zdotdir"), "PATH": run_path}

        # when
        done = subprocess.run([shutil.which("zsh"), "-lc", 'printf %s "$PATH"'], env=shell_env, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=30, check=False)

        # then
        self.assertEqual(done.stdout, run_path)

    def test_PATH에_공백과_따옴표가_있어도_zprofile은_그_값_하나로_PATH를_정한다(self):
        """.zprofile은 셸 인용을 거친 export 한 줄이고 다른 내용은 없다."""
        # given
        run_path = "/tmp/demo dir/it's:/usr/bin"

        # when
        self.prepare(FakeAppServer([demo_hook("start", "trusted")]), {**self.env, "PATH": run_path})

        # then
        entries = sorted(item.name for item in (self.result_dir / "zdotdir").iterdir())
        self.assertEqual(entries, [".zprofile"])
        lines = (self.result_dir / "zdotdir" / ".zprofile").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("export PATH="))


class CodexHookTrustTest(PreparedHomeCase):
    def test_이_플러그인의_untrusted와_modified_훅에만_신뢰_쓰기를_하고_기록한다(self):
        """신뢰 쓰기는 이 플러그인의 untrusted와 modified 훅마다 한 번이고, 이미 trusted인 훅과 다른 플러그인의 훅에는 없다."""
        # given
        other = "other-plugin@demo"
        before = [demo_hook("a", "untrusted"), demo_hook("b", "modified"), demo_hook("c", "trusted"),
                  demo_hook("d", "untrusted", other)]
        after = [{**hook, "trustStatus": "trusted"} if hook["pluginId"] == PLUGIN_ID else hook for hook in before]
        server = FakeAppServer(before, after)

        # when
        record = self.prepare(server)

        # then
        writes = server.writes()
        self.assertEqual(len(writes), 2)
        for name in ("a", "b"):
            matching = [params for params in writes if f"{PLUGIN_ID}:{name}" in params["keyPath"]]
            self.assertEqual([params["value"]["trusted_hash"] for params in matching], [f"sha256:{name}"])
        skipped = (f"{PLUGIN_ID}:c", f"{other}:d")
        self.assertFalse([params for params in writes if any(key in params["keyPath"] for key in skipped)])
        self.assertEqual({session["codex_home"] for session in server.sessions}, {str(self.result_dir / "codex-home")})
        self.assertEqual(sorted(record["hook_trust"]["trusted"]), [f"{PLUGIN_ID}:a", f"{PLUGIN_ID}:b"])
        self.assertEqual(self.setup_record()["hook_trust"], record["hook_trust"])

    def test_쓰기_뒤에도_이_플러그인의_훅_하나가_untrusted면_설정_실패로_기록하고_멈춘다(self):
        """다시 나열한 훅 중 하나가 아직 untrusted이면 CodexSetupError가 나고 codex-setup.json에 사유가 남는다."""
        # given
        before = [demo_hook("a", "untrusted"), demo_hook("b", "untrusted")]
        server = FakeAppServer(before, [demo_hook("a", "trusted"), demo_hook("b", "untrusted")])

        # when
        with self.assertRaises(codex_host.CodexSetupError) as caught:
            self.prepare(server)

        # then
        self.assertIn("trust", str(caught.exception))
        self.assertIn(f"{PLUGIN_ID}:b", self.setup_record()["hook_trust_error"])
        self.assertNotIn("hook_trust", self.setup_record())

    def test_app_server가_오류를_내면_설정_실패로_바꾼다(self):
        """app-server 호출이 TrustError로 끝나면 실행은 훅을 신뢰하지 못한 채 시작하지 않고 CodexSetupError를 낸다."""
        # given
        error = codex_trust.hook_trust_module().TrustError("codex app-server ended before answering request 2")

        def failing(*args: Any, **kwargs: Any) -> list:
            raise error

        # when
        with self.assertRaises(codex_host.CodexSetupError) as caught, patch_app_server(failing):
            codex_host.prepare_home(self.cfg, self.result_dir, self.plugin_dir, self.env, self.user_home)

        # then
        self.assertIn("ended before answering", str(caught.exception))
        self.assertIn("ended before answering", self.setup_record()["hook_trust_error"])

    def test_이_플러그인의_훅이_하나도_나열되지_않으면_설정_실패로_바꾼다(self):
        """다른 플러그인의 훅만 보이면 내보낸 플러그인이 로드되지 않은 것이므로 CodexSetupError다."""
        # given
        server = FakeAppServer([demo_hook("x", "trusted", "other-plugin@demo")])

        # when
        with self.assertRaises(codex_host.CodexSetupError):
            self.prepare(server)

        # then
        self.assertIn("no", self.setup_record()["hook_trust_error"])


ROLE_RUNNER_REVIEW = ('python3 /tmp/plugin/scripts/role_runner.py review --assignment /tmp/work/a.md '
                      '--result /tmp/work/r.md')
SCRIPT_HEADER = {"type": "input_text", "text": "Script completed\nWall time 1.3 seconds\nOutput:\n"}
DEMO_STATUS = {"role": None, "capability": "review", "runner": "claude", "model": "claude-opus-5-5",
               "evidence": {"transcript": "/tmp/demo/r.jsonl"}}


def status_line(exit_code: int) -> str:
    return json.dumps({**DEMO_STATUS, "exit": exit_code})


def chunk_item(**fields: Any) -> dict[str, str]:
    return {"type": "input_text", "text": json.dumps({"chunk_id": "1", "wall_time_seconds": 1.0, **fields})}


def exec_pair(call_id: str, script: str, items: list[dict[str, str]]) -> list[dict[str, Any]]:
    call = {"type": "custom_tool_call", "name": "exec", "call_id": call_id, "input": script}
    done = {"type": "custom_tool_call_output", "call_id": call_id, "output": [SCRIPT_HEADER, *items]}
    return [{"type": "response_item", "payload": call}, {"type": "response_item", "payload": done}]


def run_command(command_text: str) -> str:
    return f'text(await tools.exec_command({{cmd:"{command_text}",max_output_tokens:2000}}));'


class CodexExecOutputTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = HarnessConfig(run_root=self.root / "runs", tasks_root=self.root / "tasks")
        self.spec = matrix.make_spec(self.cfg.run_root, "c", "T08", "baseline", 1, "codex")
        self.run = {"run_id": self.spec.run_id, "task": "T08", "variant": "baseline", "rep": 1, "host": "codex"}

    def calls_of(self, exec_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return codex_calls.rollout_tool_calls(exec_events, "main", "rollout-main.jsonl")

    def test_종료_코드가_있는_exec_command_조각의_출력과_종료_코드가_Bash_호출과_위임_exit에_들어온다(self):
        """exec_command 조각의 output은 이스케이프가 풀린 채 result_text가 되고, exit_code 3이 오류 표시와 위임의 exit 3이 된다."""
        # given
        output = f"role_runner: reviewer failed\n{status_line(3)}\n"
        events = exec_pair("c1", run_command(ROLE_RUNNER_REVIEW), [chunk_item(exit_code=3, output=output)])
        write_rollout(self.spec.result_dir / "codex", "rollout-main.jsonl", [*rollout_rows(), *events])

        # when
        view = codex_host.load_records(self.spec, self.run, "gpt-6.1-sol")["view"]

        # then
        bash = [call for call in view["tool_calls"] if call["name"] == "Bash"]
        self.assertEqual(len(bash), 1)
        self.assertIn(status_line(3), bash[0]["result_text"])
        self.assertTrue(bash[0]["is_error"])
        self.assertEqual(metrics.runner_calls(view), {"review": {"3": 1}})

    def test_나중_exec의_write_stdin이_가져온_상태_줄이_먼저_시작한_호출에_붙고_러너_기록_경로가_보인다(self):
        """세션 101이 나중에 낸 출력은 그 세션을 시작한 호출에 붙고, 다른 명령의 출력은 그대로이며, write_stdin은 호출을 만들지 않는다."""
        # given
        first = exec_pair("c1", run_command(ROLE_RUNNER_REVIEW), [chunk_item(session_id=101, output="")])
        script = run_command("ls /tmp/work") + '\ntext(await tools.write_stdin({session_id:101,chars:"",yield_time_ms:30000}));'
        later = exec_pair("c2", script, [chunk_item(exit_code=0, output="a.md\n"),
                                         chunk_item(exit_code=0, output=f"{status_line(0)}\n")])

        # when
        calls = self.calls_of([*first, *later])

        # then
        self.assertEqual([call["input"]["command"] for call in calls], [ROLE_RUNNER_REVIEW, "ls /tmp/work"])
        self.assertIn(status_line(0), calls[0]["result_text"])
        self.assertFalse(calls[0]["is_error"])
        self.assertEqual(calls[1]["result_text"], "a.md\n")
        self.assertEqual([path for _, path in collect.runner_transcript_paths(calls)], [Path("/tmp/demo/r.jsonl")])

    def test_출력_항목_수가_문장_수와_다르면_전체_출력을_첫_명령에_붙이던_방식을_유지한다(self):
        """exec 두 문장에 항목이 하나뿐이면 항목을 문장에 짝지어 추정하지 않고 헤더까지 합친 출력을 첫 호출에 둔다."""
        # given
        script = run_command("ls /tmp/work") + "\n" + run_command("cat /tmp/work/a.md")
        events = exec_pair("c1", script, [{"type": "input_text", "text": "only-one"}])

        # when
        calls = self.calls_of(events)

        # then
        self.assertEqual([call["result_text"] for call in calls], [SCRIPT_HEADER["text"] + "\nonly-one", ""])


def assistant_message(text: str) -> dict[str, Any]:
    return {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                                                  "content": [{"type": "output_text", "text": text}]}}


def native_spawn(call_id: str, task_name: str, agent_type: str | None) -> list[dict[str, Any]]:
    """A native subagent call as Codex writes it: a `spawn_agent` function call and its output naming the child."""
    arguments = {"task_name": task_name, "fork_turns": "none", "message": "gAAAAAB-encrypted",
                 **({"agent_type": agent_type, "model": "gpt-6.1-sol", "reasoning_effort": "high"} if agent_type else {})}
    call = {"type": "function_call", "name": "spawn_agent", "namespace": "collaboration", "call_id": call_id,
            "arguments": json.dumps(arguments)}
    done = {"type": "function_call_output", "call_id": call_id, "output": json.dumps({"task_name": f"/root/{task_name}"})}
    return [{"type": "response_item", "payload": call}, {"type": "response_item", "payload": done}]


class CodexNativeDelegationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = HarnessConfig(run_root=self.root / "runs", tasks_root=self.root / "tasks")
        self.spec = matrix.make_spec(self.cfg.run_root, "c", "T08", "baseline", 1, "codex")
        self.run = {"run_id": self.spec.run_id, "task": "T08", "variant": "baseline", "rep": 1, "host": "codex"}

    def view_of(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        rows = rollout_rows()
        write_rollout(self.spec.result_dir / "codex", "rollout-main.jsonl", [*rows[:-1], *events, rows[-1]])
        return codex_host.load_records(self.spec, self.run, "gpt-6.1-sol")["view"]

    def test_네이티브_spawn_agent_호출은_이름이_붙은_역할의_위임으로_시작_지표에_들어온다(self):
        """spawn_agent가 worker를 띄우면 위임 하나가 구현 역할로 보이고 launches_by_type과 tool_calls에도 남는다."""
        # given
        events = native_spawn("c1", "edit_config", "worker") + [assistant_message("done")]

        # when
        view = self.view_of(events)

        # then
        delegations = [item for item in view["delegations"] if item["kind"] == "agent"]
        self.assertEqual([(item["type"], item["class"], item["completed"]) for item in delegations],
                         [("worker", "implementation", True)])
        self.assertEqual(metrics.launches_by_type(view), {"worker": 1})
        self.assertEqual([call["name"] for call in view["tool_calls"]], ["spawn_agent"])

    def test_역할을_적지_않은_spawn_agent도_위임으로_세고_wait_agent는_위임이_아니다(self):
        """agent_type이 없는 spawn_agent는 기본 역할의 위임이고, 결과를 기다리는 wait_agent 호출은 위임이나 호출로 세지 않는다."""
        # given
        wait = {"type": "response_item", "payload": {"type": "function_call", "name": "wait_agent", "call_id": "w1",
                                                      "arguments": json.dumps({"timeout_ms": 20000})}}

        # when
        view = self.view_of([*native_spawn("c1", "scan", None), wait])

        # then
        self.assertEqual([(item["type"], item["class"]) for item in view["delegations"]], [("general-purpose", "other")])
        self.assertEqual(len(view["tool_calls"]), 1)

    def test_네이티브_reviewer_위임은_보고_전에_끝난_검토로_센다(self):
        """spawn_agent로 reviewer를 띄운 뒤 최종 답이 나오면 review_before_report가 통과한다."""
        # given
        events = native_spawn("c1", "final_review", "reviewer") + [assistant_message("report")]

        # when
        view = self.view_of(events)
        passed, _, _ = graders.check_review_before_report(SimpleNamespace(view=view), {})

        # then
        self.assertTrue(passed)

    def test_최종_exec_안에서_검토_명령_뒤에_보고하면_위임_순서와_답변_순서가_같은_세기라_검토가_보고_전으로_센다(self):
        """한 exec가 git diff와 완료된 검토 명령을 함께 돌리고 그다음 보고하면 final_answer_order가 정규화한 호출 수 2이고 검토가 통과한다."""
        # given
        script = run_command("git diff") + "\n" + run_command(ROLE_RUNNER_REVIEW)
        items = [chunk_item(exit_code=0, output="diff\n"), chunk_item(exit_code=0, output=f"{status_line(0)}\n")]
        events = [*exec_pair("c1", script, items), assistant_message("report")]

        # when
        view = self.view_of(events)
        passed, detail, _ = graders.check_review_before_report(SimpleNamespace(view=view), {})

        # then
        self.assertEqual(view["final_answer_order"], 2)
        self.assertEqual([item["order"] for item in view["delegations"]], [1])
        self.assertTrue(passed, detail)

    def test_보고_뒤에_시작한_검토_명령은_보고_전으로_세지_않는다(self):
        """최종 답 뒤에 exec로 시작한 검토 명령은 order가 final_answer_order 이상이라 review_before_report가 실패한다."""
        # given
        events = [assistant_message("report"), *exec_pair("c1", run_command(ROLE_RUNNER_REVIEW),
                                                           [chunk_item(exit_code=0, output=f"{status_line(0)}\n")])]

        # when
        view = self.view_of(events)
        passed, _, _ = graders.check_review_before_report(SimpleNamespace(view=view), {})

        # then
        self.assertEqual(view["final_answer_order"], 0)
        self.assertFalse(passed)


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
