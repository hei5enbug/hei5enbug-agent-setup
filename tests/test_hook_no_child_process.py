import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
REAL_PYTHON = os.path.realpath(sys.executable)
LAUNCHER_COMMAND = re.compile(r'sh "\$\{CLAUDE_PLUGIN_ROOT\}/scripts/hook_python\.sh" ([a-z_]+\.py)')
PROGRAMS = ("git", "gh", "orca", "find", "mkdir", "ls", "date", "sysctl", "uname", "ps", "pgrep", "sleep", "cat",
            "rm", "mv", "codex", "claude", "kubectl", "az", "aws", "psql", "curl", "hostname", "whoami", "id", "env")
NETWORK_GUARD = (
    "import os, socket\n"
    "def _record(*args, **kwargs):\n"
    "    with open(os.environ['NET_LOG'], 'a') as handle:\n"
    "        handle.write('connect\\n')\n"
    "    raise OSError('network is blocked in this test')\n"
    "socket.socket.connect = _record\n"
    "socket.socket.connect_ex = _record\n"
    "socket.getaddrinfo = _record\n"
)


def registered_hooks():
    found = []
    for name in ("hooks.json", "codex-hooks.json", "claude-hooks.json"):
        hooks = json.loads((REPO_ROOT / "hooks" / name).read_text(encoding="utf-8"))["hooks"]
        for event, groups in hooks.items():
            for group in groups:
                for handler in group["hooks"]:
                    found.append((LAUNCHER_COMMAND.fullmatch(handler["command"])[1], event))
    return found


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    base = tmp_path_factory.mktemp("quiet")
    stubs = base / "stubs"
    stubs.mkdir()
    calls = base / "calls.log"
    for name in (*PROGRAMS, "python3"):
        stub = stubs / name
        stub.write_text(f'#!/bin/sh\necho "{name} $*" >> "{calls}"\nexit 1\n', encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    guard = base / "guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(NETWORK_GUARD, encoding="utf-8")
    folder = base / "state" / "hei5enbug-agent-setup" / "interpreter"
    folder.mkdir(parents=True, mode=0o700)
    cache = folder / "cache"
    cache.write_text(f"{stubs / 'python3'}\n{REAL_PYTHON}\n", encoding="utf-8")
    cache.chmod(0o600)
    (folder / "verified").write_text("", encoding="utf-8")
    return base, stubs, calls, guard


@pytest.mark.parametrize(("script", "event"), sorted(set(registered_hooks())))
def test_Bash_입력_ls_tmp_work은_어떤_훅도_실행_파일을_부르거나_네트워크에_연결하지_않는다(sandbox, script, event):
    # given
    base, stubs, calls, guard = sandbox
    net = base / "net.log"
    calls.write_text("")
    net.write_text("")
    payload = json.dumps({"hook_event_name": event, "session_id": "s1", "cwd": "/tmp/work", "tool_name": "Bash",
                          "tool_use_id": "t1", "tool_input": {"command": "ls /tmp/work"}, "prompt": "ls /tmp/work"})
    environment = {"PATH": str(stubs), "HOME": str(base / "home"), "XDG_STATE_HOME": str(base / "state"),
                   "PYTHONPATH": str(guard), "NET_LOG": str(net), "ORCA_TERMINAL_HANDLE": "term_demo"}
    # when
    result = subprocess.run(["/bin/sh", str(SCRIPTS / "hook_python.sh"), script], input=payload, text=True,
                            capture_output=True, env=environment, timeout=60, cwd=base)
    # then
    assert result.returncode in (0, 1), result.stderr
    assert "Traceback" not in result.stderr
    assert calls.read_text() == ""
    assert net.read_text() == ""
