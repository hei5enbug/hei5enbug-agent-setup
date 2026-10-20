import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "scripts" / "hook_python.sh"
LAUNCHER_COMMAND = re.compile(r'sh "\$\{CLAUDE_PLUGIN_ROOT\}/scripts/hook_python\.sh" ([a-z_]+\.py)')
SYSTEM_PATH = "/usr/bin:/bin"
EXPECTED_HOOKS = [
    ("SessionStart", None, "session_context.py", 10, False),
    ("SubagentStart", None, "session_context.py", 10, False),
    ("PreToolUse", "Agent|Task", "agent_guard.py", 5, False),
    ("PreToolUse", "^(Bash|Read|Edit|Write|MultiEdit|NotebookEdit|apply_patch|mcp__.*)$", "approval_guard.py", 10, False),
    ("PreToolUse", "^mcp__datagrip__execute_sql_query$", "datagrip_guard.py", 10, False),
    ("PermissionRequest", "^(Bash|Read|Edit|Write|MultiEdit|NotebookEdit|apply_patch|mcp__.*)$", "approval_guard.py", 10, False),
    ("PermissionRequest", "^mcp__datagrip__execute_sql_query$", "datagrip_guard.py", 10, False),
    ("PostToolUse", None, "language_guard.py", 5, True),
    ("PostToolUse", "^(Bash|Read|Edit|Write|MultiEdit|NotebookEdit|apply_patch|mcp__.*)$", "approval_guard.py", 10, False),
    ("PostToolUseFailure", "^(Bash|Read|Edit|Write|MultiEdit|NotebookEdit|apply_patch|mcp__.*)$", "approval_guard.py", 10, False),
    ("UserPromptSubmit", None, "approval_guard.py", 5, False),
    ("UserPromptSubmit", None, "session_context.py", 5, False),
    ("Stop", None, "language_guard.py", 5, False),
]


