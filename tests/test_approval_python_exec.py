"""`exec` and `eval` of a string literal are judged by the code they run; a non-literal argument keeps its old outcome."""
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import approval_guard as guard  # noqa: E402
import approval_state as state_mod  # noqa: E402


@pytest.fixture
def world(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = home / "work" / "project"
    project.mkdir(parents=True)
    cache = home / ".claude" / "plugins" / "cache" / "market" / "demo" / "1.0.0"
    cache.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude"))
    monkeypatch.setenv("HEI5ENBUG_RESPONSE_LANGUAGE", "English")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    state_mod.prompt_language.cache_clear()
    for name in [name for name in os.environ if name.startswith("GIT_")] + ["KUBECONFIG", "CODEX_HOME"]:
        monkeypatch.delenv(name, raising=False)
    return {"home": home, "project": project, "cache": cache}


def verdict(world, command):
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
             "session_id": "s1", "cwd": str(world["project"])}
    output = guard.handle(event, "claude")
    if not output:
        return None, ""
    details = output["hookSpecificOutput"]
    return details["permissionDecision"], details.get("permissionDecisionReason", "")


def kind(result):
    """The decision with the first words of its reason, which name the tier; every denial counts as one, and so does every
    call that runs without a question."""
    if result[0] in ("deny", None, "allow"):
        return ("deny" if result[0] == "deny" else "quiet", "")
    return result[0], " ".join(result[1].split()[:2])


def heredoc(body):
    return f"python3 - <<'EOF'\n{body}\nEOF"


def inline(body):
    return "python3 -c '" + body.replace("'", "'\"'\"'") + "'"


def wrap(code, function):
    return f"{function}({code!r})"


JUDGED_BY_CODE = [
    "print(open('{home}/.netrc').read())",
    "open('{home}/.zshrc', 'a').write('x')",
    "open('{cache}/a.py', 'w').write('x')",
    "import os\nprint(os.environ['GITHUB_TOKEN'])",
    "import subprocess\nsubprocess.run(['ls'])",
    "import os\nos.system('echo hi')",
    "print(1 + 1)",
    "open('notes.txt', 'w').write('x')",
]


@pytest.mark.parametrize("template", JUDGED_BY_CODE)
@pytest.mark.parametrize("function", ["exec"])
@pytest.mark.parametrize("shape", [heredoc, inline])
def test_문자열_리터럴_exec는_같은_코드를_직접_쓴_것과_같이_판정한다(world, template, function, shape):
    # given
    code = template.format(**world)
    # when
    direct = verdict(world, shape(code))
    wrapped = verdict(world, shape(wrap(code, function)))
    # then
    assert kind(wrapped) == kind(direct), (template, direct, wrapped)


@pytest.mark.parametrize("template", [
    "print(open('{home}/.netrc').read())", "open('{home}/.zshrc', 'a').write('x')", "open('{cache}/a.py', 'w').write('x')",
])
def test_중첩_exec_안의_위험한_코드도_같이_판정한다(world, template):
    # given
    code = template.format(**world)
    direct = verdict(world, inline(code))
    # when
    nested = verdict(world, inline(wrap(wrap(code, "exec"), "exec")))
    # then
    assert kind(nested) == kind(direct)


def test_해롭지_않은_리터럴_exec와_eval은_묻지_않는다(world):
    # given
    commands = [inline("exec('print(1 + 1)')"), heredoc("exec('x = 2\\nprint(x)')"), inline("print(eval('1 + 1'))"),
                heredoc("value = eval('[1, 2][0]')\nprint(value)")]
    # when
    results = [verdict(world, command)[0] for command in commands]
    # then
    assert all(result not in ("ask", "deny") for result in results), results


NON_LITERAL = [
    "code = 'print(1)'\nexec(code)",
    "exec(input())",
    "import sys\nexec(sys.stdin.read())",
    "import sys\nexec(sys.argv[1])",
    "exec('print(' + str(1) + ')')",
    "exec(open('plan.py').read())",
]


@pytest.mark.parametrize("body", NON_LITERAL)
def test_리터럴이_아닌_exec는_지금처럼_묻는다(world, body):
    # given
    command = inline(body)
    # when
    result = verdict(world, command)
    # then
    assert result[0] == "ask", body


def test_리터럴이_아닌_exec라도_같은_코드가_민감한_위치에_쓰면_그_판정이_앞선다(world):
    # given
    body = "import sys\nexec(sys.argv[1])\nopen('{home}/.zshrc', 'a').write('x')".format(**world)
    # when
    decision, reason = verdict(world, inline(body))
    # then
    assert decision == "ask" and reason.startswith("Asks every time")


def test_리터럴이_아닌_exec라도_같은_코드가_설치된_코드에_쓰면_거부한다(world):
    # given
    body = "import sys\nexec(sys.argv[1])\nopen('{cache}/a.py', 'w').write('x')".format(**world)
    # when
    decision, _ = verdict(world, inline(body))
    # then
    assert decision == "deny"
