"""할당이 스킬 이름을 지목하면 worker가 그 스킬을 불러오고 결과에 적으며 조정자가 호스트 기록으로 확인하는 규칙을 검사한다."""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import skill_load_check as check  # noqa: E402

SCRIPT = REPO / "scripts/skill_load_check.py"
DELEGATION = REPO / "instructions/implementation-delegation.md"
EXECUTION = REPO / "instructions/implementation-execution.md"
CODEX_ROLES = [REPO / ".codex/agents/worker.toml", REPO / "standalone-agents/codex-worker.toml"]
RESULT_WITH = "Changed notes_cli/cli.py. Loaded skills: demo-skill. Tests pass."
RESULT_WITHOUT = "Changed notes_cli/cli.py. Tests pass."


def section(text: str, heading: str) -> str:
    return " ".join(text.split(f"## {heading}", 1)[1].split("\n## ", 1)[0].split())


def claude_call(name: str, **tool_input: str) -> dict:
    block = {"type": "tool_use", "id": f"toolu_{name}", "name": name, "input": tool_input}
    return {"type": "assistant", "message": {"role": "assistant", "content": [block]}}


def claude_skill_result(is_error: bool = False) -> dict:
    block = {"type": "tool_result", "tool_use_id": "toolu_Skill", "is_error": is_error, "content": "Skill response"}
    return {"type": "user", "message": {"role": "user", "content": [block]}}


def codex_call(payload_type: str, **fields: object) -> dict:
    return {"type": "response_item", "payload": {"type": payload_type, **fields}}


BASH_ONLY = [claude_call("Bash", command="python3 -m pytest -q"), claude_call("Edit", file_path="a.py")]
SKILL_LOADED = [*BASH_ONLY, claude_call("Skill", skill="demo-skill"), claude_skill_result()]
SKILL_LOADED_WITH_PLUGIN = [claude_call("Skill", skill="demo-plugin:demo-skill"), claude_skill_result()]
CODEX_SHELL_ONLY = [codex_call("function_call", name="exec_command", arguments=json.dumps({"cmd": "ls -la"}))]
SKILL_PATH = "/home/test/.agents/skills/demo-skill/SKILL.md"


def codex_shell(command: str, call_id: str, exit_code: int) -> list[dict]:
    return [
        codex_call("function_call", name="exec_command", call_id=call_id, arguments=json.dumps({"cmd": command})),
        codex_call("function_call_output", call_id=call_id,
                   output=json.dumps({"metadata": {"exit_code": exit_code}, "output": "Shell response"})),
    ]


def codex_exec(exit_code: int) -> list[dict]:
    return [
        codex_call("custom_tool_call", name="exec", call_id="exec",
                   input=f'text(await tools.exec_command({{cmd:"cat {SKILL_PATH}"}}));\n'
                         'text(await tools.exec_command({cmd:"ls"}));'),
        codex_call("custom_tool_call_output", call_id="exec", output=[
            {"type": "input_text", "text": "Script completed\nOutput:\n"},
            {"type": "input_text", "text": json.dumps({"exit_code": exit_code, "output": "Shell response"})},
            {"type": "input_text", "text": json.dumps({"exit_code": 0, "output": "Other response"})},
        ]),
    ]


def test_위임_규칙은_스킬_이름을_적고_불러오게_하며_스킬이_없으면_아무것도_더하지_않는다():
    """Worker assignments는 이름을 적고 호스트의 스킬 수단으로 먼저 불러와 따르게 하며, 스킬이 없으면 스킬 이야기를 하지 않게 한다."""
    # Given
    text = section(DELEGATION.read_text(encoding="utf-8"), "Worker assignments")

    # Then
    assert "names a skill, its assignment states the skill name" in text
    assert "load it with the host's skill mechanism before the work the skill covers" in text
    assert "follow it instead of doing that work by hand" in text
    assert "An assignment that names no skill says nothing about skills." in text


def test_Assigned_workers는_불러오기_결과_목록_누락_시_중단을_정한다():
    """Assigned workers 절은 스킬을 먼저 불러오기, 결과에 적기, 불러올 수 없으면 편집 없이 멈추고 차단으로 보고하기를 조건부로 정한다."""
    # Given
    text = section(DELEGATION.read_text(encoding="utf-8"), "Assigned workers")

    # Then
    assert "When the assignment names a skill, load it first" in text
    assert "list each skill you loaded in the result" in text
    assert "When it cannot be loaded, stop, make no edit that the skill covers" in text
    assert "report the missing skill to the coordinator as a blocker" in text
    assert text.endswith("Return the changed paths, check results, and remaining blockers.")


