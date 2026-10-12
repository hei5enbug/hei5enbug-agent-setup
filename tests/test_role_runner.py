from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))
import role_runner  # noqa: E402
import session_context  # noqa: E402
from test_model_pins import PINS  # noqa: E402

RUNNER = REPO_ROOT / "scripts" / "role_runner.py"
THREAD = "019e0000-aaaa-bbbb-cccc-000000000001"
SESSION = "11111111-2222-3333-4444-555555555555"

FAKE_EXECUTABLE = '''#!{python}
import json, os, sys, time
from pathlib import Path

name = Path(sys.argv[0]).name
config = json.loads(os.environ.get("FAKE_CONFIG", "{{}}"))
stdin = sys.stdin.read()
Path(os.environ["FAKE_LOG"]).write_text(json.dumps({{
    "name": name, "argv": sys.argv[1:], "stdin": stdin, "cwd": os.getcwd(),
    "role": os.environ.get("HEI5ENBUG_ASSIGNED_ROLE"), "pid": os.getpid(),
}}))
if config.get("sleep"):
    time.sleep(config["sleep"])
if config.get("exit"):
    sys.stderr.write("fake failure")
    sys.exit(config["exit"])
if name == "codex":
    argv = sys.argv[1:]
    if "-o" in argv:
        Path(argv[argv.index("-o") + 1]).write_text(config.get("message", "codex answer"))
    if not config.get("no_thread"):
        print(json.dumps({{"type": "thread.started", "thread_id": config.get("thread", "{thread}")}}))
    print(json.dumps({{"type": "turn.completed"}}))
    if not config.get("no_rollout"):
        home = Path(os.environ["CODEX_HOME"]) / "sessions" / "2026" / "10" / "12"
        home.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps({{"type": "session_meta", "payload": {{"id": "x"}}}})]
        for turn in config.get("turns", [{{"model": "gpt-6-luna", "effort": "xhigh"}}]):
            lines.append(json.dumps({{"type": "turn_context", "payload": turn}}))
        (home / "rollout-2026-10-12T00-00-00-{thread}.jsonl").write_text("\\n".join(lines) + "\\n")
else:
    model = config.get("model", "claude-opus-5-5")
    print(json.dumps({{
        "type": "result", "is_error": config.get("is_error", False), "result": config.get("message", "claude answer"),
        "session_id": "{session}", "modelUsage": config.get("usage", {{model: {{}}}}),
    }}))
    if not config.get("no_transcript"):
        home = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / "-some-project"
        home.mkdir(parents=True, exist_ok=True)
        lines = []
        for entry in config.get("entries", [{{"model": model, "effort": "xhigh"}}]):
            record = {{"type": "assistant", "message": {{"model": entry.get("model")}}}}
            if "effort" in entry:
                record["effort"] = entry["effort"]
            lines.append(json.dumps(record))
        (home / "{session}.jsonl").write_text("\\n".join(lines) + "\\n")
'''


class RoleRunnerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        body = FAKE_EXECUTABLE.format(python=sys.executable, thread=THREAD, session=SESSION)
        for name in ("codex", "claude"):
            path = self.bin / name
            path.write_text(body)
            path.chmod(0o755)
        self.workspace = self.base / "workspace"
        self.workspace.mkdir()
        self.assignment = self.base / "assignment.md"
        self.assignment.write_text("Find the answer.\nSECOND LINE\n")
        self.result = self.base / "result.md"
        self.log = self.base / "log.json"
        self.codex_home = self.base / "codex-home"
        self.claude_home = self.base / "claude-home"

    def run_runner(self, *arguments, config=None, path=None, assignment=True, result=True):
        command = [sys.executable, str(RUNNER), *arguments]
        if assignment:
            command += ["--assignment", str(self.assignment)]
        if result:
            command += ["--result", str(self.result)]
        env = {
            "PATH": str(self.bin) if path is None else path,
            "HOME": str(self.base),
            "CODEX_HOME": str(self.codex_home),
            "CLAUDE_CONFIG_DIR": str(self.claude_home),
            "FAKE_LOG": str(self.log),
            "FAKE_CONFIG": json.dumps(config or {}),
        }
        return subprocess.run(command, cwd=self.workspace, env=env, capture_output=True, text=True, timeout=60)

    def logged(self):
        return json.loads(self.log.read_text())

    def status(self, completed):
        return json.loads(completed.stdout.strip().splitlines()[-1])

    def codex_argv(self, *, search=False, sandbox="read-only", model="gpt-6-luna", add_dirs=()):
        argv = ["--search"] if search else []
        argv += ["exec", "-m", model, "-c", 'model_reasoning_effort="xhigh"', "-s", sandbox, "-C", str(self.workspace)]
        for directory in add_dirs:
            argv += ["--add-dir", directory]
        return argv + ["--json", "-o", str(self.result), "-"]

    def test_scout는_읽기_전용_codex_exec_인자로_실행되고_검증된다(self):
        """scout는 고정된 읽기 전용 codex exec 인자로 실행되고 검증된 결과를 남긴다."""
        # Given
        arguments = ["scout"]

        # When
        completed = self.run_runner(*arguments)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.codex_argv(), self.logged()["argv"])
        self.assertEqual("codex answer", self.result.read_text())
        status = self.status(completed)
        self.assertEqual(
            {"role": "scout", "runner": "codex", "model": "gpt-6-luna", "effort": "xhigh", "verified": True, "exit": 0},
            {key: status[key] for key in ("role", "runner", "model", "effort", "verified", "exit")},
        )
        self.assertEqual(1, status["evidence"]["turns"])

    def test_researcher는_최상위_search_플래그로_codex를_실행한다(self):
        """researcher는 codex 바로 뒤에 --search를 두고 exec 뒤에는 두지 않는다."""
        # Given
        arguments = ["researcher"]

        # When
        completed = self.run_runner(*arguments)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        argv = self.logged()["argv"]
        self.assertEqual(self.codex_argv(search=True), argv)
        self.assertEqual(1, argv.count("--search"))
        self.assertLess(argv.index("--search"), argv.index("exec"))

    def test_worker는_workspace_write와_승인된_add_dir만_넘긴다(self):
        """worker는 workspace-write 샌드박스와 받은 --add-dir 각각만 넘긴다."""
        # Given
        directories = [str(self.base / "one"), str(self.base / "two")]
        arguments = ["worker", "--add-dir", directories[0], "--add-dir", directories[1]]

        # When
        completed = self.run_runner(*arguments)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.codex_argv(sandbox="workspace-write", add_dirs=directories), self.logged()["argv"])

    def test_reviewer는_기본_모델로_gpt_6_astra를_쓴다(self):
        """reviewer에 --model이 없으면 gpt-6-astra로 codex exec를 실행한다."""
        # Given
        config = {"turns": [{"model": "gpt-6-astra", "effort": "xhigh"}]}

        # When
        completed = self.run_runner("reviewer", config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.codex_argv(model="gpt-6-astra"), self.logged()["argv"])
        self.assertEqual("gpt-6-astra", self.status(completed)["model"])

    def test_reviewer는_GPT_모델을_지정하면_scout와_같은_방식으로_실행된다(self):
        """reviewer에 GPT 모델 ID를 주면 그 모델로 읽기 전용 codex exec를 실행한다."""
        # Given
        config = {"turns": [{"model": "gpt-6.1-sol", "effort": "xhigh"}]}

        # When
        completed = self.run_runner("reviewer", "--model", "gpt-6.1-sol", config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.codex_argv(model="gpt-6.1-sol"), self.logged()["argv"])

    def test_reviewer는_Claude_모델을_지정하면_claude_p로_실행하고_프롬프트를_표준_입력으로_받는다(self):
        """reviewer에 Claude 모델 ID를 주면 읽기 전용 claude -p 인자로 실행하고 결과 글을 저장한다."""
        # Given
        arguments = ["reviewer", "--model", "claude-opus-5-5"]

        # When
        completed = self.run_runner(*arguments)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        logged = self.logged()
        self.assertEqual("claude", logged["name"])
        self.assertEqual(
            [
                "-p", "--model", "claude-opus-5-5", "--effort", "xhigh", "--output-format", "json",
                "--tools", "Read", "Grep", "Glob", "--strict-mcp-config", "--permission-mode", "dontAsk",
                "--allowedTools", "Read", "Grep", "Glob",
            ],
            logged["argv"],
        )
        self.assertIn("Find the answer.", logged["stdin"])
        self.assertEqual("claude answer", self.result.read_text())
        status = self.status(completed)
        self.assertEqual(("claude", "claude-opus-5-5", True), (status["runner"], status["model"], status["verified"]))

    def test_모든_역할의_인자에는_금지된_플래그가_없다(self):
        """어떤 역할도 cd, --ephemeral, --dangerously-*, danger-full-access, 샌드박스 -c 덮어쓰기를 넘기지 않는다."""
        # Given
        cases = [
            (["scout"], None),
            (["researcher"], None),
            (["worker", "--add-dir", str(self.base)], None),
            (["reviewer"], {"turns": [{"model": "gpt-6-astra", "effort": "xhigh"}]}),
            (["reviewer", "--model", "claude-opus-5-5"], None),
        ]

        # When
        collected = []
        for arguments, config in cases:
            self.run_runner(*arguments, config=config)
            collected.append(self.logged()["argv"])

        # Then
        for argv in collected:
            text = " ".join(argv)
            self.assertNotIn("cd", argv)
            self.assertNotIn("--ephemeral", argv)
            self.assertNotIn("--dangerously", text)
            self.assertNotIn("danger-full-access", text)
            self.assertNotIn("sandbox", text)
            configs = [argv[index + 1] for index, item in enumerate(argv) if item in ("-c", "--config")]
            self.assertTrue(all(item.startswith("model_reasoning_effort=") for item in configs), configs)

    def test_자식_환경에_역할_환경변수가_들어간다(self):
        """자식 프로세스는 실행한 역할 이름을 HEI5ENBUG_ASSIGNED_ROLE로 받는다."""
        # Given
        roles = ["scout", "researcher", "worker"]

        # When
        seen = []
        for role in roles:
            self.run_runner(role)
            seen.append(self.logged()["role"])

        # Then
        self.assertEqual(roles, seen)

    def test_자식은_현재_작업_폴더에서_실행된다(self):
        """실행기는 현재 작업 폴더를 세션 폴더로 쓴다."""
        # Given
        arguments = ["scout"]

        # When
        self.run_runner(*arguments)

        # Then
        self.assertEqual(str(self.workspace), self.logged()["cwd"])

    def test_프롬프트는_역할_문장과_역할_정의와_할당_순서로_표준_입력에_들어간다(self):
        """표준 입력은 compose_prompt가 만든 글과 같다."""
        # Given
        expected = role_runner.compose_prompt("scout", self.assignment.read_text(), REPO_ROOT)

        # When
        self.run_runner("scout")

        # Then
        self.assertEqual(expected, self.logged()["stdin"])

    def test_compose_prompt는_역할마다_문장과_역할_정의_본문과_할당을_담는다(self):
        """scout, researcher, reviewer 프롬프트는 역할 문장, 프런트매터 없는 정의 본문, 할당을 담고 Assigned workers 절은 담지 않는다."""
        # Given
        roles = ["scout", "researcher", "reviewer"]

        # When
        prompts = {role: role_runner.compose_prompt(role, "ASSIGNMENT TEXT", REPO_ROOT) for role in roles}

        # Then
        for role, prompt in prompts.items():
            body = (REPO_ROOT / "agents" / f"{role}.md").read_text().split("---", 2)[2].strip()
            self.assertTrue(prompt.startswith(role_runner.ROLE_SENTENCES[role]), role)
            self.assertIn(body, prompt)
            self.assertNotIn("model: ", prompt)
            self.assertNotIn("tools: ", prompt)
            self.assertNotIn("## Assigned workers", prompt)
            self.assertTrue(prompt.rstrip().endswith("## Assignment\n\nASSIGNMENT TEXT"), role)

    def test_compose_prompt의_역할_문장은_계약된_뜻을_담는다(self):
        """역할 문장은 에이전트 금지, 커밋 금지, 네트워크 규칙, 반환 계약을 각 역할에 맞게 적는다."""
        # Given
        sentences = role_runner.ROLE_SENTENCES

        # When
        scout, researcher, reviewer, worker = (sentences[role] for role in role_runner.ROLES)

        # Then
        self.assertIn("read-only scout", scout)
        self.assertIn("use no network", scout)
        self.assertIn("read-only public researcher", researcher)
        self.assertIn("only the web search tool and no shell network", researcher)
        self.assertIn('assigned reviewer under the "Assigned workers" rules', reviewer)
        self.assertIn("return findings only under the role's output contract", reviewer)
        self.assertIn('assigned worker under the "Assigned workers" rules', worker)
        self.assertIn("edit only the allowed paths", worker)
        for sentence in sentences.values():
            self.assertIn("start no agents, make no commit or push", sentence)

    def test_compose_prompt는_worker에만_Assigned_workers_절을_담는다(self):
        """worker 프롬프트는 역할 정의 본문 뒤, 할당 앞에 session_context의 Assigned workers 절을 담는다."""
        # Given
        section = session_context.assigned_workers_section(REPO_ROOT)

        # When
        prompt = role_runner.compose_prompt("worker", "ASSIGNMENT TEXT", REPO_ROOT)

        # Then
        self.assertIn(section, prompt)
        self.assertLess(prompt.index("Execute the implementation task"), prompt.index(section))
        self.assertLess(prompt.index(section), prompt.index("## Assignment"))
        self.assertTrue(prompt.startswith(role_runner.ROLE_SENTENCES["worker"]))

    def test_compose_prompt는_알_수_없는_역할을_거부한다(self):
        """역할 목록에 없는 이름은 ValueError로 거부한다."""
        # Given
        role = "designer"

        # When
        with self.assertRaises(ValueError) as caught:
            role_runner.compose_prompt(role, "x", REPO_ROOT)

        # Then
        self.assertIn("designer", str(caught.exception))

    def test_스크립트의_모델_ID는_모델_고정값_일곱_개와_같다(self):
        """검토 모델 목록은 PINS의 일곱 ID와 정확히 같다."""
        # Given
        pins = set(PINS.values())

        # When
        listed = set(role_runner.REVIEW_MODELS)

        # Then
        self.assertEqual(pins, listed)
        self.assertEqual(7, len(role_runner.REVIEW_MODELS))
        self.assertIn(role_runner.DEFAULT_REVIEW_MODEL, listed)
        self.assertIn(role_runner.ROLE_MODEL, listed)

    def test_rollout의_모델이_다르면_종료_코드_4이고_결과를_폐기한다(self):
        """turn_context 모델이 기대와 다르면 종료 코드 4를 반환하고 결과 파일을 남기지 않는다."""
        # Given
        config = {"turns": [{"model": "gpt-6-astra", "effort": "xhigh"}]}

        # When
        completed = self.run_runner("scout", config=config)

        # Then
        self.assertEqual(4, completed.returncode)
        self.assertFalse(self.result.exists())
        status = self.status(completed)
        self.assertEqual((False, 4), (status["verified"], status["exit"]))

    def test_rollout의_effort가_다르면_종료_코드_4이다(self):
        """turn_context effort가 xhigh가 아니면 종료 코드 4를 반환한다."""
        # Given
        config = {"turns": [{"model": "gpt-6-luna", "effort": "high"}]}

        # When
        completed = self.run_runner("scout", config=config)

        # Then
        self.assertEqual(4, completed.returncode)
        self.assertFalse(self.result.exists())

    def test_turn_context_하나라도_다르면_종료_코드_4이다(self):
        """여러 turn_context 중 하나만 달라도 종료 코드 4를 반환한다."""
        # Given
        good = {"model": "gpt-6-luna", "effort": "xhigh"}
        config = {"turns": [good, good, {"model": "gpt-6-luna"}]}

        # When
        completed = self.run_runner("scout", config=config)

        # Then
        self.assertEqual(4, completed.returncode)

    def test_모든_turn_context가_맞으면_여러_개여도_통과한다(self):
        """turn_context가 여러 개여도 모두 기대값이면 검증된다."""
        # Given
        good = {"model": "gpt-6-luna", "effort": "xhigh"}
        config = {"turns": [good, good, good]}

        # When
        completed = self.run_runner("scout", config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(3, self.status(completed)["evidence"]["turns"])

    def test_turn_context가_없으면_종료_코드_4이다(self):
        """rollout에 turn_context가 없으면 증거가 없어 종료 코드 4이다."""
        # Given
        config = {"turns": []}

        # When
        completed = self.run_runner("scout", config=config)

        # Then
        self.assertEqual(4, completed.returncode)
        self.assertFalse(self.result.exists())

    def test_rollout_파일이_없으면_종료_코드_4이다(self):
        """thread_id에 맞는 rollout 파일이 없으면 종료 코드 4이다."""
        # Given
        config = {"no_rollout": True}

        # When
        completed = self.run_runner("scout", config=config)

        # Then
        self.assertEqual(4, completed.returncode)
        self.assertFalse(self.result.exists())

    def test_thread_started_이벤트가_없으면_종료_코드_4이다(self):
        """표준 출력에 thread.started가 없으면 종료 코드 4이다."""
        # Given
        config = {"no_thread": True}

        # When
        completed = self.run_runner("scout", config=config)

        # Then
        self.assertEqual(4, completed.returncode)
        self.assertFalse(self.result.exists())

    def test_다른_스레드의_rollout은_증거로_쓰지_않는다(self):
        """thread_id가 다른 rollout 파일만 있으면 종료 코드 4이다."""
        # Given
        other = self.codex_home / "sessions" / "2026" / "10" / "12"
        other.mkdir(parents=True)
        (other / "rollout-2026-10-12T00-00-00-other-thread.jsonl").write_text(
            json.dumps({"type": "turn_context", "payload": {"model": "gpt-6-luna", "effort": "xhigh"}}) + "\n"
        )
        config = {"no_rollout": True}

        # When
        completed = self.run_runner("scout", config=config)

        # Then
        self.assertEqual(4, completed.returncode)

    def test_Claude의_modelUsage에_다른_모델이_있으면_종료_코드_4이고_결과를_쓰지_않는다(self):
        """modelUsage에 기대 모델 외의 키가 있으면 종료 코드 4이고 결과를 저장하지 않는다."""
        # Given
        config = {"usage": {"claude-opus-5-5": {}, "claude-haiku-5-5": {}}}

        # When
        completed = self.run_runner("reviewer", "--model", "claude-opus-5-5", config=config)

        # Then
        self.assertEqual(4, completed.returncode)
        self.assertFalse(self.result.exists())

    def test_Claude의_modelUsage가_다른_모델이면_종료_코드_4이다(self):
        """modelUsage가 기대 모델이 아닌 모델만 담으면 종료 코드 4이다."""
        # Given
        config = {"usage": {"claude-sonnet-5-5": {}}}

        # When
        completed = self.run_runner("reviewer", "--model", "claude-opus-5-5", config=config)

        # Then
        self.assertEqual(4, completed.returncode)

    def test_Claude_transcript의_모델이_다르면_종료_코드_4이다(self):
        """assistant 항목 하나라도 모델이 다르면 종료 코드 4이다."""
        # Given
        good = {"model": "claude-opus-5-5", "effort": "xhigh"}
        config = {"entries": [good, {"model": "claude-haiku-5-5", "effort": "xhigh"}]}

        # When
        completed = self.run_runner("reviewer", "--model", "claude-opus-5-5", config=config)

        # Then
        self.assertEqual(4, completed.returncode)
        self.assertFalse(self.result.exists())

    def test_Claude_transcript의_effort가_다르거나_없으면_종료_코드_4이다(self):
        """assistant 항목의 effort가 xhigh가 아니거나 없으면 종료 코드 4이다."""
        # Given
        wrong = {"entries": [{"model": "claude-opus-5-5", "effort": "high"}]}
        missing = {"entries": [{"model": "claude-opus-5-5"}]}

        # When
        outcomes = [
            self.run_runner("reviewer", "--model", "claude-opus-5-5", config=config).returncode
            for config in (wrong, missing)
        ]

        # Then
        self.assertEqual([4, 4], outcomes)

    def test_Claude_transcript가_없거나_assistant_항목이_없으면_종료_코드_4이다(self):
        """transcript 파일이 없거나 assistant 항목이 없으면 종료 코드 4이다."""
        # Given
        absent = {"no_transcript": True}
        empty = {"entries": []}

        # When
        outcomes = [
            self.run_runner("reviewer", "--model", "claude-opus-5-5", config=config).returncode
            for config in (absent, empty)
        ]

        # Then
        self.assertEqual([4, 4], outcomes)

    def test_Claude가_오류를_보고하면_종료_코드_3이다(self):
        """is_error가 true인 결과는 실행 불가로 보고 종료 코드 3이다."""
        # Given
        config = {"is_error": True, "message": "usage limit"}

        # When
        completed = self.run_runner("reviewer", "--model", "claude-opus-5-5", config=config)

        # Then
        self.assertEqual(3, completed.returncode)
        self.assertFalse(self.result.exists())

    def test_사용_오류는_종료_코드_2이다(self):
        """역할 규칙을 어긴 인자와 빠진 인자는 모두 종료 코드 2이고 자식을 실행하지 않는다."""
        # Given
        cases = [
            dict(arguments=["planner"]),
            dict(arguments=["scout", "--model", "gpt-6-luna"]),
            dict(arguments=["worker", "--model", "gpt-6-luna"]),
            dict(arguments=["reviewer", "--add-dir", str(self.base)]),
            dict(arguments=["scout", "--add-dir", str(self.base)]),
            dict(arguments=["reviewer", "--model", "gpt-5.4"]),
            dict(arguments=["reviewer", "--model", "opus"]),
            dict(arguments=["scout", "--timeout", "0"]),
            dict(arguments=["scout", "--timeout", "soon"]),
            dict(arguments=["scout", "--unknown"]),
            dict(arguments=["scout"], assignment=False),
            dict(arguments=["scout"], result=False),
            dict(arguments=[]),
        ]

        # When
        outcomes = []
        for case in cases:
            outcomes.append(
                self.run_runner(
                    *case["arguments"], assignment=case.get("assignment", True), result=case.get("result", True)
                ).returncode
            )

        # Then
        self.assertEqual([2] * len(cases), outcomes)
        self.assertFalse(self.log.exists())

    def test_할당_파일이_없으면_종료_코드_2이다(self):
        """존재하지 않는 할당 파일은 사용 오류이다."""
        # Given
        self.assignment.unlink()

        # When
        completed = self.run_runner("scout")

        # Then
        self.assertEqual(2, completed.returncode)
        self.assertEqual(2, self.status(completed)["exit"])

    def test_실행기가_없으면_종료_코드_3이다(self):
        """codex가 PATH에 없으면 종료 코드 3이다."""
        # Given
        empty = self.base / "empty"
        empty.mkdir()

        # When
        completed = self.run_runner("scout", path=str(empty))

        # Then
        self.assertEqual(3, completed.returncode)
        self.assertFalse(self.result.exists())
        self.assertFalse(self.status(completed)["verified"])

    def test_실행기가_0이_아닌_코드로_끝나면_종료_코드_3이고_결과를_폐기한다(self):
        """자식이 0이 아닌 코드로 끝나면 종료 코드 3이고 결과 파일을 남기지 않는다."""
        # Given
        config = {"exit": 7}

        # When
        completed = self.run_runner("scout", config=config)

        # Then
        self.assertEqual(3, completed.returncode)
        self.assertFalse(self.result.exists())
        self.assertIn("fake failure", completed.stderr)

    def test_시간_초과이면_자식을_끝내고_종료_코드_3이다(self):
        """제한 시간을 넘기면 자식 프로세스를 강제로 끝내고 종료 코드 3이다."""
        # Given
        config = {"sleep": 60}

        # When
        started = time.monotonic()
        completed = self.run_runner("scout", "--timeout", "1", config=config)
        elapsed = time.monotonic() - started

        # Then
        self.assertEqual(3, completed.returncode)
        self.assertLess(elapsed, 30)
        pid = self.logged()["pid"]
        alive = True
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                alive = False
                break
            time.sleep(0.1)
        self.assertFalse(alive)
        self.assertFalse(self.result.exists())

    def test_표준_출력의_마지막_줄은_상태_JSON_한_줄이다(self):
        """표준 출력 마지막 줄은 계약된 키를 모두 가진 JSON 한 줄이다."""
        # Given
        arguments = ["scout"]

        # When
        completed = self.run_runner(*arguments)

        # Then
        status = self.status(completed)
        self.assertEqual({"role", "runner", "model", "effort", "verified", "evidence", "exit"}, set(status))


if __name__ == "__main__":
    unittest.main()
