import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import hook_runtime  # noqa: E402

LAUNCHER = SCRIPTS / "hook_python.sh"
LAUNCHER_COMMAND = re.compile(r'sh "\$\{CLAUDE_PLUGIN_ROOT\}/scripts/hook_python\.sh" ([a-z_]+\.py)')
PROJECT_COMMANDS = (".claude/settings.json", ".codex/hooks.json")
PLUGIN = "hei5enbug-agent-setup"


def registrations(path):
    hooks = json.loads(Path(path).read_text(encoding="utf-8"))["hooks"]
    return [(event, handler["command"], handler["timeout"])
            for event, groups in hooks.items() for group in groups for handler in group["hooks"]]


def plugin_registrations():
    found = []
    for name in ("hooks.json", "codex-hooks.json", "claude-hooks.json"):
        for event, command, timeout in registrations(REPO_ROOT / "hooks" / name):
            found.append((LAUNCHER_COMMAND.fullmatch(command)[1], event, timeout))
    return found


def run_driver(code, event, env=None, timeout=30):
    environment = {"PATH": os.environ["PATH"], "HOME": "/nonexistent", **(env or {})}
    start = time.monotonic()
    result = subprocess.run([sys.executable, "-c", code], input=json.dumps(event), text=True, capture_output=True,
                            env=environment, timeout=timeout)
    return result, time.monotonic() - start


def driver_code(module, patch, script):
    return (
        f"import sys, time\nsys.path.insert(0, {str(SCRIPTS)!r})\nimport {module} as m, hook_runtime\n{patch}\n"
        f"sys.exit(hook_runtime.run({script!r}, m.main))\n"
    )


def test_선언된_시간표는_모든_훅_파일의_등록_timeout과_일치한다():
    # given
    found = plugin_registrations()
    # when
    mismatched = [(script, event) for script, event, timeout in found
                  if hook_runtime.DECLARED_TIMEOUTS.get((script, event)) != timeout]
    unregistered = [key for key in hook_runtime.DECLARED_TIMEOUTS
                    if key[0] != hook_runtime.PROJECT_HOOK and (key[0], key[1]) not in {(s, e) for s, e, _ in found}]
    # then
    assert mismatched == []
    assert unregistered == []


@pytest.mark.parametrize("path", PROJECT_COMMANDS)
def test_프로젝트_훅의_timeout은_시간표의_프로젝트_훅_값과_같다(path):
    # given
    entries = registrations(REPO_ROOT / path)
    # when
    timeouts = {timeout for _, _, timeout in entries}
    # then
    assert timeouts == {hook_runtime.DECLARED_TIMEOUTS[(hook_runtime.PROJECT_HOOK, "PreToolUse")]}


@pytest.mark.parametrize("path", PROJECT_COMMANDS)
def test_프로젝트_훅_명령은_python3을_직접_부르지_않고_자식_프로세스도_시작하지_않는다(path):
    # given
    commands = [command for _, command, _ in registrations(REPO_ROOT / path)]
    # when
    direct = [command for command in commands if "python3" in command]
    spawning = [command for command in commands if "rev-parse" in command or "$(" in command]
    # then
    assert direct == []
    assert spawning == []


def test_시간이_다_된_훅은_거부_가능한_이벤트에서만_거부하고_나머지는_출력_없이_끝난다():
    # given
    cases = [
        ("approval_guard.py", "PreToolUse"), ("approval_guard.py", "PermissionRequest"),
        ("orca_placement_hook.py", "PreToolUse"), ("agent_guard.py", "PreToolUse"),
        ("datagrip_guard.py", "PreToolUse"),
    ]
    silent = [
        ("approval_guard.py", "PostToolUse"), ("approval_guard.py", "UserPromptSubmit"),
        ("language_guard.py", "Stop"), ("final_report_hook.py", "Stop"), ("orca_status_hook.py", "Stop"),
        ("required_checks_hook.py", "PreToolUse"), ("session_context.py", "SessionStart"),
    ]
    # when
    denied = [hook_runtime.timeout_result(script, event, 2.5) for script, event in cases]
    skipped = [hook_runtime.timeout_result(script, event, 2.5) for script, event in silent]
    # then
    assert all(text and code == 0 for text, _, code in denied)
    assert skipped == [("", "", 0)] * len(silent)


def test_허가_요청의_시간_초과_거부는_결정_형식으로_이유에_플러그인과_훅과_바쁨과_재시도를_담는다():
    # given
    event = "PermissionRequest"
    # when
    text, error, code = hook_runtime.timeout_result("approval_guard.py", event, 5)
    # then
    decision = json.loads(text)["hookSpecificOutput"]
    assert decision["hookEventName"] == event and decision["decision"]["behavior"] == "deny"
    message = decision["decision"]["message"]
    assert PLUGIN in message and "approval guard" in message and "machine is busy" in message
    assert "within 5 seconds" in message and "Retry after the load drops" in message
    assert "timed out after" not in message
    assert (error, code) == ("", 0)