def fake_interpreter(path, label, exit_code=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/bin/sh\necho "{label} $*"\ncat\nexit {exit_code}\n', encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture
def plugin(tmp_path):
    scripts = tmp_path / "plugin" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(LAUNCHER, scripts / "hook_python.sh")
    (scripts / "sample.py").write_text("", encoding="utf-8")
    (scripts / "notes.txt").write_text("", encoding="utf-8")
    fake_interpreter(tmp_path / "bin" / "python3", "path-python3")
    return scripts


def launch(plugin, *args, stdin="", **env):
    environment = {"PATH": f"{plugin.parents[1] / 'bin'}:{SYSTEM_PATH}", **env}
    return subprocess.run(
        ["/bin/sh", str(plugin / "hook_python.sh"), *args], input=stdin, text=True, capture_output=True,
        env=environment, timeout=30, cwd=plugin.parents[1],
    )


def test_Claude_옵션의_인터프리터가_실행_가능하면_그_인터프리터로_스크립트를_실행한다(plugin, tmp_path):
    # given
    interpreter = fake_interpreter(tmp_path / "custom" / "python", "option")
    # when
    result = launch(plugin, "sample.py", "one", CLAUDE_PLUGIN_OPTION_PYTHON=str(interpreter))
    # then
    assert result.returncode == 0
    assert result.stdout.splitlines()[0] == f"option {plugin / 'sample.py'} one"


def test_Claude_옵션이_비어_있으면_HEI5ENBUG_PYTHON의_인터프리터를_쓴다(plugin, tmp_path):
    # given
    interpreter = fake_interpreter(tmp_path / "codex" / "python", "codex")
    # when
    result = launch(plugin, "sample.py", CLAUDE_PLUGIN_OPTION_PYTHON="", HEI5ENBUG_PYTHON=str(interpreter))
    # then
    assert result.stdout.splitlines()[0] == f"codex {plugin / 'sample.py'}"


def test_두_값이_모두_있으면_Claude_옵션이_HEI5ENBUG_PYTHON보다_먼저다(plugin, tmp_path):
    # given
    option = fake_interpreter(tmp_path / "a" / "python", "option")
    codex = fake_interpreter(tmp_path / "b" / "python", "codex")
    # when
    result = launch(plugin, "sample.py", CLAUDE_PLUGIN_OPTION_PYTHON=str(option), HEI5ENBUG_PYTHON=str(codex))
    # then
    assert result.stdout.startswith("option ")


@pytest.mark.parametrize("kind", ["missing", "directory", "not_executable"])
def test_존재하지_않거나_실행할_수_없는_경로는_조용히_python3으로_대체한다(plugin, tmp_path, kind):
    # given
    invalid = tmp_path / "invalid"
    if kind == "directory":
        invalid.mkdir()
    elif kind == "not_executable":
        invalid.write_text("#!/bin/sh\necho invalid\n", encoding="utf-8")
        invalid.chmod(0o644)
    # when
    result = launch(plugin, "sample.py", CLAUDE_PLUGIN_OPTION_PYTHON=str(invalid))
    # then
    assert result.returncode == 0
    assert result.stdout.splitlines()[0] == f"path-python3 {plugin / 'sample.py'}"
    assert result.stderr == ""


def test_Claude_옵션이_유효하지_않아도_유효한_HEI5ENBUG_PYTHON이_있으면_그것을_쓴다(plugin, tmp_path):
    # given
    codex = fake_interpreter(tmp_path / "codex" / "python", "codex")
    # when
    result = launch(plugin, "sample.py", CLAUDE_PLUGIN_OPTION_PYTHON="/nonexistent/python", HEI5ENBUG_PYTHON=str(codex))
    # then
    assert result.stdout.startswith("codex ")


def test_값이_없으면_PATH의_python3으로_실행한다(plugin):
    # given
    arguments = ("sample.py", "x y")
    # when
    result = launch(plugin, *arguments)
    # then
    assert result.stdout.splitlines()[0] == f"path-python3 {plugin / 'sample.py'} x y"


@pytest.mark.parametrize("script", [
    "", "../sample.py", "sub/sample.py", "/abs/sample.py", "-c", "-sample.py", ".hidden.py", "notes.txt", "missing.py",
    "sample.py.bak", "sample", "bad name.py", "$(id).py",
])
def test_같은_폴더의_py_파일이_아닌_첫_인자는_종료_코드_1로_거부하고_아무것도_실행하지_않는다(plugin, tmp_path, script):
    # given
    marker = tmp_path / "ran"
    fake_interpreter(tmp_path / "custom" / "python", "option")
    (tmp_path / "custom" / "python").write_text(f'#!/bin/sh\ntouch "{marker}"\n', encoding="utf-8")
    # when
    result = launch(plugin, script, CLAUDE_PLUGIN_OPTION_PYTHON=str(tmp_path / "custom" / "python"))
    # then
    assert result.returncode == 1
    assert result.stdout == ""
    assert "hook_python.sh" in result.stderr
    assert not marker.exists()


def test_인자가_없으면_종료_코드_1로_거부한다(plugin):
    # given
    arguments = ()
    # when
    result = launch(plugin, *arguments)
    # then
    assert result.returncode == 1
    assert result.stdout == ""


def test_표준_입력과_종료_코드를_그대로_전달한다(plugin, tmp_path):
    # given
    interpreter = fake_interpreter(tmp_path / "custom" / "python", "option", exit_code=7)
    payload = json.dumps({"hook_event_name": "PreToolUse"})
    # when
    result = launch(plugin, "sample.py", stdin=payload, CLAUDE_PLUGIN_OPTION_PYTHON=str(interpreter))
    # then
    assert result.returncode == 7
    assert result.stdout.splitlines()[1] == payload


def test_종료_코드_2도_바꾸지_않고_전달한다(plugin, tmp_path):
    # given
    interpreter = fake_interpreter(tmp_path / "custom" / "python", "option", exit_code=2)
    # when
    result = launch(plugin, "sample.py", CLAUDE_PLUGIN_OPTION_PYTHON=str(interpreter))
    # then
    assert result.returncode == 2


def test_실제_훅_스크립트를_옵션_인터프리터와_존재하지_않는_경로_모두에서_성공적으로_실행한다(tmp_path):
    # given
    event = json.dumps({"hook_event_name": "Stop", "session_id": "s", "last_assistant_message": "done"})
    isolated = {"HOME": str(tmp_path / "home"), "XDG_STATE_HOME": str(tmp_path / "state"), "PATH": os.environ["PATH"]}
    command = ["sh", str(LAUNCHER), "language_guard.py"]
    # when
    with_option = subprocess.run(command, input=event, text=True, capture_output=True, timeout=60,
                                 env={**isolated, "CLAUDE_PLUGIN_OPTION_PYTHON": shutil.which("python3")})
    with_invalid = subprocess.run(command, input=event, text=True, capture_output=True, timeout=60,
                                  env={**isolated, "CLAUDE_PLUGIN_OPTION_PYTHON": "/nonexistent/python"})
    # then
    assert with_option.returncode == 0, with_option.stderr
    assert with_invalid.returncode == 0, with_invalid.stderr
    assert with_option.stdout == with_invalid.stdout


def test_hooks_json의_모든_명령이_런처_형식이고_이벤트_matcher_timeout_async가_그대로다():
    # given
    hooks = json.loads((REPO_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    # when
    entries = [
        (event, group.get("matcher"), LAUNCHER_COMMAND.fullmatch(handler["command"]), handler["timeout"],
         handler.get("async", False))
        for event, groups in hooks.items() for group in groups for handler in group["hooks"]
    ]
    # then
    assert all(entry[2] is not None for entry in entries)
    assert [(e, m, s[1], t, a) for e, m, s, t, a in entries] == EXPECTED_HOOKS
    assert all((REPO_ROOT / "scripts" / script).is_file() for _, _, script, _, _ in EXPECTED_HOOKS)


def test_hooks_json은_python3을_직접_부르는_명령을_더_이상_담지_않는다():
    # given
    text = (REPO_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8")
    # when
    direct = re.findall(r'"command":\s*"python3', text)
    # then
    assert direct == []


def test_런처는_실행_권한이_있는_POSIX_sh_스크립트다():
    # given
    mode = LAUNCHER.stat().st_mode
    # when
    first_line = LAUNCHER.read_text(encoding="utf-8").splitlines()[0]
    syntax = subprocess.run(["sh", "-n", str(LAUNCHER)], capture_output=True, text=True, timeout=30)
    # then
    assert mode & stat.S_IXUSR
    assert first_line == "#!/bin/sh"
    assert syntax.returncode == 0, syntax.stderr


def test_플러그인_매니페스트는_python_옵션을_빈_문자열_기본값의_문자열로_선언한다():
    # given
    manifest = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    # when
    option = manifest["userConfig"]["python"]
    # then
    assert option["type"] == "string"
    assert option["default"] == ""
    assert "options" not in option
    assert option["title"] and option["description"]


@pytest.mark.parametrize("value", ["py312", "./custom/python", "custom/python"])
def test_슬래시로_시작하지_않는_상대_값은_현재_폴더에_실행_파일이_있어도_python3으로_대체한다(plugin, tmp_path, value):
    # given
    fake_interpreter(tmp_path / "py312", "relative")
    fake_interpreter(tmp_path / "custom" / "python", "relative")
    # when
    option = launch(plugin, "sample.py", CLAUDE_PLUGIN_OPTION_PYTHON=value)
    codex = launch(plugin, "sample.py", HEI5ENBUG_PYTHON=value)
    # then
    assert option.returncode == 0 and codex.returncode == 0
    assert option.stdout.splitlines()[0] == f"path-python3 {plugin / 'sample.py'}"
    assert codex.stdout.splitlines()[0] == f"path-python3 {plugin / 'sample.py'}"


def test_Claude_옵션이_상대_값이어도_유효한_절대_경로의_HEI5ENBUG_PYTHON이_있으면_그것을_쓴다(plugin, tmp_path):
    # given
    fake_interpreter(tmp_path / "py312", "relative")
    codex = fake_interpreter(tmp_path / "codex" / "python", "codex")
    # when
    result = launch(plugin, "sample.py", CLAUDE_PLUGIN_OPTION_PYTHON="py312", HEI5ENBUG_PYTHON=str(codex))
    # then
    assert result.stdout.startswith("codex ")