def test_검토와_통합은_호스트_기록의_불러오기를_확인하고_없으면_인정하지_않는다():
    """Review and integration 절은 각 스킬의 불러오기를 호스트 기록으로 확인하고 기록에 없거나 결과에 없으면 실패한 검사로 다룬다."""
    # Given
    text = section(DELEGATION.read_text(encoding="utf-8"), "Review and integration")

    # Then
    assert "check the worker's host record for the load of each named skill" in text
    assert "scripts/skill_load_check.py" in text
    assert "no load of a named skill, or whose result lists none, is not accepted" in text
    assert "failed acceptance check" in text


def test_할당_필드는_스킬을_이름이_있을_때만_넣는다():
    """Assignment fields는 worker가 불러올 스킬을 작업이 이름을 댈 때만 넣는 필드로 적는다."""
    # Given
    text = section(EXECUTION.read_text(encoding="utf-8"), "Assignment fields")

    # Then
    assert "The skill the worker must load, only when the task names one" in text


@pytest.mark.parametrize("path", CODEX_ROLES, ids=lambda path: path.parent.name)
def test_Codex_worker_정의는_스킬_의무를_적는다(path):
    """Codex plugin 역할과 standalone worker 모두 먼저 불러오기, 결과 목록, 불러올 수 없으면 차단 보고를 적는다."""
    # Given
    text = " ".join(tomllib.loads(path.read_text(encoding="utf-8"))["developer_instructions"].split())

    # Then
    assert "When the assignment names a skill, load it first" in text
    assert "list each skill you loaded in the result" in text
    assert "stop and report a blocker when it cannot be loaded" in text


def test_Claude_worker_정의는_복사_없이_Assigned_workers를_가리킨다():
    """Claude worker 정의는 스킬 의무를 복사하지 않고 Assigned workers 규칙을 따르게 한다."""
    # Given
    text = (REPO / "agents" / "worker.md").read_text(encoding="utf-8")

    # Then
    assert 'Follow the "Assigned workers" rules' in text
    assert "skill" not in text.split("---", 2)[2].lower()


def test_Bash만_있고_스킬_불러오기가_없는_기록은_인정하지_않는다():
    """demo-skill을 지목했는데 기록에 셸 명령과 편집뿐이면 결과가 이름을 적어도 인정하지 않는다."""
    # When
    report = check.evaluate(BASH_ONLY, RESULT_WITH, ["demo-skill"])

    # Then
    assert report["accepted"] is False
    assert report["not_loaded"] == ["demo-skill"]
    assert report["not_listed"] == []


def test_불러오기_기록이_있어도_결과가_스킬을_적지_않으면_인정하지_않는다():
    """기록에 불러오기가 있어도 결과가 그 이름을 적지 않으면 인정하지 않는다."""
    # When
    report = check.evaluate(SKILL_LOADED, RESULT_WITHOUT, ["demo-skill"])

    # Then
    assert report["accepted"] is False
    assert report["not_loaded"] == []
    assert report["not_listed"] == ["demo-skill"]


@pytest.mark.parametrize("entries", [
    SKILL_LOADED, SKILL_LOADED_WITH_PLUGIN, codex_shell(f"cat {SKILL_PATH}", "skill", 0), codex_exec(0),
], ids=["claude", "plugin", "codex", "codex-exec"])
def test_불러오기_기록과_결과_목록이_모두_있으면_인정한다(entries):
    """Claude Skill 호출, 플러그인 접두사 호출, Codex SKILL.md 읽기 중 무엇이든 결과가 이름을 적으면 인정한다."""
    # When
    report = check.evaluate(entries, RESULT_WITH, ["demo-skill"])

    # Then
    assert report["accepted"] is True


@pytest.mark.parametrize("entries", [
    [claude_call("Skill", skill="demo-skill"), claude_skill_result(is_error=True)],
    [*codex_shell(f"cat {SKILL_PATH}", "skill", 1), *codex_shell("ls", "other", 0)],
    codex_exec(1),
    codex_shell(f"cat {SKILL_PATH}", "skill", 0)[:1],
    codex_shell(f"echo {SKILL_PATH}", "mention", 0),
    [codex_call("message", role="assistant", content=[{"type": "output_text", "text": SKILL_PATH}])],
], ids=["claude-error", "codex-error", "codex-exec-error", "pending", "shell-mention", "text-mention"])
def test_실패한_호출이나_경로_언급은_스킬_불러오기로_세지_않는다(entries):
    """파일을 읽는 데 실패하거나 경로만 언급하면 결과에 이름이 있어도 인정하지 않는다."""
    # given
    result = "Could not load demo-skill: missing file."
    # when
    report = check.evaluate(entries, result, ["demo-skill"])
    # then
    assert report["accepted"] is False
    assert report["not_loaded"] == ["demo-skill"]