def test_공개_경계_훅의_시간_초과는_종료_코드_2와_표준_오류의_이유로_막는다():
    # given
    script = "public_boundary_hook.py"
    # when
    text, error, code = hook_runtime.timeout_result(script, "PreToolUse", 15)
    # then
    assert text == "" and code == 2
    assert PLUGIN in error and "public boundary hook" in error and "machine is busy" in error


def test_Linux_proc_값으로_프로세스_시작_시각을_부팅_시각과_틱에서_계산한다():
    # given
    stat_text = "1234 (py (x) thon) S " + " ".join(["0"] * 18 + ["500"]) + " 0 0\n"
    # when
    started = hook_runtime.linux_start(stat_text, "100.00 50.00\n", 1000.0, 100)
    # then
    assert started == 905.0
    assert hook_runtime.linux_start("garbage", "100.0", 1000.0, 100) is None


def test_시작_시각_변수가_최근이면_그_값을_쓰고_오래됐거나_깨졌으면_쓰지_않는다(monkeypatch):
    # given
    now = 1_000_000.0
    # when
    recent = _started(monkeypatch, "999998.5", now)
    stale = _started(monkeypatch, "999000.0", now)
    broken = _started(monkeypatch, "soon", now)
    future = _started(monkeypatch, "1000005.0", now)
    # then
    assert recent == 999998.5
    assert stale != 999000.0 and broken != "soon"
    assert future == now


def _started(monkeypatch, value, now):
    monkeypatch.setenv(hook_runtime.STARTED_AT, value)
    monkeypatch.setattr(hook_runtime, "process_start", lambda _now: None)
    return hook_runtime.started_at(now)


def test_필수_검사_훅은_단계가_절반_시간을_넘기면_출력_없이_종료_코드_0으로_끝난다():
    # given
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "git push origin demo-a"}}
    code = driver_code("required_checks_hook", "m.runs_commit_or_push = lambda command: time.sleep(30)",
                       "required_checks_hook.py")
    environment = {hook_runtime.STARTED_AT: repr(time.time())}
    # when
    result, elapsed = run_driver(code, event, environment)
    # then
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert elapsed < 2.5 + 1.0


def test_언어_가드의_Stop은_단계가_절반_시간을_넘기면_출력_없이_종료_코드_0으로_끝난다():
    # given
    event = {"hook_event_name": "Stop", "session_id": "s", "last_assistant_message": "done"}
    code = driver_code("language_guard", "m.handle = lambda event: time.sleep(30)", "language_guard.py")
    # when
    result, elapsed = run_driver(code, event, {hook_runtime.STARTED_AT: repr(time.time())})
    # then
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert elapsed < 2.5 + 1.0


def test_이미_시간이_지난_뒤_시작한_훅은_본문을_실행하지_않고_바로_시간_초과_결과를_낸다(tmp_path):
    # given
    marker = tmp_path / "ran"
    event = {"hook_event_name": "PermissionRequest", "tool_name": "Bash"}
    code = (
        f"import sys\nsys.path.insert(0, {str(SCRIPTS)!r})\nimport hook_runtime\n"
        f"def main():\n    open({str(marker)!r}, 'w').close()\n    return 0\n"
        "sys.exit(hook_runtime.run('approval_guard.py', main))\n"
    )
    # when
    result, elapsed = run_driver(code, event, {hook_runtime.STARTED_AT: repr(time.time() - 60)})
    # then
    assert not marker.exists()
    assert result.returncode == 0 and elapsed < 2.5
    assert json.loads(result.stdout)["hookSpecificOutput"]["decision"]["behavior"] == "deny"


def test_타이머를_설정하지_못하면_본문을_실행하지_않고_추적_정보_없이_시간_초과_결과를_낸다(tmp_path):
    # given
    marker = tmp_path / "ran"
    event = {"hook_event_name": "PermissionRequest", "tool_name": "Bash"}
    code = (
        f"import sys, signal\nsys.path.insert(0, {str(SCRIPTS)!r})\nimport hook_runtime\n"
        "def broken(*args):\n    raise OSError('no timer')\n"
        "signal.setitimer = broken\n"
        f"def main():\n    open({str(marker)!r}, 'w').close()\n    return 0\n"
        "sys.exit(hook_runtime.run('approval_guard.py', main))\n"
    )
    # when
    result, _ = run_driver(code, event)
    # then
    assert not marker.exists() and "Traceback" not in result.stderr
    assert result.returncode == 0
    assert json.loads(result.stdout)["hookSpecificOutput"]["decision"]["behavior"] == "deny"


