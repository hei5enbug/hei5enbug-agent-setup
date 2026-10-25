from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))
import role_runner  # noqa: E402
import session_context  # noqa: E402
from test_model_pins import PINS  # noqa: E402

RUNNER = REPO_ROOT / "scripts" / "role_runner.py"
THREAD = "019e0000-aaaa-bbbb-cccc-000000000001"
SESSION = "11111111-2222-3333-4444-555555555555"
SHELL_RULES = [
    "Bash(git diff:*)", "Bash(git show:*)", "Bash(git grep:*)", "Bash(git log:*)", "Bash(git cat-file:*)",
    "Bash(git ls-tree:*)", "Bash(git ls-files:*)", "Bash(git rev-parse:*)", "Bash(git merge-base:*)",
    "Bash(rg:*)", "Bash(ls:*)", "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)", "Bash(wc:*)",
]


def allowed_rules(argv: list[str]) -> list[str]:
    """Return the --allowedTools rules of a claude -p argument list."""
    start = argv.index("--allowedTools") + 1
    end = next((index for index in range(start, len(argv)) if argv[index].startswith("--")), len(argv))
    return argv[start:end]

FAKE_EXECUTABLE = '''#!{python}
import json, os, sys, time
from pathlib import Path

name = Path(sys.argv[0]).name
config = json.loads(os.environ.get("FAKE_CONFIG", "{{}}"))
is_server = name == "codex" and sys.argv[1:2] == ["app-server"]
stdin = "" if is_server else sys.stdin.read()
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({{
        "name": name, "argv": sys.argv[1:], "stdin": stdin, "cwd": os.getcwd(),
        "role": os.environ.get("HEI5ENBUG_ASSIGNED_ROLE"), "pid": os.getpid(),
        "parent": os.environ.get("HEI5ENBUG_PARENT_SESSION"), "started": time.time(),
    }}) + "\\n")


def guard_hook(cwd):
    command = config.get("hooks_command", 'sh "/abs/plugin/root/scripts/hook_python.sh" approval_guard.py')
    return {{
        "key": "plugin@market:hooks/hooks.json:pre_tool_use:1:0", "eventName": "preToolUse", "handlerType": "command",
        "command": command, "async": config.get("hooks_async", False),
        "matcher": config.get("hooks_matcher", "^(Bash|Read|Edit|Write)$"), "timeoutSec": 10, "source": "plugin",
        "pluginId": "plugin@market", "enabled": config.get("hooks_enabled", True),
        "isManaged": config.get("hooks_managed", False), "currentHash": "sha256:x",
        "trustStatus": config.get("hooks_trust", "trusted"),
    }}


def serve_hooks():
    """Answer initialize and hooks/list only after reading each request, like the real app-server."""
    if config.get("hooks_exit"):
        sys.exit(config["hooks_exit"])
    if config.get("hooks_sleep"):
        time.sleep(config["hooks_sleep"])
    for line in sys.stdin:
        request = json.loads(line)
        if request.get("method") == "initialize":
            print(json.dumps({{"id": request["id"], "result": {{"userAgent": "fake"}}}}), flush=True)
            print(json.dumps({{"method": "notice", "params": {{}}}}), flush=True)
        elif request.get("method") == "hooks/list":
            if config.get("hooks_not_json"):
                print("not json", flush=True)
                continue
            if config.get("hooks_bad_bytes"):
                sys.stdout.buffer.write(b"\\xff\\xfe\\n")
                sys.stdout.flush()
                continue
            if config.get("hooks_error"):
                print(json.dumps({{"id": request["id"], "error": {{"code": -32600, "message": "bad request"}}}}), flush=True)
                continue
            cwd = request["params"]["cwds"][0]
            hooks = [] if config.get("hooks_empty") else [guard_hook(cwd)]
            entries = [] if config.get("hooks_no_entry") else [{{"cwd": cwd, "warnings": [], "errors": [], "hooks": hooks}}]
            print(json.dumps({{"id": request["id"], "result": {{"data": entries}}}}), flush=True)
            return


if is_server:
    serve_hooks()
    sys.exit(0)


def touch_heartbeat(host, session_id):
    if config.get("no_heartbeat"):
        return
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    directory = Path(state) / "hei5enbug-agent-setup" / "heartbeats"
    directory.mkdir(parents=True, exist_ok=True)
    if not config.get("event_only"):
        (directory / (host + "-" + session_id)).touch()
    if not config.get("legacy_only"):
        event = config.get("heartbeat_event", "PreToolUse" if host == "codex" else "UserPromptSubmit")
        (directory / (host + "-" + session_id + "." + event)).touch()


if name == "codex" and sys.argv[1:3] == ["mcp", "list"]:
    if config.get("mcp_exit"):
        sys.stderr.write("fake mcp failure")
        sys.exit(config["mcp_exit"])
    print(config.get("mcp_list", json.dumps([{{"name": "aside", "enabled": True}}, {{"name": "datadog", "enabled": True}}])))
    sys.exit(0)
for needle, code in config.get("exit_when", {{}}).items():
    if needle in stdin:
        sys.stderr.write("fake failure")
        sys.exit(code)
if config.get("sleep"):
    time.sleep(config["sleep"])
if config.get("exit"):
    sys.stderr.write("fake failure")
    sys.exit(config["exit"])
if name == "codex":
    argv = sys.argv[1:]
    sandbox = argv[argv.index("-s") + 1] if "-s" in argv else next(
        (item.split("=", 1)[1].strip('"') for item in argv if item.startswith("sandbox_mode=")), None)
    if "-o" in argv and not any(needle in stdin for needle in config.get("no_answer_when", [])):
        Path(argv[argv.index("-o") + 1]).write_text(config.get("message", "codex answer"))
    if not config.get("no_thread"):
        print(json.dumps({{"type": "thread.started", "thread_id": config.get("thread", "{thread}")}}))
        touch_heartbeat("codex", config.get("thread", "{thread}"))
    print(json.dumps({{"type": "turn.completed"}}))
    if not config.get("no_rollout"):
        home = Path(os.environ["CODEX_HOME"]) / "sessions" / "2026" / "10" / "12"
        home.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps({{"type": "session_meta", "payload": {{"id": "x"}}}})]
        if not config.get("no_tool_calls"):
            lines.append(json.dumps({{"type": "response_item", "payload": {{"type": "function_call", "name": "exec"}}}}))
        lines.append(json.dumps({{"type": "response_item", "payload": {{"type": "web_search_call"}}}}))
        for turn in config.get("turns", [{{"model": "gpt-5.6-luna", "effort": "high"}}]):
            turn = dict(turn)
            turn.setdefault("sandbox_policy", {{"type": sandbox}})
            lines.append(json.dumps({{"type": "turn_context", "payload": turn}}))
        (home / "rollout-2026-10-12T00-00-00-{thread}.jsonl").write_text("\\n".join(lines) + "\\n")
else:
    model = config.get("model", "claude-opus-5-5")
    touch_heartbeat("claude", "{session}")
    print(json.dumps({{
        "type": "result", "is_error": config.get("is_error", False), "result": config.get("message", "claude answer"),
        "session_id": "{session}", "modelUsage": config.get("usage", {{model: {{}}}}),
    }}))
    if not config.get("no_transcript"):
        home = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / "-some-project"
        home.mkdir(parents=True, exist_ok=True)
        lines = []
        for entry in config.get("entries", [{{"model": model, "effort": "high"}}]):
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
        self.instructions = self.base / "instructions.md"
        self.instructions.write_text("Answer with the evidence.\nINSTRUCTION LINE\n")
        self.log = self.base / "log.json"
        self.codex_home = self.base / "codex-home"
        self.claude_home = self.base / "claude-home"
        self.state_home = self.base / "state"

    def run_runner(self, *arguments, config=None, path=None, assignment=True, result=True, extra_env=None):
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
            "XDG_STATE_HOME": str(self.state_home),
            "FAKE_LOG": str(self.log),
            "FAKE_CONFIG": json.dumps(config or {}),
        }
        env.update(extra_env or {})
        env = {key: value for key, value in env.items() if value is not None}
        return subprocess.run(command, cwd=self.workspace, env=env, capture_output=True, text=True, timeout=60)

    def beat(self, host, session_id):
        """Plant the heartbeat the approval guard leaves for an earlier session."""
        heartbeat = self.state_home / "hei5enbug-agent-setup" / "heartbeats" / f"{host}-{session_id}"
        heartbeat.parent.mkdir(parents=True, exist_ok=True)
        heartbeat.touch()
        event = "PreToolUse" if host == "codex" else "UserPromptSubmit"
        heartbeat.with_name(heartbeat.name + "." + event).touch()

    def calls(self):
        """Every logged child call in order, including the MCP listing and the hook readiness call."""
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def logged(self):
        """The last child call: the assignment run, or the failing call when an earlier step stopped the runner."""
        return self.calls()[-1]

    def executions(self):
        """The logged exec calls, without the MCP listing and the app-server readiness calls."""
        return [call for call in self.calls() if call["argv"][:2] != ["mcp", "list"] and call["argv"][:1] != ["app-server"]]

    def app_server_calls(self):
        """The logged hook readiness calls to codex app-server."""
        return [call for call in self.calls() if call["argv"][:1] == ["app-server"]]

    def status(self, completed):
        return json.loads(completed.stdout.strip().splitlines()[-1])

    def codex_argv(self, *, search=False, sandbox="read-only", model="gpt-5.6-luna", effort="high", add_dirs=(), mcp_off=True, output=None):
        """The assignment run of a Codex child: the scoped exec resume of the preflight thread when it writes, else one fresh exec."""
        if sandbox == "workspace-write":
            return self.codex_resume_argv(
                search=search, sandbox=sandbox, model=model, effort=effort, roots=add_dirs, mcp_off=mcp_off, output=output,
            )
        return self.codex_start_argv(
            search=search, sandbox=sandbox, model=model, effort=effort, add_dirs=add_dirs, mcp_off=mcp_off, output=output,
        )

    def codex_start_argv(self, *, search=False, sandbox="read-only", model="gpt-5.6-luna", effort="high", add_dirs=(), mcp_off=True, output=None):
        """The fresh exec of a Codex child: the assignment of a read-only run, or the hook preflight of a writing run."""
        argv = ["--search"] if search else []
        argv += ["exec", "-m", model, "-c", f'model_reasoning_effort="{effort}"', "-s", sandbox, "-C", str(self.workspace)]
        argv += self.mcp_off_flags(mcp_off)
        argv += self.skills_off_flags(sandbox)
        for directory in add_dirs:
            argv += ["--add-dir", directory]
        return argv + ["--json", "-o", str(output or self.result), "-"]

    def mcp_off_flags(self, names=True):
        """The overrides for the fake's listed servers (True), the given names, or none (False)."""
        names = ("aside", "datadog") if names is True else (names or ())
        return [item for name in names for item in ("-c", f"mcp_servers.{name}.enabled=false")]

    def skills_off_flags(self, sandbox):
        """The override that drops the host skill catalog, which only a read-only Codex run sends."""
        return ["-c", "skills.max_context_tokens=1"] if sandbox == "read-only" else []

    def codex_resume_argv(self, *, search=False, sandbox="read-only", model="gpt-5.6-luna", effort="high", roots=(), mcp_off=True, output=None, thread=THREAD):
        argv = ["--search"] if search else []
        argv += ["exec", "resume", thread, "-m", model, "-c", f'model_reasoning_effort="{effort}"', "-c", f'sandbox_mode="{sandbox}"']
        argv += self.mcp_off_flags(mcp_off)
        argv += self.skills_off_flags(sandbox)
        if roots:
            argv += ["-c", f"sandbox_workspace_write.writable_roots={json.dumps([str(Path(root).resolve()) for root in roots])}"]
        return argv + ["--json", "-o", str(output or self.result), "-"]

    def claude_argv(self, *, model="claude-opus-5-5", effort="high", writing=False, resume=None, add_dirs=()):
        """A capability run on Claude: the read set and the read-only shell, plus edits in approved directories when it writes."""
        tools = ["Read", "Grep", "Glob", "Bash", *(["Edit", "Write"] if writing else [])]
        rules = [f"Edit(/{directory}/**)" for directory in add_dirs]
        allowed = ["Read", "Grep", "Glob", *SHELL_RULES, *(rules if writing else []), *(["Bash"] if writing else [])]
        argv = ["-p"]
        if resume is not None:
            argv += ["--resume", resume]
        argv += ["--model", model, "--effort", effort, "--output-format", "json"]
        argv += [] if writing else ["--disable-slash-commands"]
        argv += ["--tools", *tools, "--strict-mcp-config", "--permission-mode", "dontAsk", "--allowedTools", *allowed]
        for directory in add_dirs:
            argv += ["--add-dir", directory]
        return argv

    def claude_agent_argv(self, *, model="claude-sonnet-5-5", effort="high", writing=False, web=(), mcp=False, add_dirs=()):
        """An agent run on Claude: the read set, the shell list, web tools its definition lists, edits when it writes, and bare Bash with MCP."""
        tools = ["Read", "Grep", "Glob", "Bash", *web, *(["Edit", "Write"] if writing else [])]
        allowed = ["Read", "Grep", "Glob", *SHELL_RULES, *web]
        if writing:
            allowed += [f"Edit(/{d}/**)" for d in add_dirs]
        if writing or mcp:
            allowed += ["Bash"]
        if mcp:
            allowed += ["mcp__*"]
        argv = ["-p", "--model", model, "--effort", effort, "--output-format", "json"]
        argv += [] if writing else ["--disable-slash-commands"]
        argv += ["--tools", *tools]
        if not mcp:
            argv.append("--strict-mcp-config")
        argv += ["--permission-mode", "dontAsk", "--allowedTools", *allowed]
        for directory in add_dirs:
            argv += ["--add-dir", directory]
        return argv

    def write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def write_declaration(self, path: Path, agents: dict) -> None:
        self.write(path, json.dumps({"version": 1, "agents": agents}))

    def use_declared_claude_plugin(self, agents: dict) -> Path:
        """Install a Claude plugin example-plugin whose model-roles.json declares agents and whose scout definition is planted."""
        install = self.base / "example-plugin"
        self.write_declaration(install / ".claude-plugin" / "model-roles.json", agents)
        self.write(install / "agents" / "scout.md", "---\nname: scout\ntools: Read, Grep\n---\n\nDECLARED BODY\n")
        installed = {"version": 2, "plugins": {"example-plugin@market": [{"scope": "user", "installPath": str(install)}]}}
        self.write(self.claude_home / "plugins" / "installed_plugins.json", json.dumps(installed))
        return install

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
            {"role": "scout", "runner": "codex", "model": "gpt-5.6-luna", "effort": "high", "verified": True, "exit": 0},
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
        config = {"turns": [{"model": "gpt-6-astra", "effort": "high"}]}

        # When
        completed = self.run_runner("reviewer", config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.codex_argv(model="gpt-6-astra"), self.logged()["argv"])
        self.assertEqual("gpt-6-astra", self.status(completed)["model"])

    def test_reviewer는_GPT_모델을_지정하면_scout와_같은_방식으로_실행된다(self):
        """reviewer에 GPT 모델 ID를 주면 그 모델로 읽기 전용 codex exec를 실행한다."""
        # Given
        config = {"turns": [{"model": "gpt-6.1-sol", "effort": "high"}]}

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
                "-p", "--model", "claude-opus-5-5", "--effort", "high", "--output-format", "json", "--disable-slash-commands",
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
            (["reviewer"], {"turns": [{"model": "gpt-6-astra", "effort": "high"}]}),
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
            sandboxes = [argv[index + 1] for index, item in enumerate(argv) if item == "-s"]
            self.assertTrue(all(value in ("read-only", "workspace-write") for value in sandboxes), sandboxes)
            configs = [argv[index + 1] for index, item in enumerate(argv) if item in ("-c", "--config")]
            allowed = (
                "model_reasoning_effort=", "sandbox_mode=", "mcp_servers.", "sandbox_workspace_write.writable_roots=",
                "skills.max_context_tokens=",
            )
            self.assertTrue(all(item.startswith(allowed) for item in configs), configs)
            self.assertTrue(all("workspace-write" in item or "read-only" in item for item in configs if item.startswith("sandbox_mode=")))

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
            definition = role_runner.ROLE_DEFINITIONS.get(role, role)
            body = (REPO_ROOT / "agents" / f"{definition}.md").read_text().split("---", 2)[2].strip()
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
        config = {"turns": [{"model": "gpt-6-astra", "effort": "high"}]}

        # When
        completed = self.run_runner("scout", config=config)

        # Then
        self.assertEqual(4, completed.returncode)
        self.assertFalse(self.result.exists())
        status = self.status(completed)
        self.assertEqual((False, 4), (status["verified"], status["exit"]))

    def test_rollout의_effort가_다르면_종료_코드_4이다(self):
        """turn_context effort가 high가 아니면 종료 코드 4를 반환한다."""
        # Given
        config = {"turns": [{"model": "gpt-5.6-luna", "effort": "xhigh"}]}

        # When
        completed = self.run_runner("scout", config=config)

        # Then
        self.assertEqual(4, completed.returncode)
        self.assertFalse(self.result.exists())

    def test_turn_context_하나라도_다르면_종료_코드_4이다(self):
        """여러 turn_context 중 하나만 달라도 종료 코드 4를 반환한다."""
        # Given
        good = {"model": "gpt-5.6-luna", "effort": "high"}
        config = {"turns": [good, good, {"model": "gpt-5.6-luna"}]}

        # When
        completed = self.run_runner("scout", config=config)

        # Then
        self.assertEqual(4, completed.returncode)

    def test_모든_turn_context가_맞으면_여러_개여도_통과한다(self):
        """turn_context가 여러 개여도 모두 기대값이면 검증된다."""
        # Given
        good = {"model": "gpt-5.6-luna", "effort": "high"}
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
            json.dumps({"type": "turn_context", "payload": {"model": "gpt-5.6-luna", "effort": "high"}}) + "\n"
        )
        config = {"no_rollout": True}

        # When
        completed = self.run_runner("scout", config=config)

        # Then
        self.assertEqual(4, completed.returncode)

    def test_turn_context의_sandbox가_요청과_다르면_종료_코드_4이고_결과를_폐기한다(self):
        """scout은 read-only로 실행하므로 turn_context가 workspace-write이면 종료 코드 4이고 결과를 남기지 않는다."""
        # Given
        config = {"turns": [{"model": "gpt-5.6-luna", "effort": "high", "sandbox_policy": {"type": "workspace-write"}}]}

        # When
        completed = self.run_runner("scout", config=config)

        # Then
        self.assertEqual(4, completed.returncode)
        self.assertFalse(self.result.exists())

    def test_turn_context에_sandbox_정보가_없으면_종료_코드_4이다(self):
        """sandbox_policy가 null이거나 type이 없으면 요청한 sandbox를 확인할 수 없어 종료 코드 4이다."""
        cases = [
            {"model": "gpt-5.6-luna", "effort": "high", "sandbox_policy": None},
            {"model": "gpt-5.6-luna", "effort": "high", "sandbox_policy": {}},
        ]
        for turn in cases:
            with self.subTest(turn=turn):
                # Given
                config = {"turns": [turn]}

                # When
                completed = self.run_runner("scout", config=config)

                # Then
                self.assertEqual(4, completed.returncode)
                self.assertFalse(self.result.exists())

    def test_쓰기_역할의_turn_context는_workspace_write이면_통과한다(self):
        """worker는 workspace-write로 실행하므로 그 sandbox를 가진 turn_context는 검증을 통과한다."""
        # Given
        config = {"turns": [{"model": "gpt-5.6-luna", "effort": "high", "sandbox_policy": {"type": "workspace-write"}}]}

        # When
        completed = self.run_runner("worker", config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        argv = self.logged()["argv"]
        self.assertIn('sandbox_mode="workspace-write"', argv)

    def test_codex_resume은_resume_하위_명령과_sandbox_설정으로_실행하고_세션을_evidence에_남긴다(self):
        """scout을 --resume으로 이으면 codex exec resume에 -c sandbox_mode와 모델·effort 설정을 넘기고 thread를 evidence에 남긴다."""
        self.beat("codex", THREAD)

        # When
        completed = self.run_runner("scout", "--resume", THREAD)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.codex_resume_argv(), self.logged()["argv"])
        self.assertEqual(THREAD, self.status(completed)["evidence"]["session"])

    def test_codex_resume의_researcher는_최상위_search_플래그를_유지한다(self):
        """researcher를 --resume으로 이어도 --search는 exec resume 앞에 그대로 붙는다."""
        self.beat("codex", THREAD)

        # When
        completed = self.run_runner("researcher", "--resume", THREAD)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.codex_resume_argv(search=True), self.logged()["argv"])

    def test_codex_resume의_쓰기_역할은_승인된_add_dir을_writable_roots로_넘긴다(self):
        """worker를 --resume으로 이을 때 승인된 디렉터리는 sandbox_workspace_write.writable_roots로 넘기고 --add-dir은 넘기지 않는다."""
        # Given
        directory = self.base / "shared"
        directory.mkdir()
        self.beat("codex", THREAD)

        # When
        completed = self.run_runner("worker", "--resume", THREAD, "--add-dir", str(directory))

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.codex_resume_argv(sandbox="workspace-write", roots=[directory]), self.logged()["argv"])
        self.assertNotIn("--add-dir", self.logged()["argv"])

    def test_codex_resume에서도_turn_context의_sandbox가_다르면_종료_코드_4이다(self):
        """resume한 실행의 turn_context sandbox가 요청과 다르면 종료 코드 4이고 결과를 남기지 않는다."""
        # Given
        config = {"turns": [{"model": "gpt-5.6-luna", "effort": "high", "sandbox_policy": {"type": "workspace-write"}}]}
        self.beat("codex", THREAD)

        # When
        completed = self.run_runner("scout", "--resume", THREAD, config=config)

        # Then
        self.assertEqual(4, completed.returncode)
        self.assertFalse(self.result.exists())

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
        good = {"model": "claude-opus-5-5", "effort": "high"}
        config = {"entries": [good, {"model": "claude-haiku-5-5", "effort": "high"}]}

        # When
        completed = self.run_runner("reviewer", "--model", "claude-opus-5-5", config=config)

        # Then
        self.assertEqual(4, completed.returncode)
        self.assertFalse(self.result.exists())

    def test_Claude_transcript의_effort가_다르거나_없으면_종료_코드_4이다(self):
        """assistant 항목의 effort가 high가 아니거나 없으면 종료 코드 4이다."""
        # Given
        wrong = {"entries": [{"model": "claude-opus-5-5", "effort": "xhigh"}]}
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

    def test_답변이_없으면_검증된_기록만으로_성공하지_않는다(self):
        """모델 기록이 맞아도 답변이 없거나 공백뿐이면 검증 실패로 처리한다."""
        for arguments, message in (
            (["scout"], ""),
            (["scout"], " \n"),
            (["reviewer", "--model", "claude-opus-5-5"], None),
            (["reviewer", "--model", "claude-opus-5-5"], ""),
            (["reviewer", "--model", "claude-opus-5-5"], " \n"),
        ):
            with self.subTest(arguments=arguments, message=message):
                # Given
                config = {"message": message}

                # When
                completed = self.run_runner(*arguments, config=config)

                # Then
                self.assertEqual(4, completed.returncode)
                self.assertFalse(self.status(completed)["verified"])
                self.assertFalse(self.result.exists())

    def test_결과_경로가_할당_파일이면_실행하지_않고_원본을_보존한다(self):
        """결과 경로가 할당 파일 자체나 그 심볼릭 링크이면 사용 오류로 거부한다."""
        for alias in (False, True):
            with self.subTest(alias=alias):
                # Given
                original = self.assignment.read_text()
                result = self.assignment
                if alias:
                    result = self.base / "assignment-link.md"
                    result.symlink_to(self.assignment)

                # When
                completed = self.run_runner("scout", "--result", str(result), result=False)

                # Then
                self.assertEqual(2, completed.returncode)
                self.assertEqual(original, self.assignment.read_text())
                self.assertFalse(self.log.exists())

    def test_결과_경로가_디렉터리이면_상태_JSON으로_사용_오류를_알린다(self):
        """결과 파일 대신 디렉터리를 지정하면 자식 실행 전에 종료 코드 2를 반환한다."""
        # Given
        self.result.mkdir()

        # When
        completed = self.run_runner("scout")

        # Then
        self.assertEqual(2, completed.returncode)
        self.assertEqual(2, self.status(completed)["exit"])
        self.assertTrue(self.result.is_dir())
        self.assertFalse(self.log.exists())

    def test_사용_오류는_종료_코드_2이다(self):
        """역할 규칙을 어긴 인자와 빠진 인자는 모두 종료 코드 2이고 자식을 실행하지 않는다."""
        # Given
        cases = [
            dict(arguments=["planner"]),
            dict(arguments=["scout", "--model", "gpt-5.6-luna"]),
            dict(arguments=["worker", "--model", "gpt-5.6-luna"]),
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
        self.assertEqual(
            {"role", "capability", "agent", "fallback", "runner", "model", "effort", "verified", "evidence", "exit"},
            set(status),
        )
        self.assertEqual((None, False), (status["capability"], status["fallback"]))

    def test_capability는_host에_맞는_entry를_고르고_읽기_전용_codex_인자로_실행한다(self):
        """investigation을 Claude 호스트에서 실행하면 Luna high를 읽기 전용 codex exec로 실행한다."""
        # Given
        arguments = ["investigation", "--host", "claude", "--instructions", str(self.instructions)]

        # When
        completed = self.run_runner(*arguments)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.codex_argv(), self.logged()["argv"])
        status = self.status(completed)
        self.assertEqual(
            ("investigation", None, False, "codex", "gpt-5.6-luna", "high", True),
            (
                status["capability"], status["role"], status["fallback"], status["runner"], status["model"],
                status["effort"], status["verified"],
            ),
        )
        self.assertIn("You are an assigned worker for the investigation capability", self.logged()["stdin"])

    def test_capability는_host에_맞는_entry를_고르고_읽기_전용_claude_인자로_실행한다(self):
        """review를 Codex 호스트에서 실행하면 Opus high를 읽기 전용 claude -p로 실행하고 effort를 entry 값으로 검증한다."""
        # Given
        config = {"entries": [{"model": "claude-opus-5-5", "effort": "high"}]}
        arguments = ["review", "--host", "codex", "--instructions", str(self.instructions)]

        # When
        completed = self.run_runner(*arguments, config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.claude_argv(effort="high"), self.logged()["argv"])
        status = self.status(completed)
        self.assertEqual(("claude", "claude-opus-5-5", "high"), (status["runner"], status["model"], status["effort"]))

    def test_쓰기_capability의_codex_실행은_workspace_write와_entry_effort를_쓴다(self):
        """language를 Claude 호스트에서 실행하면 Sol high를 workspace-write codex exec로 실행한다."""
        # Given
        config = {"turns": [{"model": "gpt-6.1-sol", "effort": "high"}]}
        arguments = ["language", "--host", "claude", "--instructions", str(self.instructions)]

        # When
        completed = self.run_runner(*arguments, config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(
            self.codex_argv(model="gpt-6.1-sol", effort="high", sandbox="workspace-write"),
            self.logged()["argv"],
        )

    def test_쓰기_capability의_claude_실행은_승인된_add_dir의_편집_규칙과_dontAsk를_쓴다(self):
        """design을 Codex 호스트의 fallback으로 실행하면 Opus high를 dontAsk로 실행하고 편집 허용은 승인된 디렉터리 규칙만 쓴다."""
        # Given
        directory = str(self.base / "approved")
        arguments = ["design", "--host", "codex", "--fallback", "--add-dir", directory, "--instructions", str(self.instructions)]

        # When
        completed = self.run_runner(*arguments)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.claude_argv(writing=True, add_dirs=[directory]), self.logged()["argv"])

    def test_Claude_쓰기_capability는_add_dir_없이는_실행하지_않고_종료_코드_2이다(self):
        """design의 Codex 호스트 fallback인 Claude 경로는 편집할 디렉터리 --add-dir이 없으면 자식을 띄우지 않고 종료 코드 2이다."""
        # Given
        arguments = ["design", "--host", "codex", "--fallback", "--instructions", str(self.instructions)]

        # When
        completed = self.run_runner(*arguments)

        # Then
        self.assertEqual(2, completed.returncode, completed.stderr)
        self.assertIn("--add-dir", completed.stderr)
        self.assertFalse(self.log.exists())

    def test_capability의_add_dir은_두_호스트_명령에_모두_넘어간다(self):
        """쓰기 capability의 --add-dir은 claude --add-dir와 codex --add-dir로 각각 전달된다."""
        directory = str(self.base / "one")
        cases = [
            (
                ["design", "--host", "codex", "--fallback"], None,
                self.claude_argv(writing=True, add_dirs=[directory]),
            ),
            (
                ["language", "--host", "claude"], {"turns": [{"model": "gpt-6.1-sol", "effort": "high"}]},
                self.codex_argv(
                    model="gpt-6.1-sol", effort="high", sandbox="workspace-write", add_dirs=[directory],
                ),
            ),
        ]
        for target, config, expected in cases:
            with self.subTest(target=target):
                # Given
                arguments = [*target, "--add-dir", directory, "--instructions", str(self.instructions)]

                # When
                completed = self.run_runner(*arguments, config=config)

                # Then
                self.assertEqual(0, completed.returncode, completed.stderr)
                self.assertEqual(expected, self.logged()["argv"])

    def test_fallback은_capability의_fallback_entry를_고른다(self):
        """design의 Claude 호스트 fallback은 Astra high를 workspace-write codex exec로 실행하고 fallback을 true로 보고한다."""
        # Given
        config = {"turns": [{"model": "gpt-6-astra", "effort": "high"}]}
        arguments = ["design", "--host", "claude", "--fallback", "--instructions", str(self.instructions)]

        # When
        completed = self.run_runner(*arguments, config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(
            self.codex_argv(model="gpt-6-astra", sandbox="workspace-write"), self.logged()["argv"],
        )
        status = self.status(completed)
        self.assertEqual((True, "design", "gpt-6-astra"), (status["fallback"], status["capability"], status["model"]))

    def test_via가_agent인_entry는_실행하지_않고_종료_코드_2이다(self):
        """primary entry가 via agent이면 실행기는 자식을 띄우지 않고 via 값을 알리며 종료 코드 2를 반환한다."""
        cases = [["implementation", "--host", "claude"], ["design", "--host", "codex"]]
        for target in cases:
            with self.subTest(target=target):
                # Given
                arguments = [*target, "--instructions", str(self.instructions)]

                # When
                completed = self.run_runner(*arguments)

                # Then
                self.assertEqual(2, completed.returncode)
                self.assertIn("via 'agent'", completed.stderr)
                self.assertEqual(2, self.status(completed)["exit"])
                self.assertFalse(self.log.exists())

    def test_agent는_fallback_없이는_실행하지_않고_종료_코드_2이다(self):
        """agent 모드는 --fallback이 없으면 자식을 띄우지 않고 종료 코드 2이다."""
        # Given
        arguments = ["agent", "--name", "hei5enbug-agent-setup:scout"]

        # When
        completed = self.run_runner(*arguments)

        # Then
        self.assertEqual(2, completed.returncode)
        self.assertIn("--fallback", completed.stderr)
        self.assertFalse(self.log.exists())

    def test_agent는_Claude_레지스트리_정의의_본문으로_gpt_대체를_읽기_전용_codex_exec로_실행한다(self):
        """Claude 호스트의 scout 에이전트 대체는 frontmatter를 뺀 정의 본문과 Assigned workers 절을 담고, 웹 도구를 나열해 --search를 붙인다."""
        # Given
        arguments = ["agent", "--name", "hei5enbug-agent-setup:scout", "--fallback"]
        config = {"turns": [{"model": "gpt-5.6-luna", "effort": "high"}]}

        # When
        completed = self.run_runner(*arguments, config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.codex_argv(search=True), self.logged()["argv"])
        prompt = self.logged()["stdin"]
        body = (REPO_ROOT / "agents" / "scout.md").read_text(encoding="utf-8").split("---", 2)[2].strip()
        self.assertTrue(prompt.startswith(role_runner.ROLE_SENTENCES["worker"]))
        self.assertIn(body, prompt)
        self.assertIn("## Assigned workers", prompt)
        self.assertTrue(prompt.endswith("## Assignment\n\nFind the answer.\nSECOND LINE\n"))
        status = self.status(completed)
        self.assertEqual(
            ("hei5enbug-agent-setup:scout", True, "codex", "gpt-5.6-luna", "high"),
            (status["agent"], status["fallback"], status["runner"], status["model"], status["effort"]),
        )

    def test_agent는_쓰기_에이전트의_gpt_대체에_승인된_add_dir과_workspace_write를_넘긴다(self):
        """sonnet-worker의 gpt 대체는 workspace-write codex exec에 승인된 add-dir만 넘기고 MCP 설정을 끈다."""
        # Given
        directory = str(self.base / "approved")
        arguments = ["agent", "--name", "hei5enbug-agent-setup:sonnet-worker", "--fallback", "--add-dir", directory]
        config = {"turns": [{"model": "gpt-6.1-sol", "effort": "high"}]}

        # When
        completed = self.run_runner(*arguments, config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(
            self.codex_argv(model="gpt-6.1-sol", sandbox="workspace-write", add_dirs=[directory]), self.logged()["argv"],
        )

    def test_agent의_쓰기_에이전트는_add_dir이_없으면_자식을_띄우지_않고_종료_코드_2이다(self):
        """쓰기 접근 에이전트는 편집할 디렉터리 --add-dir이 없으면 자식을 띄우지 않고 종료 코드 2이다."""
        # Given
        arguments = ["agent", "--name", "hei5enbug-agent-setup:sonnet-worker", "--fallback"]

        # When
        completed = self.run_runner(*arguments)

        # Then
        self.assertEqual(2, completed.returncode)
        self.assertIn("--add-dir", completed.stderr)
        self.assertFalse(self.log.exists())

    def test_agent는_Codex_쓰기_정의의_Claude_대체를_승인된_디렉터리_규칙으로_claude_p에_넘긴다(self):
        """Codex 호스트의 worker 에이전트 대체는 Sonnet high를 dontAsk로 실행하고, 편집은 승인된 디렉터리 규칙만 쓰며, Codex 역할 TOML의 지침을 담는다."""
        # Given
        self.write(self.codex_home / "agents" / "worker.toml", 'name = "worker"\ndeveloper_instructions = """\nCODEX WORKER BODY\n"""\n')
        directory = str(self.base / "approved")
        arguments = ["agent", "--name", "worker", "--host", "codex", "--fallback", "--add-dir", directory]
        config = {"model": "claude-sonnet-5-5", "entries": [{"model": "claude-sonnet-5-5", "effort": "high"}]}

        # When
        completed = self.run_runner(*arguments, config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.claude_agent_argv(writing=True, add_dirs=[directory]), self.logged()["argv"])
        prompt = self.logged()["stdin"]
        self.assertIn("CODEX WORKER BODY", prompt)
        self.assertIn("## Assigned workers", prompt)
        status = self.status(completed)
        self.assertEqual(("claude", "claude-sonnet-5-5", "high"), (status["runner"], status["model"], status["effort"]))

    def test_agent의_mcp_옵션은_Claude에서_strict_MCP를_빼고_mcp_규칙을_허용한다(self):
        """--mcp를 주면 쓰기 에이전트의 claude -p는 --strict-mcp-config를 빼고 mcp__* 규칙을 허용 목록 끝에 붙인다."""
        # Given
        directory = str(self.base / "approved")
        arguments = ["agent", "--name", "worker", "--host", "codex", "--fallback", "--add-dir", directory, "--mcp"]
        config = {"model": "claude-sonnet-5-5", "entries": [{"model": "claude-sonnet-5-5", "effort": "high"}]}

        # When
        completed = self.run_runner(*arguments, config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.claude_agent_argv(writing=True, add_dirs=[directory], mcp=True), self.logged()["argv"])

    def test_agent의_mcp_옵션은_Codex에서_MCP_설정을_남기고_쓰기면_네트워크를_켠다(self):
        """--mcp를 주면 쓰기 에이전트의 codex exec는 사용자의 MCP 설정을 남기고 network_access를 켠다."""
        # Given
        directory = str(self.base / "approved")
        arguments = ["agent", "--name", "hei5enbug-agent-setup:sonnet-worker", "--fallback", "--add-dir", directory, "--mcp"]
        config = {"turns": [{"model": "gpt-6.1-sol", "effort": "high"}]}

        # When
        completed = self.run_runner(*arguments, config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        expected = [
            "exec", "resume", THREAD, "-m", "gpt-6.1-sol", "-c", 'model_reasoning_effort="high"',
            "-c", 'sandbox_mode="workspace-write"', "-c", "sandbox_workspace_write.network_access=true",
            "-c", f"sandbox_workspace_write.writable_roots={json.dumps([directory])}",
            "--json", "-o", str(self.result), "-",
        ]
        self.assertEqual(expected, self.logged()["argv"])
        self.assertNotIn(["mcp", "list", "--json"], [call["argv"] for call in self.calls()])

    def test_agent는_정의가_웹_도구를_나열하면_그_도구만_Claude_대체에_넘긴다(self):
        """Codex 호스트의 scout 대체는 scout 정의가 나열한 WebSearch와 WebFetch를 Claude 읽기 도구에 더한다."""
        # Given
        arguments = ["agent", "--name", "scout", "--host", "codex", "--fallback"]
        config = {"model": "claude-sonnet-5-5", "entries": [{"model": "claude-sonnet-5-5", "effort": "medium"}]}

        # When
        completed = self.run_runner(*arguments, config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(
            self.claude_agent_argv(model="claude-sonnet-5-5", effort="medium", web=("WebSearch", "WebFetch")),
            self.logged()["argv"],
        )

    def test_agent의_resume은_같은_MCP_설정을_exec_resume에_넘긴다(self):
        """scout 에이전트를 --resume으로 이어도 exec resume에 mcp_servers 끄기 설정과 --search를 유지한다."""
        # Given
        arguments = ["agent", "--name", "hei5enbug-agent-setup:scout", "--fallback", "--resume", THREAD]
        config = {"turns": [{"model": "gpt-5.6-luna", "effort": "high"}]}
        self.beat("codex", THREAD)

        # When
        completed = self.run_runner(*arguments, config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.codex_resume_argv(search=True), self.logged()["argv"])

    def test_agent는_선언된_Claude_역할을_설치_경로의_정의와_선언된_대체로_실행한다(self):
        """설치된 Claude 플러그인이 선언한 역할은 설치 경로의 정의 본문을 쓰고 선언된 대체를 codex exec로 실행하며, access가 없으면 읽기로 본다."""
        # Given
        self.use_declared_claude_plugin({
            "example-plugin:scout": {
                "model": "claude-sonnet-5-5", "effort": "medium",
                "fallback": {"model": "gpt-5.6-luna", "effort": "high"},
            },
        })
        arguments = ["agent", "--name", "example-plugin:scout", "--fallback"]
        config = {"turns": [{"model": "gpt-5.6-luna", "effort": "high"}]}

        # When
        completed = self.run_runner(*arguments, config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.codex_argv(), self.logged()["argv"])
        self.assertIn("DECLARED BODY", self.logged()["stdin"])
        self.assertEqual("example-plugin:scout", self.status(completed)["agent"])

    def test_agent는_선언된_Codex_역할을_캐시의_최신_선언과_CODEX_HOME의_정의로_실행한다(self):
        """Codex 캐시가 선언한 역할은 CODEX_HOME의 role TOML 지침을 쓰고, 선언된 Claude 대체를 claude -p로 실행한다."""
        # Given
        self.write(
            self.codex_home / "plugins/cache/market/example/1.0.0/.codex-plugin/model-roles.json",
            json.dumps({"version": 1, "agents": {"example_worker": {
                "model": "gpt-5.6-luna", "effort": "xhigh",
                "fallback": {"model": "claude-sonnet-5-5", "effort": "medium"},
            }}}),
        )
        self.write(self.codex_home / "agents" / "example_worker.toml", 'name = "example_worker"\ndeveloper_instructions = """\nCODEX DECLARED BODY\n"""\n')
        arguments = ["agent", "--name", "example_worker", "--host", "codex", "--fallback"]
        config = {"model": "claude-sonnet-5-5", "entries": [{"model": "claude-sonnet-5-5", "effort": "medium"}]}

        # When
        completed = self.run_runner(*arguments, config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.claude_agent_argv(model="claude-sonnet-5-5", effort="medium"), self.logged()["argv"])
        self.assertIn("CODEX DECLARED BODY", self.logged()["stdin"])

    def test_agent는_알_수_없는_이름이면_종료_코드_2이다(self):
        """레지스트리와 설치된 선언 어디에도 없는 이름이나 호스트에 맞지 않는 이름은 자식을 띄우지 않고 종료 코드 2이다."""
        cases = [
            ["--name", "hei5enbug-agent-setup:nobody", "--host", "claude"],
            ["--name", "nobody", "--host", "codex"],
            ["--name", "worker", "--host", "claude"],
        ]
        for case in cases:
            with self.subTest(case=case):
                # Given
                arguments = ["agent", *case, "--fallback"]

                # When
                completed = self.run_runner(*arguments)

                # Then
                self.assertEqual(2, completed.returncode, completed.stderr)
                self.assertIn("Unknown agent", completed.stderr)
                self.assertFalse(self.log.exists())

    def test_agent는_같은_계열의_대체를_선언하면_종료_코드_2이다(self):
        """선언된 대체가 기본 모델과 같은 계열이면 실행기는 자식을 띄우지 않고 종료 코드 2이다."""
        # Given
        self.use_declared_claude_plugin({
            "example-plugin:scout": {
                "model": "claude-sonnet-5-5", "effort": "medium",
                "fallback": {"model": "claude-opus-5-5", "effort": "high"},
            },
        })
        arguments = ["agent", "--name", "example-plugin:scout", "--fallback"]

        # When
        completed = self.run_runner(*arguments)

        # Then
        self.assertEqual(2, completed.returncode, completed.stderr)
        self.assertIn("other model family", completed.stderr)
        self.assertFalse(self.log.exists())

    def test_agent는_대체가_없는_선언이나_지침이_없는_Codex_역할이면_종료_코드_2이다(self):
        """선언에 fallback이 없거나 Codex 역할 TOML에 developer_instructions가 없으면 자식을 띄우지 않고 종료 코드 2이다."""
        # Given
        self.use_declared_claude_plugin({
            "example-plugin:scout": {"model": "claude-sonnet-5-5", "effort": "medium"},
        })
        self.write(
            self.codex_home / "plugins/cache/market/example/1.0.0/.codex-plugin/model-roles.json",
            json.dumps({"version": 1, "agents": {"example_worker": {
                "model": "gpt-5.6-luna", "effort": "xhigh", "fallback": {"model": "claude-sonnet-5-5", "effort": "medium"},
            }}}),
        )
        cases = [
            ["--name", "example-plugin:scout", "--host", "claude"],
            ["--name", "example_worker", "--host", "codex"],
        ]
        for case in cases:
            with self.subTest(case=case):
                # When
                completed = self.run_runner("agent", *case, "--fallback")

                # Then
                self.assertEqual(2, completed.returncode, completed.stderr)
                self.assertFalse(self.log.exists())

    def test_agent의_금지된_옵션은_종료_코드_2이다(self):
        """역할에는 --name과 --mcp를, agent에는 --model과 --instructions를 넣으면 자식을 띄우지 않고 종료 코드 2이다."""
        cases = [
            ["scout", "--name", "hei5enbug-agent-setup:scout"],
            ["scout", "--mcp"],
            ["agent", "--name", "hei5enbug-agent-setup:scout", "--fallback", "--model", "claude-opus-5-5"],
            ["agent", "--name", "hei5enbug-agent-setup:scout", "--fallback", "--instructions", str(self.instructions)],
        ]
        for case in cases:
            with self.subTest(case=case):
                # When
                completed = self.run_runner(*case)

                # Then
                self.assertEqual(2, completed.returncode, completed.stderr)
                self.assertFalse(self.log.exists())

    def test_capability의_mcp는_Codex에서_MCP_설정을_남기고_Claude에서는_strict를_뺀다(self):
        """--mcp를 준 capability는 Codex 쓰기 실행이 network_access를 켜고 mcp_servers 끄기를 넘기지 않으며, Claude 실행은 strict를 빼고 mcp__* 규칙을 더한다."""
        # Given
        directory = str(self.base / "approved")
        codex_case = ["language", "--host", "claude", "--mcp", "--instructions", str(self.instructions)]
        claude_case = ["design", "--host", "codex", "--fallback", "--mcp", "--add-dir", directory, "--instructions", str(self.instructions)]

        # When
        codex_completed = self.run_runner(*codex_case, config={"turns": [{"model": "gpt-6.1-sol", "effort": "high"}]})
        codex_argv = self.logged()["argv"]
        claude_completed = self.run_runner(*claude_case)

        # Then
        self.assertEqual(0, codex_completed.returncode, codex_completed.stderr)
        self.assertEqual(
            [
                "exec", "resume", THREAD, "-m", "gpt-6.1-sol", "-c", 'model_reasoning_effort="high"',
                "-c", 'sandbox_mode="workspace-write"', "-c", "sandbox_workspace_write.network_access=true",
                "--json", "-o", str(self.result), "-",
            ],
            codex_argv,
        )
        self.assertEqual(0, claude_completed.returncode, claude_completed.stderr)
        self.assertEqual(
            [
                "-p", "--model", "claude-opus-5-5", "--effort", "high", "--output-format", "json",
                "--tools", "Read", "Grep", "Glob", "Bash", "Edit", "Write",
                "--permission-mode", "dontAsk", "--allowedTools", "Read", "Grep", "Glob", *SHELL_RULES,
                f"Edit(/{directory}/**)", "Bash", "mcp__*",
                "--add-dir", directory,
            ],
            self.logged()["argv"],
        )

    def test_instructions의_frontmatter는_빼고_역할_정의_자리에_넣는다(self):
        """capability 프롬프트는 시작 문장, frontmatter 없는 지침, Assigned workers 절, 할당 순서로 표준 입력에 들어간다."""
        # Given
        instructions = self.base / "with-frontmatter.md"
        instructions.write_text("---\nname: probe\ndescription: test\n---\nBODY LINE\n")
        section = session_context.assigned_workers_section(REPO_ROOT)

        # When
        completed = self.run_runner("investigation", "--host", "claude", "--instructions", str(instructions))

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        prompt = self.logged()["stdin"]
        self.assertEqual(
            role_runner.compose_capability_prompt("investigation", "BODY LINE", "Find the answer.\nSECOND LINE\n", REPO_ROOT),
            prompt,
        )
        self.assertTrue(prompt.startswith(role_runner.capability_sentence("investigation")))
        self.assertNotIn("description: test", prompt)
        self.assertLess(prompt.index("BODY LINE"), prompt.index(section))
        self.assertLess(prompt.index(section), prompt.index("## Assignment"))

    def test_capability와_새_옵션의_잘못된_조합은_종료_코드_2이다(self):
        """알 수 없는 target, 빠진 또는 없는 --instructions, 역할에 맞지 않는 옵션, 빈 --resume은 실행 없이 종료 코드 2이다."""
        cases = [
            ["not-a-capability", "--host", "claude", "--instructions", str(self.instructions)],
            ["investigation", "--host", "claude"],
            ["investigation", "--host", "claude", "--instructions", str(self.base / "missing.md")],
            ["scout", "--instructions", str(self.instructions)],
            ["scout", "--fallback"],
            ["review", "--host", "codex", "--model", "claude-opus-5-5", "--instructions", str(self.instructions)],
            ["review", "--host", "codex", "--add-dir", str(self.base), "--instructions", str(self.instructions)],
            ["review", "--host", "codex", "--instructions", str(self.instructions), "--resume="],
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                # Given
                # (the case arguments above name a call the runner must refuse before any child starts)

                # When
                completed = self.run_runner(*arguments)

                # Then
                self.assertEqual(2, completed.returncode, completed.stderr)
                self.assertFalse(self.log.exists())

    def test_HEI5ENBUG_REVIEW_MODEL은_목록에_있을_때만_review의_Claude_primary_모델을_바꾼다(self):
        """review의 Claude primary는 환경 변수가 review_models의 값이면 그 모델로, 아니면 entry 모델로 실행한다."""
        cases = [
            ({"HEI5ENBUG_REVIEW_MODEL": "claude-haiku-5-5"}, {"model": "claude-haiku-5-5"}, self.claude_argv(model="claude-haiku-5-5")),
            ({"HEI5ENBUG_REVIEW_MODEL": "gpt-5.4"}, {"turns": [{"model": "gpt-6-astra", "effort": "high"}]}, self.codex_argv(model="gpt-6-astra")),
            ({}, {"turns": [{"model": "gpt-6-astra", "effort": "high"}]}, self.codex_argv(model="gpt-6-astra")),
        ]
        for extra_env, config, expected in cases:
            with self.subTest(extra_env=extra_env):
                # Given
                arguments = ["review", "--host", "claude", "--instructions", str(self.instructions)]

                # When
                completed = self.run_runner(*arguments, config=config, extra_env=extra_env)

                # Then
                self.assertEqual(0, completed.returncode, completed.stderr)
                self.assertEqual(expected, self.logged()["argv"])

    def test_host를_생략하면_CODEX_THREAD_ID가_있을_때만_codex_entry를_고른다(self):
        """CODEX_THREAD_ID가 없으면 claude 호스트, 있으면 codex 호스트의 entry를 고른다."""
        cases = [
            ({}, None, self.codex_argv(model="gpt-6-astra")),
            ({"CODEX_THREAD_ID": "thread"}, {"entries": [{"model": "claude-opus-5-5", "effort": "high"}]}, self.claude_argv(effort="high")),
        ]
        for extra_env, config, expected in cases:
            with self.subTest(extra_env=extra_env):
                # Given
                arguments = ["review", "--instructions", str(self.instructions)]
                config = config or {"turns": [{"model": "gpt-6-astra", "effort": "high"}]}

                # When
                completed = self.run_runner(*arguments, config=config, extra_env=extra_env)

                # Then
                self.assertEqual(0, completed.returncode, completed.stderr)
                self.assertEqual(expected, self.logged()["argv"])

    def test_host_옵션은_역할_실행에서_무시된다(self):
        """scout에 --host claude를 줘도 scout 고정 설정으로 codex exec를 실행한다."""
        # Given
        arguments = ["scout", "--host", "claude"]

        # When
        completed = self.run_runner(*arguments)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.codex_argv(), self.logged()["argv"])

    def test_claude_resume은_같은_session_id와_모델과_effort로_실행하고_evidence에_남긴다(self):
        """Claude capability를 --resume으로 이어 실행하면 claude -p --resume 인자를 쓰고 session을 evidence에 남긴다."""
        # Given
        config = {"entries": [{"model": "claude-opus-5-5", "effort": "high"}]}
        arguments = ["review", "--host", "codex", "--resume", SESSION, "--instructions", str(self.instructions)]

        # When
        completed = self.run_runner(*arguments, config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.claude_argv(effort="high", resume=SESSION), self.logged()["argv"])
        status = self.status(completed)
        self.assertEqual((True, SESSION), (status["verified"], status["evidence"]["session"]))

    def test_evidence의_session은_codex에서는_thread_id이고_claude에서는_session_id이다(self):
        """성공한 실행은 재개에 쓸 id를 evidence.session으로 남긴다."""
        cases = [
            (["scout"], None, THREAD),
            (["reviewer", "--model", "claude-opus-5-5"], None, SESSION),
        ]
        for arguments, config, expected in cases:
            with self.subTest(arguments=arguments):
                # Given
                # (the fake runners answer with the fixed thread and session ids)

                # When
                completed = self.run_runner(*arguments, config=config)

                # Then
                self.assertEqual(0, completed.returncode, completed.stderr)
                self.assertEqual(expected, self.status(completed)["evidence"]["session"])

    def test_verification의_effort는_실행_entry의_effort와_같아야_한다(self):
        """language의 entry effort는 high이므로 기록이 xhigh이면 종료 코드 4이고 결과를 남기지 않는다."""
        # Given
        config = {"turns": [{"model": "gpt-6.1-sol", "effort": "xhigh"}]}
        arguments = ["language", "--host", "claude", "--instructions", str(self.instructions)]

        # When
        completed = self.run_runner(*arguments, config=config)

        # Then
        self.assertEqual(4, completed.returncode)
        self.assertFalse(self.result.exists())

    def test_Claude_쓰기_실행은_bare_Bash와_승인된_편집_규칙을_허용한다(self):
        """Claude 경로의 쓰기 실행은 dontAsk로 읽기 셸 목록, bare Bash, 승인된 디렉터리의 절대 경로 Edit 규칙을 허용한다."""
        # Given
        directory = str(self.base / "approved")
        self.write(self.codex_home / "agents" / "worker.toml", 'name = "worker"\ndeveloper_instructions = """\nCODEX WORKER BODY\n"""\n')
        claude_config = {"model": "claude-sonnet-5-5", "entries": [{"model": "claude-sonnet-5-5", "effort": "high"}]}
        cases = [
            (["agent", "--name", "worker", "--host", "codex", "--fallback", "--add-dir", directory], claude_config),
            (["design", "--host", "codex", "--fallback", "--add-dir", directory, "--instructions", str(self.instructions)], None),
        ]
        for arguments, config in cases:
            with self.subTest(target=arguments[0]):
                # When
                completed = self.run_runner(*arguments, config=config)

                # Then
                self.assertEqual(0, completed.returncode, completed.stderr)
                rules = allowed_rules(self.logged()["argv"])
                self.assertIn("Bash", rules)
                self.assertTrue(set(SHELL_RULES) <= set(rules))
                self.assertIn(f"Edit(/{directory}/**)", rules)
                self.assertFalse([rule for rule in rules if rule.startswith("Write(")])
                argv = self.logged()["argv"]
                self.assertEqual("dontAsk", argv[argv.index("--permission-mode") + 1])

    def test_claude_tools는_규칙이_이름_붙인_도구만_처음_나온_순서로_담는다(self):
        """--tools는 허용 규칙이 가리키는 도구 이름을 처음 나온 순서로 담고 Edit 규칙이 함께 허용하는 Write를 덧붙이며, mcp__* 규칙은 도구 이름이 아니다."""
        # Given
        rules = ["Read", "Bash(git diff:*)", "Bash(wc:*)", "WebFetch", "Edit(/x/**)", "Bash", "mcp__*"]

        # When
        tools = role_runner.claude_tools(rules)

        # Then
        self.assertEqual(["Read", "Bash", "WebFetch", "Edit", "Write"], tools)

    def test_mcp_없는_Claude_실행의_프롬프트만_읽기_셸_명령과_git_C_금지를_담는다(self):
        """--mcp 없는 Claude 실행 프롬프트는 허용된 읽기 셸 명령과 git -C 금지 문장을 담고, --mcp 실행과 Codex 실행은 담지 않는다."""
        # Given
        directory = str(self.base / "approved")
        self.write(self.codex_home / "agents" / "worker.toml", 'name = "worker"\ndeveloper_instructions = """\nCODEX WORKER BODY\n"""\n')
        sonnet = {"model": "claude-sonnet-5-5", "entries": [{"model": "claude-sonnet-5-5", "effort": "high"}]}
        opus = {"model": "claude-opus-5-5", "entries": [{"model": "claude-opus-5-5", "effort": "high"}]}
        cases = [
            (["language", "--host", "claude", "--fallback", "--add-dir", directory, "--instructions", str(self.instructions)], opus, True),
            (["agent", "--name", "worker", "--host", "codex", "--fallback", "--add-dir", directory], sonnet, True),
            (["agent", "--name", "worker", "--host", "codex", "--fallback", "--add-dir", directory, "--mcp"], sonnet, False),
            (["investigation", "--host", "claude", "--instructions", str(self.instructions)], None, False),
        ]
        for arguments, config, limited in cases:
            with self.subTest(arguments=arguments):
                # When
                completed = self.run_runner(*arguments, config=config)

                # Then
                self.assertEqual(0, completed.returncode, completed.stderr)
                prompt = self.logged()["stdin"]
                self.assertEqual(limited, "`git diff`, `git show`" in prompt)
                self.assertEqual(limited, "`git -C`" in prompt)

    def test_mcp_옵션의_프롬프트는_no_network_대신_외부_작업의_MCP_네트워크_규칙을_쓴다(self):
        """capability와 agent 프롬프트는 --mcp가 없으면 use no network를, 있으면 외부 작업에만 쓰는 MCP와 네트워크 규칙을 쓴다."""
        # Given
        directory = str(self.base / "approved")
        self.write(self.codex_home / "agents" / "worker.toml", 'name = "worker"\ndeveloper_instructions = """\nCODEX WORKER BODY\n"""\n')
        claude_config = {"model": "claude-sonnet-5-5", "entries": [{"model": "claude-sonnet-5-5", "effort": "high"}]}
        cases = [
            (["investigation", "--host", "claude", "--instructions", str(self.instructions)], None, False),
            (["investigation", "--host", "claude", "--mcp", "--instructions", str(self.instructions)], None, True),
            (["agent", "--name", "worker", "--host", "codex", "--fallback", "--add-dir", directory], claude_config, False),
            (["agent", "--name", "worker", "--host", "codex", "--fallback", "--add-dir", directory, "--mcp"], claude_config, True),
        ]
        for arguments, config, mcp in cases:
            with self.subTest(arguments=arguments):
                # When
                completed = self.run_runner(*arguments, config=config)

                # Then
                self.assertEqual(0, completed.returncode, completed.stderr)
                prompt = self.logged()["stdin"]
                expected, other = (role_runner.MCP_NETWORK_RULE, "use no network") if mcp else ("use no network", role_runner.MCP_NETWORK_RULE)
                self.assertIn(expected, prompt)
                self.assertNotIn(other, prompt)

    def test_review의_Claude_primary가_Claude이면_대체는_gpt_astra_high_실행기다(self):
        """review의 Claude primary가 HEI5ENBUG_REVIEW_MODEL로 Claude 모델이 되면 대체는 레지스트리의 Claude 에이전트 대신 gpt-6-astra high 실행기다."""
        # Given
        arguments = ["review", "--host", "claude", "--fallback", "--instructions", str(self.instructions)]
        config = {"turns": [{"model": "gpt-6-astra", "effort": "high"}]}

        # When
        completed = self.run_runner(*arguments, config=config, extra_env={"HEI5ENBUG_REVIEW_MODEL": "claude-opus-5-5"})

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.codex_argv(model="gpt-6-astra", effort="high"), self.logged()["argv"])
        status = self.status(completed)
        self.assertEqual(
            (True, "codex", "gpt-6-astra", "high"),
            (status["fallback"], status["runner"], status["model"], status["effort"]),
        )

    def test_review의_GPT_primary면_대체는_레지스트리의_Claude_에이전트_항목을_유지한다(self):
        """review의 primary가 기본 GPT이면 Claude 대체는 레지스트리의 reviewer 에이전트 항목이라 실행기로 가지 않고 종료 코드 2이다."""
        # Given
        arguments = ["review", "--host", "claude", "--fallback", "--instructions", str(self.instructions)]

        # When
        completed = self.run_runner(*arguments)

        # Then
        self.assertEqual(2, completed.returncode)
        self.assertIn("via 'agent'", completed.stderr)
        self.assertFalse(self.log.exists())

    def test_대체가_기본_항목과_같은_계열이면_계획_단계에서_UsageError이다(self):
        """design의 Codex 호스트 대체를 기본 항목과 같은 GPT 계열로 바꾸면 자식을 띄우기 전에 UsageError이다."""
        # Given
        argv = [
            "design", "--host", "codex", "--fallback", "--add-dir", str(self.base / "approved"),
            "--instructions", str(self.instructions), "--assignment", str(self.assignment), "--result", str(self.result),
        ]
        parsed = role_runner.build_parser().parse_args(argv)
        same_family = {"model": "gpt-6.1-sol", "effort": "xhigh", "via": "runner"}

        # When
        with mock.patch.dict(role_runner.CAPABILITIES["design"]["codex"], {"fallback": same_family}):
            with self.assertRaises(role_runner.UsageError) as caught:
                role_runner.plan(parsed)

        # Then
        self.assertIn("other model family", str(caught.exception))

    def test_레지스트리의_capability_이름은_읽기_전용과_쓰기로_빠짐없이_나뉜다(self):
        """읽기 전용 둘과 쓰기 셋이 레지스트리 capability 이름 전체와 같다."""
        # Given
        read_only = {"investigation", "review"}
        writing = set(role_runner.WRITING_CAPABILITIES)

        # When
        names = set(role_runner.CAPABILITIES)

        # Then
        self.assertEqual(names, read_only | writing)
        self.assertEqual(set(), read_only & writing)

    def test_MCP_서버는_목록에서_이름만_읽어_서버마다_enabled_false로_끈다(self):
        """--mcp 없는 Codex 실행은 codex mcp list --json의 이름마다 mcp_servers.<이름>.enabled=false를 넘기고 빈 매핑은 쓰지 않는다."""
        # Given
        config = {"mcp_list": json.dumps([{"name": "aside", "transport": {"command": "secret-command"}}, {"name": "data-dog_2"}])}

        # When
        completed = self.run_runner("scout", config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        listing = self.calls()[0]
        self.assertEqual(["mcp", "list", "--json"], listing["argv"])
        names = ("aside", "data-dog_2")
        (execution,) = self.executions()
        self.assertEqual(self.codex_start_argv(mcp_off=names), execution["argv"])
        for call in (*self.app_server_calls(), execution):
            self.assertNotIn("mcp_servers={}", call["argv"])
            self.assertNotIn("secret-command", " ".join(call["argv"]))

    def test_MCP_서버_목록은_자식과_같은_환경으로_조회한다(self):
        """codex mcp list와 hook 점검 app-server는 자식 실행과 같은 역할 표식과 부모 세션 환경을 받는다."""
        # Given
        extra = {"HEI5ENBUG_PARENT_SESSION": "claude:parent-1"}

        # When
        completed = self.run_runner("scout", extra_env=extra)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        listing = self.calls()[0]
        self.assertEqual(["mcp", "list", "--json"], listing["argv"])
        self.assertEqual(("scout", "claude:parent-1"), (listing["role"], listing["parent"]))
        (readiness,) = self.app_server_calls()
        (execution,) = self.executions()
        for call in (readiness, execution):
            self.assertEqual((call["role"], call["parent"]), (listing["role"], listing["parent"]))

    def test_MCP_서버_목록이_비어_있으면_끄기_설정을_넘기지_않는다(self):
        """서버가 하나도 없으면 -c mcp_servers 설정 없이 실행한다."""
        # Given
        config = {"mcp_list": "[]"}

        # When
        completed = self.run_runner("scout", config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.codex_argv(mcp_off=False), self.logged()["argv"])

    def test_MCP_서버_목록을_못_읽으면_자식을_실행하지_않고_종료_코드_3이다(self):
        """목록 조회 실패, JSON이 아닌 출력, 목록이 아닌 JSON, 안전하지 않은 이름은 MCP를 켠 채 실행하지 않고 종료 코드 3이다."""
        cases = [
            {"mcp_exit": 5},
            {"mcp_list": "not json"},
            {"mcp_list": json.dumps({"aside": {}})},
            {"mcp_list": json.dumps(["aside"])},
            {"mcp_list": json.dumps([{"name": 'a"b'}])},
            {"mcp_list": json.dumps([{"name": "a.b"}])},
            {"mcp_list": json.dumps([{"name": "has space"}])},
            {"mcp_list": json.dumps([{"name": ""}])},
            {"mcp_list": json.dumps([{"enabled": True}])},
        ]
        for config in cases:
            with self.subTest(config=config):
                # Given
                self.log.unlink(missing_ok=True)

                # When
                completed = self.run_runner("scout", config=config)

                # Then
                self.assertEqual(3, completed.returncode, completed.stderr)
                self.assertEqual([], self.executions())
                self.assertFalse(self.result.exists())
                self.assertFalse(self.status(completed)["verified"])
                self.assertIn("MCP", completed.stderr)

    def test_mcp_옵션은_서버_목록을_조회하지_않는다(self):
        """--mcp를 준 Codex 실행은 MCP 서버를 끄지 않으므로 목록을 조회하지 않는다."""
        # Given
        arguments = ["language", "--host", "claude", "--mcp", "--instructions", str(self.instructions)]
        config = {"turns": [{"model": "gpt-6.1-sol", "effort": "high"}]}

        # When
        completed = self.run_runner(*arguments, config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(len(self.calls()), len(self.executions()) + len(self.app_server_calls()))
        self.assertFalse(any(item.startswith("mcp_servers.") for call in self.calls() for item in call["argv"]))

    def test_resume도_서버_목록을_조회해_끄기_설정을_넘긴다(self):
        """--resume으로 이은 Codex 실행도 목록을 조회해 exec resume에 서버별 끄기 설정을 넘긴다."""
        # Given
        self.beat("codex", THREAD)
        config = {"mcp_list": json.dumps([{"name": "only"}])}

        # When
        completed = self.run_runner("scout", "--resume", THREAD, config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(["mcp", "list", "--json"], self.calls()[0]["argv"])
        self.assertEqual(self.codex_resume_argv(mcp_off=("only",)), self.logged()["argv"])
        self.assertEqual(["app-server", *self.mcp_off_flags(("only",))], self.app_server_calls()[0]["argv"])

    def test_부모_세션은_자식_환경에_상속값_Claude_Codex_순서로_들어간다(self):
        """HEI5ENBUG_PARENT_SESSION은 기존 값을 유지하고, 없으면 CLAUDECODE와 세션 ID가 있을 때 claude:ID, 그다음 codex:ID이며, 없으면 비워 둔다."""
        cases = [
            ({"HEI5ENBUG_PARENT_SESSION": "codex:kept", "CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "c1"}, "codex:kept"),
            ({"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "c1", "CODEX_SESSION_ID": "x1"}, "claude:c1"),
            ({"CLAUDE_CODE_SESSION_ID": "c1", "CODEX_SESSION_ID": "x1"}, "codex:x1"),
            ({"CLAUDECODE": "1", "CODEX_SESSION_ID": "x1"}, "codex:x1"),
            ({"CODEX_SESSION_ID": "x1"}, "codex:x1"),
            ({"CODEX_THREAD_ID": "t1"}, "codex:t1"),
            ({"CODEX_SESSION_ID": "x1", "CODEX_THREAD_ID": "t1"}, "codex:x1"),
            ({"CLAUDECODE": "1"}, None),
            ({}, None),
        ]
        for extra, expected in cases:
            with self.subTest(extra=extra):
                # Given
                self.log.unlink(missing_ok=True)

                # When
                completed = self.run_runner("scout", extra_env=extra)

                # Then
                self.assertEqual(0, completed.returncode, completed.stderr)
                self.assertEqual({expected}, {call["parent"] for call in self.calls()})

    def test_부모_세션은_Claude_자식에게도_들어간다(self):
        """Claude로 실행하는 자식도 같은 방식으로 정한 부모 세션 환경을 받는다."""
        # Given
        extra = {"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "c9"}

        # When
        completed = self.run_runner("reviewer", "--model", "claude-opus-5-5", extra_env=extra)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("claude:c9", self.logged()["parent"])

    def test_Codex는_훅을_점검한_뒤_할당_하나만_exec로_보낸다(self):
        """새 Codex 실행은 app-server로 훅을 점검하고, 확인용 턴 없이 할당을 담은 exec 하나만 보낸다."""
        # Given
        arguments = ["scout"]

        # When
        completed = self.run_runner(*arguments)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(["mcp", "app-server", "exec"], [call["argv"][0] for call in self.calls()])
        (execution,) = self.executions()
        self.assertIn("Find the answer.", execution["stdin"])
        self.assertNotIn("exactly once", execution["stdin"])
        self.assertEqual(self.codex_start_argv(), execution["argv"])
        (readiness,) = self.app_server_calls()
        self.assertEqual(["app-server", *self.mcp_off_flags()], readiness["argv"])
        self.assertEqual(str(self.workspace), readiness["cwd"])
        evidence = self.status(completed)["evidence"]
        self.assertEqual((THREAD, 1), (evidence["session"], evidence["tool_calls"]))
        self.assertEqual("codex answer", self.result.read_text())

    def test_준비된_훅은_관리됨_표시나_셸을_덮는_matcher로도_통과한다(self):
        """untrusted여도 isManaged이면, 그리고 matcher가 비었거나 *이거나 Bash를 덮으면 할당을 보낸다."""
        # Given
        configurations = [
            {"hooks_trust": "untrusted", "hooks_managed": True},
            {"hooks_matcher": None},
            {"hooks_matcher": ""},
            {"hooks_matcher": "*"},
            {"hooks_matcher": "Bash"},
            {"hooks_matcher": "^(Agent|Bash)$"},
        ]
        for config in configurations:
            with self.subTest(config=config):
                self.log.unlink(missing_ok=True)

                # When
                completed = self.run_runner("scout", config=config)

                # Then
                self.assertEqual(0, completed.returncode, completed.stderr)
                self.assertEqual(1, len(self.executions()))

    def test_훅이_준비되지_않았으면_할당을_보내지_않고_종료_코드_4이다(self):
        """신뢰 안 됨, 수정됨, 꺼짐, 비동기, 셸을 덮지 않는 matcher, 잘못된 정규식, 훅 없음, 다른 명령만 있는 경우는 exec 없이 종료 코드 4이다."""
        # Given
        cases = {
            "untrusted": {"hooks_trust": "untrusted"},
            "modified": {"hooks_trust": "modified"},
            "disabled": {"hooks_enabled": False},
            "async": {"hooks_async": True},
            "matcher": {"hooks_matcher": "^Agent$"},
            "invalid regex": {"hooks_matcher": "("},
            "empty": {"hooks_empty": True},
            "foreign command": {"hooks_command": "sh other_hook.py"},
            "name only": {"hooks_command": "echo approval_guard.py"},
        }
        for label, config in cases.items():
            with self.subTest(case=label):
                self.log.unlink(missing_ok=True)

                # When
                completed = self.run_runner("scout", config=config)

                # Then
                self.assertEqual(4, completed.returncode)
                self.assertIn(role_runner.CODEX_HOOKS_MESSAGE, completed.stderr)
                self.assertEqual([], self.executions())
                self.assertFalse(self.result.exists())
                status = self.status(completed)
                self.assertFalse(status["verified"])
                hooks = status["evidence"]["hooks"]
                self.assertEqual(0 if label in ("empty", "foreign command", "name only") else 1, len(hooks))

    def test_훅_증거는_찾은_훅의_키_활성_신뢰_상태를_남긴다(self):
        """준비되지 않은 훅의 증거는 키, enabled, trust를 담는다."""
        # Given
        config = {"hooks_trust": "modified"}

        # When
        completed = self.run_runner("scout", config=config)

        # Then
        (hook,) = self.status(completed)["evidence"]["hooks"]
        self.assertEqual("plugin@market:hooks/hooks.json:pre_tool_use:1:0", hook["key"])
        self.assertEqual((True, "modified"), (hook["enabled"], hook["trust"]))

    def test_app_server가_답하지_못하면_할당을_보내지_않고_종료_코드_3이다(self):
        """app-server가 오류 응답, 비정상 종료, JSON이 아닌 출력, cwd 항목 없음, 시간 초과이면 exec 없이 종료 코드 3이다."""
        # Given
        cases = {
            "error reply": ({"hooks_error": True}, "rejected"),
            "exit": ({"hooks_exit": 5}, "ended before answering"),
            "not json": ({"hooks_not_json": True}, "not JSON"),
            "invalid utf-8": ({"hooks_bad_bytes": True}, "not JSON"),
            "no entry": ({"hooks_no_entry": True}, "no hooks entry"),
            "timeout": ({"hooks_sleep": 60}, "timeout"),
        }
        for label, (config, reason) in cases.items():
            with self.subTest(case=label):
                self.log.unlink(missing_ok=True)

                # When
                completed = self.run_runner("scout", "--timeout", "2", config=config)

                # Then
                self.assertEqual(3, completed.returncode, completed.stderr)
                self.assertIn(reason, completed.stderr)
                self.assertEqual([], self.executions())
                self.assertFalse(self.result.exists())
                self.assertFalse(self.status(completed)["verified"])

    def test_시간_초과된_app_server는_강제로_끝낸다(self):
        """제한 시간을 넘긴 app-server 프로세스는 남지 않는다."""
        # Given
        config = {"hooks_sleep": 60}

        # When
        started = time.monotonic()
        completed = self.run_runner("scout", "--timeout", "1", config=config)
        elapsed = time.monotonic() - started

        # Then
        self.assertEqual(3, completed.returncode)
        self.assertLess(elapsed, 30)
        pid = self.app_server_calls()[0]["pid"]
        alive = True
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                alive = False
                break
            time.sleep(0.1)
        self.assertFalse(alive)

    def test_점검과_exec는_같은_MCP_끄기_설정과_환경을_받는다(self):
        """hook 점검 app-server는 exec와 같은 -c mcp_servers 설정, 역할 표식, 부모 세션, 작업 폴더를 받는다."""
        # Given
        config = {"mcp_list": json.dumps([{"name": "only"}, {"name": "second"}])}
        extra = {"HEI5ENBUG_PARENT_SESSION": "claude:parent-9"}

        # When
        completed = self.run_runner("scout", config=config, extra_env=extra)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        (readiness,) = self.app_server_calls()
        (execution,) = self.executions()
        flags = self.mcp_off_flags(("only", "second"))
        self.assertEqual(["app-server", *flags], readiness["argv"])
        self.assertEqual(self.codex_start_argv(mcp_off=("only", "second")), execution["argv"])
        for key in ("role", "parent", "cwd"):
            self.assertEqual(execution[key], readiness[key])
        self.assertEqual(("scout", "claude:parent-9"), (readiness["role"], readiness["parent"]))

    def test_도구를_쓴_실행에_PreToolUse_하트비트가_없으면_결과를_버리고_종료_코드_4이다(self):
        """rollout에 도구 호출이 있는데 thread의 PreToolUse 하트비트가 없으면 결과를 남기지 않고 종료 코드 4이다."""
        # Given
        config = {"no_heartbeat": True}

        # When
        completed = self.run_runner("scout", config=config)

        # Then
        self.assertEqual(4, completed.returncode)
        self.assertIn("The approval guard hooks did not run in Codex; trust them in /hooks", completed.stderr)
        self.assertEqual(1, len(self.executions()))
        self.assertTrue(self.status(completed)["evidence"]["heartbeat"].endswith(".PreToolUse"))
        self.assertFalse(self.result.exists())
        self.assertFalse(self.status(completed)["verified"])

    def test_도구를_쓰지_않은_실행은_하트비트가_없어도_통과한다(self):
        """rollout에 도구 호출이 없으면 가드가 막을 호출이 없으므로 하트비트 없이 종료 코드 0이고 tool_calls는 0이다."""
        # Given
        config = {"no_heartbeat": True, "no_tool_calls": True}

        # When
        completed = self.run_runner("scout", config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(0, self.status(completed)["evidence"]["tool_calls"])
        self.assertEqual("codex answer", self.result.read_text())

    def test_웹_검색_호출은_도구_호출로_세지_않는다(self):
        """web_search_call만 있는 rollout은 도구 호출 0건이다."""
        # Given
        config = {"no_heartbeat": True, "no_tool_calls": True}

        # When
        completed = self.run_runner("researcher", config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(0, self.status(completed)["evidence"]["tool_calls"])

    def test_Codex는_일반_하트비트만_있으면_도구를_쓴_결과를_버린다(self):
        """일반 하트비트만 있고 PreToolUse 증거가 없으면 도구를 쓴 실행의 결과를 버리고 종료 코드 4를 낸다."""
        # Given
        config = {"legacy_only": True}

        # When
        completed = self.run_runner("scout", config=config)

        # Then
        self.assertEqual(4, completed.returncode)
        self.assertIn(role_runner.CODEX_HOOKS_MESSAGE, completed.stderr)
        self.assertEqual(1, len(self.executions()))
        self.assertTrue(self.status(completed)["evidence"]["heartbeat"].endswith(".PreToolUse"))
        self.assertFalse(self.result.exists())

    def test_Codex는_차단하지_않는_이벤트_하트비트로_통과하지_않는다(self):
        """UserPromptSubmit이나 SessionStart 증거만으로는 도구를 쓴 Codex 실행이 PreToolUse 검사를 통과할 수 없다."""
        # Given
        configurations = [{"heartbeat_event": event} for event in ("UserPromptSubmit", "SessionStart")]

        # When
        outcomes = [self.run_runner("scout", config=config).returncode for config in configurations]

        # Then
        self.assertEqual([4, 4], outcomes)
        self.assertFalse(self.result.exists())

    def test_Codex_resume도_일반_하트비트만_있으면_할당을_보내지_않는다(self):
        """기존 스레드 재개에서도 일반 하트비트만 있으면 실행 전에 종료 코드 4를 낸다."""
        # Given
        heartbeat = self.state_home / "hei5enbug-agent-setup" / "heartbeats" / f"codex-{THREAD}"
        heartbeat.parent.mkdir(parents=True)
        heartbeat.touch()

        # When
        completed = self.run_runner("scout", "--resume", THREAD)

        # Then
        self.assertEqual(4, completed.returncode)
        self.assertIn(role_runner.CODEX_HOOKS_MESSAGE, completed.stderr)
        self.assertEqual([], self.executions())
        self.assertFalse(self.result.exists())

    def test_Codex는_PreToolUse_하트비트만_있어도_통과한다(self):
        """Codex의 PreToolUse 하트비트가 있으면 일반 파일이 없어도 통과한다."""
        # Given
        config = {"event_only": True}

        # When
        completed = self.run_runner("scout", config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(1, len(self.executions()))

    def test_Codex_출력에_thread_id가_없으면_종료_코드_4이고_결과를_남기지_않는다(self):
        """출력에 thread.started가 없으면 rollout을 찾을 수 없어 종료 코드 4이다."""
        # Given
        config = {"no_thread": True}

        # When
        completed = self.run_runner("scout", config=config)

        # Then
        self.assertEqual(4, completed.returncode)
        self.assertEqual(1, len(self.executions()))
        self.assertFalse(self.result.exists())

    def test_쓰기_Codex_실행은_true_한_번으로_훅을_확인한_뒤_같은_스레드에_할당을_보낸다(self):
        """쓰기 실행의 첫 codex exec는 true 한 번과 OK 응답을 요청하고, 같은 설정의 exec resume이 할당을 전달한다."""
        # Given
        directory = str(self.base)
        arguments = ["worker", "--add-dir", directory]

        # When
        completed = self.run_runner(*arguments)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        first, second = self.executions()
        self.assertEqual("Run the shell command `true` exactly once, then reply with OK only.", first["stdin"])
        self.assertIn("Find the answer.", second["stdin"])
        output = first["argv"][first["argv"].index("-o") + 1]
        self.assertNotEqual(str(self.result), output)
        self.assertEqual(self.codex_start_argv(sandbox="workspace-write", add_dirs=(directory,), output=output), first["argv"])
        self.assertEqual(self.codex_resume_argv(sandbox="workspace-write", roots=(directory,)), second["argv"])
        self.assertEqual(THREAD, self.status(completed)["evidence"]["session"])
        self.assertEqual("codex answer", self.result.read_text())

    def test_쓰기_Codex_실행은_app_server를_부르지_않고_preflight_경로를_탄다(self):
        """worker, 쓰기 capability, --resume한 worker는 codex app-server를 부르지 않으므로 app-server가 실패해도 통과한다."""
        # Given
        self.beat("codex", THREAD)
        config = {"hooks_exit": 5, "turns": [{"model": "gpt-6.1-sol", "effort": "high"}]}
        cases = {
            "worker": ["worker", "--add-dir", str(self.base)],
            "resumed worker": ["worker", "--add-dir", str(self.base), "--resume", THREAD],
            "capability": ["language", "--host", "claude", "--instructions", str(self.instructions)],
        }
        for label, arguments in cases.items():
            with self.subTest(case=label):
                self.log.unlink(missing_ok=True)
                run_config = config if label == "capability" else {"hooks_exit": 5}

                # When
                completed = self.run_runner(*arguments, config=run_config)

                # Then
                self.assertEqual(0, completed.returncode, completed.stderr)
                self.assertEqual([], self.app_server_calls())
                self.assertEqual(1 if label == "resumed worker" else 2, len(self.executions()))

    def test_쓰기_Codex_훅_하트비트가_없으면_할당을_보내지_않고_종료_코드_4이다(self):
        """쓰기 실행에서 preflight thread의 하트비트가 없으면 할당 없이 종료 코드 4와 /hooks 안내를 낸다."""
        # Given
        config = {"no_heartbeat": True}

        # When
        completed = self.run_runner("worker", "--add-dir", str(self.base), config=config)

        # Then
        self.assertEqual(4, completed.returncode)
        self.assertIn("The approval guard hooks did not run in Codex; trust them in /hooks", completed.stderr)
        self.assertEqual(["Run the shell command `true` exactly once, then reply with OK only."],
                         [call["stdin"] for call in self.executions()])
        self.assertFalse(self.result.exists())
        self.assertFalse(self.status(completed)["verified"])

    def test_쓰기_Codex_preflight에_thread_id가_없으면_종료_코드_4이고_할당을_보내지_않는다(self):
        """쓰기 실행의 preflight 출력에 thread.started가 없으면 하트비트를 확인할 수 없어 종료 코드 4이다."""
        # Given
        config = {"no_thread": True}

        # When
        completed = self.run_runner("worker", "--add-dir", str(self.base), config=config)

        # Then
        self.assertEqual(4, completed.returncode)
        self.assertIn("Codex preflight output", completed.stderr)
        self.assertEqual(1, len(self.executions()))
        self.assertFalse(self.result.exists())

    def test_쓰기_Codex는_일반_하트비트만_있으면_할당을_보내지_않는다(self):
        """쓰기 실행에서 일반 하트비트만 있고 PreToolUse 증거가 없으면 할당 없이 종료 코드 4이다."""
        # Given
        config = {"legacy_only": True}

        # When
        completed = self.run_runner("worker", "--add-dir", str(self.base), config=config)

        # Then
        self.assertEqual(4, completed.returncode)
        self.assertEqual(1, len(self.executions()))
        self.assertTrue(self.status(completed)["evidence"]["heartbeat"].endswith(".PreToolUse"))
        self.assertFalse(self.result.exists())

    def test_하트비트는_XDG_STATE_HOME이_없으면_홈의_local_state를_본다(self):
        """XDG_STATE_HOME이 없으면 ~/.local/state 아래 하트비트로 확인한다."""
        # Given
        extra = {"XDG_STATE_HOME": None}

        # When
        completed = self.run_runner("scout", extra_env=extra)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        heartbeat = self.base / ".local" / "state" / "hei5enbug-agent-setup" / "heartbeats" / f"codex-{THREAD}.PreToolUse"
        self.assertTrue(heartbeat.is_file())

    def test_resume은_기존_하트비트가_있을_때만_할당을_보낸다(self):
        """--resume은 그 thread의 하트비트를 먼저 확인하고, 없으면 할당 없이 종료 코드 4이다."""
        # Given
        config = {"no_heartbeat": True}

        # When
        completed = self.run_runner("scout", "--resume", THREAD, config=config)

        # Then
        self.assertEqual(4, completed.returncode)
        self.assertIn("trust them in /hooks", completed.stderr)
        self.assertEqual([], self.executions())
        self.assertEqual(1, len(self.app_server_calls()))

    def test_resume은_훅이_준비되지_않았으면_하트비트가_있어도_할당을_보내지_않는다(self):
        """--resume도 먼저 hook 점검을 하므로 훅이 신뢰되지 않았으면 종료 코드 4이고 exec를 보내지 않는다."""
        # Given
        self.beat("codex", THREAD)
        config = {"hooks_trust": "untrusted"}

        # When
        completed = self.run_runner("scout", "--resume", THREAD, config=config)

        # Then
        self.assertEqual(4, completed.returncode)
        self.assertIn(role_runner.CODEX_HOOKS_MESSAGE, completed.stderr)
        self.assertEqual([], self.executions())
        self.assertFalse(self.result.exists())

    def test_Claude_하트비트가_없으면_종료_코드_4이고_결과를_쓰지_않는다(self):
        """Claude 실행 뒤 결과 JSON의 session_id 하트비트가 없으면 종료 코드 4이고 결과를 남기지 않는다."""
        # Given
        config = {"no_heartbeat": True}

        # When
        completed = self.run_runner("reviewer", "--model", "claude-opus-5-5", config=config)

        # Then
        self.assertEqual(4, completed.returncode)
        self.assertIn("The approval guard hooks did not run in Claude Code", completed.stderr)
        self.assertFalse(self.result.exists())

    def test_Claude_transcript의_synthetic_항목은_건너뛰고_나머지만_검증한다(self):
        """모델이 <synthetic>인 assistant 항목은 건너뛰고, 남은 항목이 하나 이상이며 모두 모델과 effort가 맞으면 통과한다."""
        # Given
        config = {"entries": [{"model": "claude-opus-5-5", "effort": "high"}, {"model": "<synthetic>"}]}

        # When
        completed = self.run_runner("reviewer", "--model", "claude-opus-5-5", config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(1, self.status(completed)["evidence"]["entries"])

    def test_Claude_transcript에_synthetic_항목만_있거나_나머지가_다르면_종료_코드_4이다(self):
        """synthetic 항목만 있으면 실제 모델 증거가 없고, 다른 항목의 모델이나 effort가 다르면 synthetic이 있어도 종료 코드 4이다."""
        # Given
        synthetic = {"model": "<synthetic>"}
        cases = [
            {"entries": [synthetic]},
            {"entries": [synthetic, {"model": "claude-haiku-5-5", "effort": "high"}]},
            {"entries": [synthetic, {"model": "claude-opus-5-5", "effort": "xhigh"}]},
        ]

        # When
        outcomes = [
            self.run_runner("reviewer", "--model", "claude-opus-5-5", config=config).returncode for config in cases
        ]

        # Then
        self.assertEqual([4, 4, 4], outcomes)
        self.assertFalse(self.result.exists())

    def test_Claude_하트비트가_session_id_이름으로_있으면_통과한다(self):
        """Claude 결과의 session_id로 이름 붙은 하트비트가 있으면 검증이 통과한다."""
        # When
        completed = self.run_runner("reviewer", "--model", "claude-opus-5-5")

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        heartbeat = self.state_home / "hei5enbug-agent-setup" / "heartbeats" / f"claude-{SESSION}"
        self.assertTrue(heartbeat.is_file())

    def test_Claude는_UserPromptSubmit_하트비트만_있어도_통과한다(self):
        """Claude는 UserPromptSubmit 하트비트가 있으면 일반 파일이 없어도 검증이 통과한다."""
        # Given
        config = {"event_only": True}

        # When
        completed = self.run_runner("reviewer", "--model", "claude-opus-5-5", config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("claude answer", self.result.read_text())

    def test_Claude는_일반_하트비트를_계속_허용한다(self):
        """Claude는 기존 일반 하트비트만 있어도 검증이 통과한다."""
        # Given
        config = {"legacy_only": True}

        # When
        completed = self.run_runner("reviewer", "--model", "claude-opus-5-5", config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("claude answer", self.result.read_text())

    def pair_args(self, *names):
        """Write one assignment and result path per name, with the assignment text ASSIGN_<name>, and return their arguments."""
        arguments = []
        for name in names:
            assignment = self.base / f"assignment-{name}.md"
            assignment.write_text(f"ASSIGN_{name}\nDetails for {name}.\n")
            arguments += ["--assignment", str(assignment), "--result", str(self.base / f"result-{name}.md")]
        return arguments

    def status_lines(self, completed):
        return [json.loads(line) for line in completed.stdout.strip().splitlines()]

    def test_effort를_생략하면_자식_명령과_상태_줄은_범위의_하한을_쓴다(self):
        """--effort가 없으면 scout는 레지스트리 실행기 항목의 하한 high를 자식 명령과 상태 줄에 쓴다."""
        # Given
        arguments = ["scout"]

        # When
        completed = self.run_runner(*arguments)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.codex_argv(effort="high"), self.logged()["argv"])
        self.assertEqual("high", self.status(completed)["effort"])

    def test_effort_xhigh는_범위_안이면_Codex_자식_명령과_상태_줄에_그대로_쓰인다(self):
        """scout에 --effort xhigh를 주면 codex exec이 xhigh로 실행되고 상태 줄이 xhigh와 검증 성공을 보고한다."""
        # Given
        arguments = ["scout", "--effort", "xhigh"]
        config = {"turns": [{"model": "gpt-5.6-luna", "effort": "xhigh"}]}

        # When
        completed = self.run_runner(*arguments, config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.codex_argv(effort="xhigh"), self.logged()["argv"])
        status = self.status(completed)
        self.assertEqual(("xhigh", True), (status["effort"], status["verified"]))

    def test_effort_xhigh는_Claude_capability_자식_명령에도_넘어간다(self):
        """review의 Codex 호스트 기본 항목은 Claude 실행기이고, --effort xhigh는 claude -p의 --effort로 넘어간다."""
        # Given
        arguments = ["review", "--host", "codex", "--instructions", str(self.instructions), "--effort", "xhigh"]
        config = {"entries": [{"model": "claude-opus-5-5", "effort": "xhigh"}]}

        # When
        completed = self.run_runner(*arguments, config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.claude_argv(effort="xhigh"), self.logged()["argv"])

    def test_agent_모드의_effort는_대체_항목의_범위_안에서_고른다(self):
        """agent 모드는 대체 항목의 범위를 쓰므로 scout의 Luna 대체에 --effort xhigh를 넘길 수 있다."""
        # Given
        arguments = ["agent", "--name", "hei5enbug-agent-setup:scout", "--fallback", "--effort", "xhigh"]
        config = {"turns": [{"model": "gpt-5.6-luna", "effort": "xhigh"}]}

        # When
        completed = self.run_runner(*arguments, config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.codex_argv(search=True, effort="xhigh"), self.logged()["argv"])

    def test_범위_밖_effort는_자식을_띄우기_전에_종료_코드_2이고_허용_수준을_이유에_적는다(self):
        """범위 위(max), 범위 아래(medium), 모르는 값, 범위가 없는 항목의 다른 값은 모두 종료 코드 2이고 허용 수준을 알려준다."""
        # Given
        instructions = ["--instructions", str(self.instructions)]
        cases = [
            (["scout", "--effort", "max"], "high or xhigh"),
            (["scout", "--effort", "medium"], "high or xhigh"),
            (["scout", "--effort", "turbo"], "high or xhigh"),
            (["investigation", "--host", "codex", "--fallback", "--effort", "high", *instructions], "use medium"),
        ]
        for arguments, allowed in cases:
            with self.subTest(arguments=arguments):
                # When
                completed = self.run_runner(*arguments)

                # Then
                self.assertEqual(2, completed.returncode, completed.stderr)
                self.assertIn(allowed, completed.stderr)
                self.assertFalse(self.log.exists())

    def test_max_effort가_없는_항목은_자기_effort를_명시해도_통과한다(self):
        """investigation의 Codex 호스트 대체는 범위가 없는 medium 항목이므로 --effort medium만 통과한다."""
        # Given
        arguments = ["investigation", "--host", "codex", "--fallback", "--effort", "medium", "--instructions", str(self.instructions)]
        config = {"model": "claude-sonnet-5-5", "entries": [{"model": "claude-sonnet-5-5", "effort": "medium"}]}

        # When
        completed = self.run_runner(*arguments, config=config)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.claude_argv(model="claude-sonnet-5-5", effort="medium"), self.logged()["argv"])

    def test_허용_수준은_효과_규칙과의_교집합이다(self):
        """모델의 효과 규칙이 high만 허용하면 xhigh까지 열린 항목이어도 --effort xhigh는 UsageError이고 high만 안내한다."""
        # Given
        argv = [
            "reviewer", "--model", "claude-opus-5-5", "--effort", "xhigh",
            "--assignment", str(self.assignment), "--result", str(self.result),
        ]
        parsed = role_runner.build_parser().parse_args(argv)

        # When
        with mock.patch.dict(role_runner.REGISTRY["effort_rules"], {"claude-opus-5-5": ["high"]}):
            with self.assertRaises(role_runner.UsageError) as caught:
                role_runner.plan(parsed)

        # Then
        self.assertIn("use high", str(caught.exception))

    def test_읽기_전용_두_쌍은_자식을_동시에_시작하고_상태_줄_둘을_찍는다(self):
        """scout에 쌍 둘을 주면 두 자식의 exec가 겹쳐 시작되고, 상태 줄 둘과 결과 파일 둘이 남는다."""
        # Given
        pairs = self.pair_args("A", "B")

        # When
        completed = self.run_runner("scout", *pairs, assignment=False, result=False, config={"sleep": 0.5})

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        executions = self.executions()
        self.assertEqual(2, len(executions))
        self.assertNotIn("resume", [item for call in executions for item in call["argv"]])
        self.assertEqual(2, len(self.app_server_calls()))
        starts = [call["started"] for call in executions]
        self.assertLess(max(starts) - min(starts), 0.5)
        self.assertEqual({True}, {line["verified"] for line in self.status_lines(completed)})
        self.assertEqual(2, len(self.status_lines(completed)))
        self.assertEqual(["codex answer"] * 2, [(self.base / f"result-{name}.md").read_text() for name in "AB"])
        prompts = [call["stdin"] for call in executions]
        self.assertEqual({"A", "B"}, {name for name in "AB" if any(f"ASSIGN_{name}" in prompt for prompt in prompts)})

    def test_배치의_종료_코드는_쌍_가운데_가장_큰_값이고_상태_줄은_입력_순서다(self):
        """첫 쌍이 실행 오류(3), 둘째 쌍이 답변 없음(4)이면 종료 코드는 4이고 상태 줄은 입력 순서로 3, 4이다."""
        # Given
        pairs = self.pair_args("A", "B")
        config = {"exit_when": {"ASSIGN_A": 1}, "no_answer_when": ["ASSIGN_B"]}

        # When
        completed = self.run_runner("scout", *pairs, assignment=False, result=False, config=config)

        # Then
        self.assertEqual(4, completed.returncode, completed.stderr)
        self.assertEqual([3, 4], [line["exit"] for line in self.status_lines(completed)])
        self.assertEqual([False, False], [line["verified"] for line in self.status_lines(completed)])

    def run_in_process(self, argv, failing_result):
        """Run the runner in this process with the fake CLIs, and make discarding the result named failing_result raise OSError."""
        environment = {
            "PATH": str(self.bin), "HOME": str(self.base), "CODEX_HOME": str(self.codex_home),
            "CLAUDE_CONFIG_DIR": str(self.claude_home), "XDG_STATE_HOME": str(self.state_home),
            "FAKE_LOG": str(self.log), "FAKE_CONFIG": json.dumps({}),
        }
        original = role_runner.discard

        def discard(path):
            if Path(path).name == failing_result:
                raise PermissionError("result is locked")
            original(path)

        output, errors = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, environment, clear=True), mock.patch.object(role_runner, "discard", discard):
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                code = role_runner.main(argv)
        lines = [json.loads(line) for line in output.getvalue().strip().splitlines()]
        return code, lines, errors.getvalue()

    def test_한_쌍의_결과_파일_처리에서_OSError가_나도_배치는_나머지_쌍의_상태_줄을_찍고_종료_코드_3이다(self):
        """한 쌍의 결과 파일을 지우다 OSError가 나면 그 쌍만 종료 코드 3 상태 줄과 stderr 오류가 되고 다른 쌍은 검증 성공으로 끝난다."""
        # Given
        argv = ["scout", *self.pair_args("A", "B")]

        # When
        code, lines, errors = self.run_in_process(argv, "result-B.md")

        # Then
        self.assertEqual(3, code)
        self.assertEqual([0, 3], [line["exit"] for line in lines])
        self.assertEqual([True, False], [line["verified"] for line in lines])
        self.assertIn("result is locked", errors)
        self.assertEqual("codex answer", (self.base / "result-A.md").read_text())

    def test_한_쌍만_줄_때도_결과_파일_OSError는_종료_코드_3_상태_줄이다(self):
        """쌍이 하나여도 결과 파일 처리 OSError는 예외로 새지 않고 종료 코드 3 상태 줄과 stderr 오류가 된다."""
        # Given
        argv = ["scout", *self.pair_args("A")]

        # When
        code, lines, errors = self.run_in_process(argv, "result-A.md")

        # Then
        self.assertEqual(3, code)
        self.assertEqual([(3, False)], [(line["exit"], line["verified"]) for line in lines])
        self.assertIn("result is locked", errors)

    def test_읽기_전용_Claude_reviewer도_쌍_여럿을_받는다(self):
        """reviewer를 Claude 모델로 실행할 때도 쌍 둘이 각각 claude 자식 하나씩으로 실행되고 종료 코드 0이다."""
        # Given
        pairs = self.pair_args("A", "B")

        # When
        completed = self.run_runner("reviewer", "--model", "claude-opus-5-5", *pairs, assignment=False, result=False)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(["claude", "claude"], [call["name"] for call in self.calls()])
        self.assertEqual(2, len(self.status_lines(completed)))

    def test_쓰기_대상과_잘못된_쌍은_자식을_띄우기_전에_종료_코드_2이다(self):
        """쓰기 대상, 개수 불일치, 일곱 쌍, 결과 중복, 결과와 같은 assignment, 쌍 둘과 --resume은 자식 없이 종료 코드 2이다."""
        # Given
        approved = str(self.base / "approved")
        instructions = ["--instructions", str(self.instructions)]
        two = self.pair_args("A", "B")
        shared = str(self.base / "result-shared.md")
        duplicate = [two[0], two[1], two[2], two[1]]
        crossed = [two[0], two[1], two[2], two[0]]
        cases = {
            "worker": (["worker", "--add-dir", approved, *two], "read-only"),
            "writing capability": (["implementation", "--host", "codex", "--add-dir", approved, *instructions, *two], "read-only"),
            "writing agent": (["agent", "--name", "hei5enbug-agent-setup:worker", "--fallback", "--add-dir", approved, *two], "read-only"),
            "unequal counts": (["scout", "--assignment", two[1], "--assignment", two[5], "--result", two[3]], "equal numbers"),
            "seven pairs": (["scout", *self.pair_args(*"ABCDEFG")], "At most 6"),
            "duplicate result": (["scout", *duplicate], "different file"),
            "assignment equals result": (["scout", "--assignment", two[1], "--result", two[3], "--assignment", two[3], "--result", shared], "different files"),
            "resume": (["scout", "--resume", THREAD, *two], "--resume"),
        }
        for label, (arguments, reason) in cases.items():
            with self.subTest(case=label):
                # When
                completed = self.run_runner(*arguments, assignment=False, result=False)

                # Then
                self.assertEqual(2, completed.returncode, completed.stderr)
                self.assertIn(reason, completed.stderr)
                self.assertFalse(self.log.exists())

    def test_읽기_전용_Codex_명령은_exec에_스킬_목록_끄기를_넘긴다(self):
        """scout의 assignment exec는 -c skills.max_context_tokens=1을 넘기고 MCP 목록 조회는 넘기지 않는다."""
        # Given
        arguments = ["scout"]

        # When
        completed = self.run_runner(*arguments)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        (execution,) = self.executions()
        argv = execution["argv"]
        self.assertEqual("-c", argv[argv.index("skills.max_context_tokens=1") - 1])
        listing = self.calls()[0]["argv"]
        self.assertNotIn("skills.max_context_tokens=1", listing)

    def test_쓰기_Codex_명령은_스킬_목록_끄기를_넘기지_않는다(self):
        """worker는 쓰기 실행이므로 assignment exec에 skills.max_context_tokens를 넘기지 않는다."""
        # Given
        arguments = ["worker", "--add-dir", str(self.base)]

        # When
        completed = self.run_runner(*arguments)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        for call in self.executions():
            self.assertNotIn("skills.max_context_tokens=1", call["argv"])

    def test_읽기_전용_Claude_명령은_슬래시_명령_끄기를_넘긴다(self):
        """읽기 전용 reviewer의 claude -p 명령은 --disable-slash-commands를 넘긴다."""
        # Given
        arguments = ["reviewer", "--model", "claude-opus-5-5"]

        # When
        completed = self.run_runner(*arguments)

        # Then
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("--disable-slash-commands", self.logged()["argv"])

    def test_쓰기_Claude_명령은_슬래시_명령_끄기를_넘기지_않는다(self):
        """쓰기 worker의 claude -p 명령은 --disable-slash-commands를 넘기지 않는다."""
        # Given
        directory = self.base / "one"
        directory.mkdir()

        # When
        code, _ = self.run_claude_worker(["worker", "--add-dir", str(directory)])

        # Then
        self.assertEqual(0, code)
        self.assertNotIn("--disable-slash-commands", self.logged()["argv"])

    def run_claude_worker(self, arguments, config=None):
        """Run the name-only worker role on the Claude path by pinning the role model to Claude, in this process."""
        argv = [*arguments, "--assignment", str(self.assignment), "--result", str(self.result)]
        environment = {
            "PATH": str(self.bin), "HOME": str(self.base), "CODEX_HOME": str(self.codex_home),
            "CLAUDE_CONFIG_DIR": str(self.claude_home), "XDG_STATE_HOME": str(self.state_home),
            "FAKE_LOG": str(self.log), "FAKE_CONFIG": json.dumps(config or {"model": "claude-haiku-5-5"}),
        }
        output = io.StringIO()
        with mock.patch.dict(os.environ, environment, clear=True), mock.patch.object(role_runner, "ROLE_MODEL", "claude-haiku-5-5"):
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                code = role_runner.main(argv)
        return code, output.getvalue()

    def test_Claude_worker_역할은_dontAsk와_add_dir_편집_규칙만_쓴다(self):
        """이름만 주는 worker 역할의 Claude 경로는 acceptEdits와 맨 Edit·Write 대신 dontAsk와 디렉터리별 Edit 규칙을 쓴다."""
        # Given
        directories = [self.base / "one", self.base / "two"]
        for directory in directories:
            directory.mkdir()
        arguments = ["worker", "--add-dir", str(directories[0]), "--add-dir", str(directories[1])]

        # When
        code, _ = self.run_claude_worker(arguments)

        # Then
        self.assertEqual(0, code)
        argv = self.logged()["argv"]
        self.assertEqual(
            ["-p", "--model", "claude-haiku-5-5", "--effort", "high", "--output-format", "json",
               "--tools", "Read", "Grep", "Glob", "Bash", "Edit", "Write", "--strict-mcp-config",
               "--permission-mode", "dontAsk", "--allowedTools", "Read", "Grep", "Glob", "Bash",
               *[f"Edit(/{item.resolve().as_posix()}/**)" for item in directories],
               "--add-dir", str(directories[0]), "--add-dir", str(directories[1])],
            argv,
        )
        self.assertNotIn("acceptEdits", argv)
        self.assertNotIn("Edit", allowed_rules(argv))
        self.assertNotIn("Write", allowed_rules(argv))

    def test_Claude_worker_역할은_add_dir_없이는_종료_코드_2이다(self):
        """쓰는 역할의 Claude 경로가 --add-dir 없이 호출되면 자식을 띄우지 않고 사용 오류로 끝난다."""
        # When
        code, output = self.run_claude_worker(["worker"])

        # Then
        self.assertEqual(2, code)
        self.assertFalse(self.log.exists())
        self.assertEqual(2, json.loads(output.strip().splitlines()[-1])["exit"])


if __name__ == "__main__":
    unittest.main()