def test_Codex_기록에_스킬_읽기가_없으면_인정하지_않는다():
    """Codex 기록이 SKILL.md를 읽지 않고 셸 명령만 담으면 인정하지 않는다."""
    # When
    report = check.evaluate(CODEX_SHELL_ONLY, RESULT_WITH, ["demo-skill"])

    # Then
    assert report["accepted"] is False


def test_이름이_비슷한_다른_스킬의_불러오기는_세지_않는다():
    """demo-skill-extra를 불러온 기록과 그 이름만 적은 결과는 demo-skill의 불러오기와 목록으로 세지 않는다."""
    # When
    report = check.evaluate([claude_call("Skill", skill="demo-skill-extra"), claude_skill_result()],
                            "Loaded skills: demo-skill-extra.", ["demo-skill"])

    # Then
    assert report["accepted"] is False
    assert report["not_loaded"] == ["demo-skill"]
    assert report["not_listed"] == ["demo-skill"]


def test_이름을_둘_지목하면_하나라도_빠진_결과는_인정하지_않는다():
    """스킬 둘을 지목했을 때 하나만 불러왔으면 빠진 이름을 알리며 인정하지 않는다."""
    # When
    report = check.evaluate(SKILL_LOADED, "Loaded: demo-skill, other-skill", ["demo-skill", "other-skill"])

    # Then
    assert report["accepted"] is False
    assert report["not_loaded"] == ["other-skill"]


def test_스킬을_지목하지_않은_할당은_인정이_그대로다():
    """지목한 스킬이 없으면 기록과 결과가 무엇이든 인정하고 아무것도 확인하지 않는다."""
    # When
    report = check.evaluate(BASH_ONLY, RESULT_WITHOUT, [])

    # Then
    assert report["accepted"] is True
    assert report["named"] == []


def run_cli(tmp_path: Path, entries: list[dict], result: str, *skills: str) -> subprocess.CompletedProcess:
    record = tmp_path / "agent.jsonl"
    record.write_text("\n".join(json.dumps(entry) for entry in entries) + "\nnot json\n", encoding="utf-8")
    result_file = tmp_path / "result.txt"
    result_file.write_text(result, encoding="utf-8")
    command = [sys.executable, str(SCRIPT), "--record", str(record), "--result", str(result_file)]
    for skill in skills:
        command += ["--skill", skill]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def test_명령은_기록과_결과로_종료_코드와_JSON을_낸다(tmp_path):
    """명령은 인정하면 0, 인정하지 않으면 1이고 JSON에 불러온 스킬과 빠진 이름을 담는다."""
    # When
    rejected = run_cli(tmp_path, BASH_ONLY, RESULT_WITH, "demo-skill")
    accepted = run_cli(tmp_path, SKILL_LOADED, RESULT_WITH, "demo-skill")
    unnamed = run_cli(tmp_path, BASH_ONLY, RESULT_WITHOUT)

    # Then
    assert (rejected.returncode, json.loads(rejected.stdout)["not_loaded"]) == (1, ["demo-skill"])
    assert (accepted.returncode, json.loads(accepted.stdout)["loaded"]) == (0, ["demo-skill"])
    assert unnamed.returncode == 0


def test_명령은_읽을_수_없는_기록과_빠진_인자를_인정하지_않는다(tmp_path):
    """기록 파일이 없으면 4, 스킬을 지목하고 기록이나 결과를 빼면 2로 끝나며 인정하지 않는다."""
    # When
    missing = subprocess.run(
        [sys.executable, str(SCRIPT), "--record", str(tmp_path / "none.jsonl"), "--result", str(tmp_path / "r.txt"),
         "--skill", "demo-skill"],
        capture_output=True, text=True, check=False,
    )
    usage = subprocess.run([sys.executable, str(SCRIPT), "--skill", "demo-skill"], capture_output=True, text=True, check=False)

    # Then
    assert missing.returncode == check.EXIT_EVIDENCE
    assert json.loads(missing.stdout)["accepted"] is False
    assert usage.returncode == check.EXIT_USAGE