def test_본문이_시간_안에_끝나면_출력과_종료_코드를_그대로_전달하고_표준_입력을_읽을_수_있다():
    # given
    event = {"hook_event_name": "Stop", "x": 1}
    code = (
        f"import sys\nsys.path.insert(0, {str(SCRIPTS)!r})\nimport hook_runtime, json\n"
        "def main():\n    print(json.dumps(json.load(sys.stdin)))\n    print('note', file=sys.stderr)\n    return 3\n"
        "sys.exit(hook_runtime.run('language_guard.py', main))\n"
    )
    # when
    result, _ = run_driver(code, event)
    # then
    assert json.loads(result.stdout) == event
    assert (result.stderr, result.returncode) == ("note\n", 3)


def _stub_orca(tmp_path, marker):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "orca"
    stub.write_text(f"#!/bin/sh\necho called >> '{marker}'\nexec sleep 20\n", encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    return bin_dir


def test_Orca_배치_훅은_orca_호출이_절반_시간을_넘기면_바쁨_거부를_절반_시간_안에_낸다(tmp_path):
    # given
    marker = tmp_path / "marker"
    bin_dir = _stub_orca(tmp_path, marker)
    command = "orca worktree set --worktree demo-a --display-name demo-title"
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
             "cwd": str(tmp_path)}
    environment = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HEI5ENBUG_PYTHON": sys.executable,
                   "HOME": str(tmp_path / "home")}
    start = time.monotonic()
    # when
    result = subprocess.run(["sh", str(LAUNCHER), "orca_placement_hook.py"], input=json.dumps(event), text=True,
                            capture_output=True, env=environment, timeout=30, cwd=tmp_path)
    elapsed = time.monotonic() - start
    # then
    assert marker.exists()
    assert result.returncode == 0 and elapsed < 2.5 + 1.0
    output = json.loads(result.stdout)["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    reason = output["permissionDecisionReason"]
    assert PLUGIN in reason and "Orca placement hook" in reason and "machine is busy" in reason
    assert "Retry after the load drops" in reason and "timed out after" not in reason


FAILING = [
    ("required_checks_hook", "runs_commit_or_push", "required checks hook", "PreToolUse",
     {"tool_name": "Bash", "tool_input": {"command": "git push origin demo-a"}}, {}),
    ("orca_placement_hook", "texts_to_check", "Orca placement hook", "PreToolUse",
     {"tool_name": "Bash", "tool_input": {"command": "orca worktree create --no-parent"}}, {}),
    ("agent_guard", "denial", "agent guard", "PreToolUse", {"tool_name": "Agent", "tool_input": {}},
     {"PLUGIN_ROOT": str(REPO_ROOT)}),
    ("language_guard", "handle", "language guard", "Stop", {"last_assistant_message": "done"}, {}),
    ("final_report_hook", "decide", "final report hook", "Stop", {"last_assistant_message": "done"}, {}),
    ("orca_status_hook", "handle", "Orca status hook", "Stop", {}, {"ORCA_TERMINAL_HANDLE": "term_demo"}),
    ("approval_guard", "handle", "approval guard", "UserPromptSubmit", {"prompt": "hello", "session_id": "s"}, {}),
    ("datagrip_guard", "handle", "DataGrip guard", "PreToolUse",
     {"tool_name": "mcp__datagrip__execute_sql_query", "tool_input": {}, "session_id": "s"}, {}),
]


@pytest.mark.parametrize(("module", "attribute", "title", "event_name", "fields", "env"), FAILING)
def test_내부_오류가_나면_플러그인과_훅과_건너뛴_일을_알리는_한_줄을_내고_추적_정보는_내지_않는다(
        module, attribute, title, event_name, fields, env):
    # given
    event = {"hook_event_name": event_name, **fields}
    patch = f"def boom(*a, **k):\n    raise RuntimeError('detail')\nm.{attribute} = boom"
    script = f"{module}.py"
    # when
    result, _ = run_driver(driver_code(module, patch, script), event, env)
    # then
    assert result.returncode in (0, 1)
    assert "Traceback" not in result.stderr and "detail" not in result.stderr
    assert result.stderr.count("\n") == 1
    assert PLUGIN in result.stderr and title in result.stderr and "RuntimeError" in result.stderr
    assert "so it " in result.stderr and "Run the step again" in result.stderr


def test_세션_맥락_훅이_입력을_읽지_못하면_플러그인과_훅과_다음_단계를_알린다():
    # given
    event = {"hook_event_name": "Unknown"}
    # when
    result = subprocess.run([sys.executable, str(SCRIPTS / "session_context.py")], input=json.dumps(event),
                            text=True, capture_output=True, timeout=30)
    # then
    assert result.returncode == 1 and "Traceback" not in result.stderr
    assert PLUGIN in result.stderr and "session context hook" in result.stderr
    assert "instructions were not loaded" in result.stderr and "start a new session" in result.stderr


def test_승인_가드의_분류_실패_사유는_플러그인과_승인_가드를_밝히고_다음_단계를_말한다():
    # given
    import approval_state
    # when
    reason = approval_state.FAILURE_REASON
    # then
    assert reason.startswith(PLUGIN + " approval guard") and "failed" in reason
    assert "approve only if the call looks right" in reason
    assert len(reason) < 82
