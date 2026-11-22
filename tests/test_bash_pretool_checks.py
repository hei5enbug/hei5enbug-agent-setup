"""The Bash PreToolUse dispatcher runs the public boundary, required checks, and Orca placement checks in one process.

The logic tests drive `run_checks` with seeded fake checks. The equivalence tests run each real check alone and the
dispatcher on the same input and compare the decision the host would take from the separate hooks with the decision
of the dispatcher.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import bash_pretool_checks as dispatcher  # noqa: E402
import hook_runtime  # noqa: E402

PUBLIC_REPO = "demo-owner/demo-public"
HOME_PATH = "/home/" + "jdoe" + "/project"
ORDER = ("public_boundary_hook.py", "required_checks_hook.py", "orca_placement_hook.py")
BASH_EVENT = "PreToolUse"


def event_bytes(command: str, cwd: str | None = None) -> bytes:
    event = {"hook_event_name": BASH_EVENT, "tool_name": "Bash", "tool_input": {"command": command}}
    if cwd is not None:
        event["cwd"] = cwd
    return json.dumps(event).encode()


@pytest.fixture
def fakes(tmp_path, monkeypatch):
    """Fake check modules that record their calls in `log.calls`; each is written from a body of `main`."""
    folder = tmp_path / "fakes"
    folder.mkdir()
    (folder / "fake_log.py").write_text("calls = []\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(folder))
    sys.modules.pop("fake_log", None)
    made = []

    def make(name: str, body: str) -> str:
        source = "import sys, time, json\nimport fake_log\n\ndef main():\n    fake_log.calls.append(NAME)\n"
        source = source.replace("NAME", repr(name)) + textwrap.indent(textwrap.dedent(body), "    ") + "\n"
        (folder / f"{name}.py").write_text(source, encoding="utf-8")
        made.append(name)
        return name

    yield make
    for name in (*made, "fake_log"):
        sys.modules.pop(name, None)


def calls() -> list[str]:
    import fake_log

    return fake_log.calls


def fake_check(script: str, module: str, limit: float | None = None, needs: tuple[str, ...] = ()):
    return dispatcher.Check(script, module, needs=needs, limit=limit)


def test_출력_없이_통과하는_검사들은_모두_실행되고_출력도_종료_상태도_없다(fakes):
    # given
    checks = tuple(fake_check(script, fakes(f"pass_{index}", "return 0")) for index, script in enumerate(ORDER))
    # when
    stdout, stderr, code = dispatcher.run_checks(event_bytes("ls /tmp/work"), checks, start=hook_runtime.time.time())
    # then
    assert (stdout, stderr, code) == ("", "", 0)
    assert calls() == ["pass_0", "pass_1", "pass_2"]


def test_종료_상태_2로_막은_검사는_이름과_함께_반환되고_뒤_검사는_실행되지_않는다(fakes):
    # given
    first = fakes("deny_exit", 'print("finding at command:1", file=sys.stderr)\nreturn 2')
    later = [fakes("later_a", "return 0"), fakes("later_b", "return 0")]
    checks = (fake_check(ORDER[0], first), fake_check(ORDER[1], later[0]), fake_check(ORDER[2], later[1]))
    # when
    stdout, stderr, code = dispatcher.run_checks(event_bytes("git push"), checks, start=hook_runtime.time.time())
    # then
    assert code == 2 and stdout == ""
    assert ORDER[0] in stderr and "finding at command:1" in stderr
    assert calls() == ["deny_exit"]


def test_결정_형식으로_막은_검사는_앞_검사의_맥락과_함께_반환되고_뒤_검사는_실행되지_않는다(fakes):
    # given
    context = fakes("context", 'print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", '
                               '"additionalContext": "remember"}}))\nreturn 0')
    deny = fakes("deny_json", 'print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", '
                              '"permissionDecision": "deny", "permissionDecisionReason": "no top level"}}))\nreturn 0')
    later = fakes("later", "return 0")
    checks = (fake_check(ORDER[0], fakes("first", "return 0")), fake_check(ORDER[1], context),
              fake_check(ORDER[2], deny), fake_check("agent_guard.py", later))
    # when
    stdout, stderr, code = dispatcher.run_checks(event_bytes("orca x"), checks, start=hook_runtime.time.time())
    # then
    output = json.loads(stdout)["hookSpecificOutput"]
    assert (code, stderr) == (0, "")
    assert output["permissionDecision"] == "deny" and ORDER[2] in output["permissionDecisionReason"]
    assert "no top level" in output["permissionDecisionReason"] and output["additionalContext"] == "remember"
    assert calls() == ["first", "context", "deny_json"]


@pytest.mark.parametrize("script", ORDER)
def test_예산을_넘긴_검사는_이름과_그_검사의_기존_시간_초과_결과로_보고되고_나머지_검사는_계속_실행된다(fakes, script):
    # given
    slow = fakes("slow", "time.sleep(30)\nreturn 0")
    checks = [fake_check(name, fakes(f"quick_{index}", "return 0")) for index, name in enumerate(ORDER)]
    position = ORDER.index(script)
    checks[position] = fake_check(script, slow, limit=0.3)
    alone = hook_runtime.timeout_result(script, BASH_EVENT, 0.3)
    # when
    stdout, stderr, code = dispatcher.run_checks(event_bytes("ls"), tuple(checks), start=hook_runtime.time.time())
    # then
    ran = [name for name in calls()]
    denied = alone[2] == 2 or bool(alone[0])
    assert ran == [f"quick_{index}" for index in range(position)] + ["slow"] + (
        [] if denied else [f"quick_{index}" for index in range(position + 1, len(ORDER))])
    if denied:
        assert hook_runtime.title_of(script) in stdout + stderr and script in stdout + stderr
        assert "machine is busy" in stdout + stderr
        assert (code == 2) == (alone[2] == 2)
    else:
        assert (stdout, stderr, code) == ("", "", 0)


def test_내부_오류를_낸_검사는_이름으로_알리되_막지_않고_뒤_검사는_실행된다(fakes):
    # given
    broken = fakes("broken", "raise RuntimeError('detail')")
    after = fakes("after", "return 0")
    checks = (fake_check(ORDER[0], broken), fake_check(ORDER[1], after))
    # when
    stdout, stderr, code = dispatcher.run_checks(event_bytes("ls"), checks, start=hook_runtime.time.time())
    # then
    output = json.loads(stdout)
    assert (code, stderr) == (0, "")
    assert "hookSpecificOutput" not in output
    assert "public boundary hook" in output["systemMessage"] and "RuntimeError" in output["systemMessage"]
    assert "detail" not in output["systemMessage"]
    assert calls() == ["broken", "after"]


def test_입력에_필요한_낱말이_없으면_그_검사는_불러오지도_않는다(fakes):
    # given
    skipped = fakes("skipped", "return 0")
    ran = fakes("ran", "return 0")
    checks = (fake_check(ORDER[2], skipped, needs=("orca", "EnterWorktree")), fake_check(ORDER[1], ran))
    # when
    dispatcher.run_checks(event_bytes("ls /tmp/work"), checks, start=hook_runtime.time.time())
    # then
    assert calls() == ["ran"] and "skipped" not in sys.modules


def test_합친_등록의_timeout은_합쳐진_세_검사의_예산_합이다():
    # given
    merged = sum(hook_runtime.DECLARED_TIMEOUTS[(script, BASH_EVENT)] for script in ORDER)
    registered = json.loads((REPO_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    # when
    entry = [handler for group in registered for handler in group["hooks"]
             if "bash_pretool_checks.py" in handler["command"]]
    # then
    assert [handler["timeout"] for handler in entry] == [merged]
    assert hook_runtime.DECLARED_TIMEOUTS[("bash_pretool_checks.py", BASH_EVENT)] == merged
    assert [check.script for check in dispatcher.CHECKS] == list(ORDER)


class Sandbox:
    """A copy of the plugin that declares one public repository, with a session repository outside it."""

    def __init__(self, base: Path) -> None:
        self.base = base
        self.root = base / "own"
        shutil.copytree(SCRIPTS, self.root / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(REPO_ROOT / ".githooks", self.root / ".githooks", ignore=shutil.ignore_patterns("__pycache__"))
        (self.root / "issue-target.json").write_text(json.dumps(
            {"version": 1, "tracker": {"kind": "github", "location": PUBLIC_REPO}, "public": True}), encoding="utf-8")
        self.session = base / "work" / "demo-a"
        self.session.mkdir(parents=True)
        for command in (["git", "init", "-q", "-b", "main"],
                        ["git", "remote", "add", "origin", "https://github.com/demo-owner/demo-a.git"]):
            subprocess.run(command, cwd=self.session, check=True, capture_output=True)
        self.env = {
            **{key: value for key, value in os.environ.items()
               if not key.startswith(("GIT_", "HEI5ENBUG_", "CLAUDE_", "CODEX_", "ORCA_"))},
            "HOME": str(base / "home"), "XDG_STATE_HOME": str(base / "state"),
            "CLAUDE_CONFIG_DIR": str(base / "claude"), "CODEX_HOME": str(base / "codex"),
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "HEI5ENBUG_AVAILABLE_MEMORY_MB_FOR_TESTS": "100000",
        }

    def run(self, script: str, command: str, **extra: str) -> tuple[str, str, int]:
        payload = event_bytes(command, str(self.session)).decode()
        result = subprocess.run([sys.executable, str(self.root / "scripts" / script)], input=payload, text=True,
                                capture_output=True, cwd=self.base, env={**self.env, **extra}, timeout=60)
        return result.stdout, result.stderr, result.returncode


@pytest.fixture
def sandbox(tmp_path):
    return Sandbox(tmp_path)


def issue(body: str) -> str:
    return f'gh issue create --repo {PUBLIC_REPO} --title t --body "{body}"'


def host_decision(answers: list[tuple[str, tuple[str, str, int]]]) -> dict:
    """What the host decides from the separate hooks: a deny from any, and the context and messages of the rest."""
    denied, contexts, messages = [], [], []
    for script, (stdout, stderr, code) in answers:
        if code == 2:
            denied.append(script)
            continue
        try:
            output = json.loads(stdout) if stdout.strip() else {}
        except ValueError:
            output = {}
        specific = output.get("hookSpecificOutput", {})
        if specific.get("permissionDecision") == "deny":
            denied.append(script)
        elif code == 0:
            contexts += [specific["additionalContext"]] if "additionalContext" in specific else []
            messages += [output["systemMessage"]] if "systemMessage" in output else []
    return {"denied": denied, "contexts": contexts, "messages": messages}


def dispatcher_decision(answer: tuple[str, str, int]) -> dict:
    stdout, stderr, code = answer
    if code == 2:
        return {"denied": [stderr], "contexts": "", "messages": "", "code": 2}
    output = json.loads(stdout) if stdout.strip() else {}
    specific = output.get("hookSpecificOutput", {})
    denied = [specific["permissionDecisionReason"]] if specific.get("permissionDecision") == "deny" else []
    contexts = specific.get("additionalContext", "")
    messages = output.get("systemMessage", "")
    return {"denied": denied, "contexts": contexts, "messages": messages, "code": code}


COMMANDS = [
    "ls /tmp/work",
    "echo orca",
    "git commit -m demo",
    "git push origin main",
    "git status && ls",
    issue("clean text"),
    issue(f"see {HOME_PATH}"),
    f"git push origin main && {issue(f'see {HOME_PATH}')}",
    "orca worktree create --repo path:/tmp/work/demo --name demo-b --no-parent",
    "git commit -m demo && orca worktree create --repo path:/tmp/work/demo --name demo-b --no-parent",
    f"{issue(f'see {HOME_PATH}')} && orca worktree create --repo path:/tmp/work/demo --name demo-b --no-parent",
    f"{issue('clean text')} && git push origin main",
    "orca orchestration worker-start --worktree new-top-level --agent claude",
    "cat <<'EOF'\norca worktree create --no-parent\nEOF",
    "echo $(orca worktree create --no-parent)",
    "orca worktree list --json",
]


@pytest.mark.parametrize("command", COMMANDS)
def test_합친_실행은_세_검사를_따로_돌린_것과_같은_거부와_허용과_맥락을_낸다(sandbox, command):
    # given
    separate = [(script, sandbox.run(script, command)) for script in ORDER]
    expected = host_decision(separate)
    # when
    actual = dispatcher_decision(sandbox.run("bash_pretool_checks.py", command))
    # then
    assert bool(actual["denied"]) == bool(expected["denied"])
    if expected["denied"]:
        first = expected["denied"][0]
        assert first in actual["denied"][0]
        alone = dict(separate)[first]
        reason = alone[1].strip() if alone[2] == 2 else json.loads(alone[0])["hookSpecificOutput"][
            "permissionDecisionReason"]
        assert reason in actual["denied"][0]
        if actual["code"] == 0:
            earlier = host_decision(separate[:ORDER.index(first)])
            assert actual["contexts"] == "\n".join(earlier["contexts"])
    else:
        assert actual["contexts"] == "\n".join(expected["contexts"])
        assert actual["messages"] == "\n".join(expected["messages"])
        assert actual["code"] == 0


def test_공개_저장소로_가는_쓰기에_시드한_경계_결과가_있으면_공개_경계_사유로_막고_세_검사_모두_통과하는_명령은_통과한다(sandbox):
    # given
    blocked = f"git commit -m demo && {issue(f'see {HOME_PATH}')}"
    # when
    denied = sandbox.run("bash_pretool_checks.py", blocked)
    passed = sandbox.run("bash_pretool_checks.py", "ls /tmp/work")
    # then
    assert denied[2] == 2 and "public_boundary_hook.py" in denied[1] and "public boundary: blocked" in denied[1]
    assert HOME_PATH not in denied[1] and "orca" not in denied[1].lower()
    assert passed == ("", "", 0)


def test_런처를_거친_합친_훅도_거부는_종료_상태_2와_통과는_빈_출력으로_끝난다(sandbox):
    # given
    launcher = sandbox.root / "scripts" / "hook_python.sh"
    def launch(command):
        result = subprocess.run(["sh", str(launcher), "bash_pretool_checks.py"],
                                input=event_bytes(command, str(sandbox.session)).decode(), text=True,
                                capture_output=True, cwd=sandbox.base, env=sandbox.env, timeout=60)
        return result.stdout, result.returncode
    # when
    denied = launch(issue(f"see {HOME_PATH}"))
    passed = launch("ls /tmp/work")
    # then
    assert denied[1] == 2 and passed == ("", 0)


def test_엔터워크트리_입력은_합친_훅_없이_오르카_배치_훅_자신의_등록으로_거부된다(sandbox):
    # given
    event = json.dumps({"hook_event_name": BASH_EVENT, "tool_name": "EnterWorktree", "tool_input": {}})
    launcher = sandbox.root / "scripts" / "hook_python.sh"
    env = {**sandbox.env, "ORCA_TERMINAL_HANDLE": "term_demo-a"}
    # when
    result = subprocess.run(["sh", str(launcher), "orca_placement_hook.py"], input=event, text=True,
                            capture_output=True, cwd=sandbox.base, env=env, timeout=60)
    # then
    output = json.loads(result.stdout)["hookSpecificOutput"]
    assert result.returncode == 0 and output["permissionDecision"] == "deny"
