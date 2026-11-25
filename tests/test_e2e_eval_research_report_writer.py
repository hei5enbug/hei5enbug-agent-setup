"""Offline checks for the five research-report-writer tasks."""

import importlib.util
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
E2E = ROOT / "evals/e2e"
TASKS = E2E / "tasks"
sys.path.insert(0, str(E2E))

from harness import graders, scripted_user  # noqa: E402

QUESTION = "이 문서에 research-report-writer를 사용해도 될까요?"


def task_workspace(tmp_path, task_id):
    task = graders.load_task(TASKS, task_id)
    repo = tmp_path / "repo"
    base = graders.materialize_fixture(task, E2E / "fixtures", TASKS, repo)
    return task, repo, base


def apply_reference(task_id, repo):
    script = TASKS / "reference" / task_id / "apply.py"
    subprocess.run([sys.executable, "-B", str(script), str(repo)],
                   env={**os.environ, "PYTHONPATH": str(TASKS / "reference")}, check=True)


def tool(name, inputs, result="", ident="tool-1"):
    return {"id": ident, "name": name, "input": inputs, "result_text": result, "is_error": False}


def skill_call():
    return tool("Skill", {"skill": "hei5enbug-agent-setup:research-report-writer"}, "Skill instructions delivered.")


def shell_skill_call():
    return tool("Bash", {"command": "cat /tmp/work/skills/research-report-writer/SKILL.md"},
                "# Research Report Writer\n", "shell-skill")


def consent(task, kind, tool_use_id=None):
    sheet = scripted_user.load_sheet(TASKS / task["user"]["sheet"])
    exchange = scripted_user.respond(sheet, QUESTION, kind, QUESTION, False)
    return scripted_user.log_exchange(None, exchange, tool_use_id=tool_use_id)


def grade(tmp_path, task, repo, base, calls=(), exchanges=(), answer=""):
    view = {"tool_calls": calls, "user_exchanges": exchanges, "final_answer": answer}
    result = graders.grade_run(task, repo, base, view, TASKS, tmp_path / "grade/work")
    return {check["id"]: check["passed"] for check in result["checks"]} | {"success": result["success"]}


@pytest.mark.parametrize(("task_id", "effect"), [
    ("T188", "direct-skill-started"),
    ("T189", "skill-started-after-consent"),
    ("T190", "output-exists"),
    ("T191", "options-share-table"),
    ("T192", "requested-option-marked"),
])
def test_변경하지_않은_픽스처는_과제에_필요한_검사를_통과하지_못한다(tmp_path, task_id, effect):
    """작업을 시작하지 않으면 각 과제의 필수 결과나 진행 순서가 빠진다."""
    # given
    task, repo, base = task_workspace(tmp_path, task_id)

    # when
    checks = grade(tmp_path, task, repo, base)

    # then
    assert not checks["success"]
    assert not checks[effect]
    assert checks["sources-unchanged"]


@pytest.mark.parametrize("task_id", ("T188", "T189", "T190", "T191", "T192"))
def test_참조_보고서와_실행_기록은_모든_필수_검사를_통과한다(tmp_path, task_id):
    """참조 산출물과 동의 뒤 스킬을 연 기록은 각 과제의 필수 조건을 충족한다."""
    # given
    task, repo, base = task_workspace(tmp_path, task_id)
    apply_reference(task_id, repo)
    calls, exchanges = [], []
    if task_id == "T188":
        calls = [skill_call()]
    elif task_id == "T189":
        question = tool("AskUserQuestion", {"questions": [{"question": QUESTION}]}, ident="consent-question")
        calls = [question, skill_call()]
        exchanges = [consent(task, "tool", "consent-question")]

    # when
    checks = grade(tmp_path, task, repo, base, calls=calls, exchanges=exchanges)

    # then
    assert all(checks.values()), checks


@pytest.mark.parametrize(("early_action", "passed"), [
    (None, True),
    ({"type": "command_execution", "command": "cat logs/timeout.csv"}, False),
    ({"type": "command_execution", "command": "cat /tmp/work/skills/research-report-writer/SKILL.md"}, False),
    ({"type": "command_execution", "command": "printf 'draft' > scratch.md"}, False),
    ({"type": "file_change", "changes": [{"path": "out/report.md", "kind": "add"}]}, False),
])
def test_동의_전에는_분석이나_쓰기나_스킬_로드를_하지_않는다(tmp_path, early_action, passed):
    """텍스트로 받은 동의가 로그 읽기와 파일 쓰기와 스킬 로드보다 먼저인지 확인한다."""
    # given
    task, repo, base = task_workspace(tmp_path, "T189")
    apply_reference("T189", repo)
    events = [{"type": "item.completed", "item": {"type": "agent_message", "text": QUESTION}},
              {"type": "turn.completed"}]
    if early_action:
        events.insert(0, {"type": "item.completed", "item": early_action})
    stream = tmp_path / "stream.jsonl"
    stream.write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")

    # when
    checks = grade(tmp_path, task, repo, base, calls=[shell_skill_call()], exchanges=[consent(task, "text")])

    # then
    assert checks["skill-started-after-consent"] == passed


def test_직접_요청에서는_동의_질문이나_스킬_파일_경로만_나온_기록을_거른다(tmp_path):
    """스킬을 직접 요청한 경우 스킬 본문을 읽고 다시 사용 여부를 묻지 않아야 한다."""
    # given
    task, repo, base = task_workspace(tmp_path, "T188")
    apply_reference("T188", repo)
    path_only = tool("Bash", {"command": "rg -l pattern research-report-writer/SKILL.md"},
                     "research-report-writer/SKILL.md")
    asks_again = tool("AskUserQuestion", {"questions": [{"question": QUESTION}]}, ident="consent-question")

    # when
    outcomes = [grade(tmp_path, task, repo, base, calls=calls)["direct-skill-started"]
                for calls in ([path_only], [asks_again, skill_call()], [shell_skill_call()])]

    # then
    assert outcomes == [False, False, True]


@pytest.mark.parametrize(("exit_code", "passed"), [(0, True), (1, False)])
def test_조합한_스킬_경로는_코덱스의_완료_이벤트로_확인한다(tmp_path, exit_code, passed):
    """정규화된 도구 기록에 경로가 잘려도 완료 이벤트에서 본문을 읽었는지 판정한다."""
    # given
    task, repo, base = task_workspace(tmp_path, "T188")
    apply_reference("T188", repo)
    body = "# Research Report Writer\n"
    (tmp_path / "stream.jsonl").write_text(json.dumps({"type": "item.completed", "item": {
        "type": "command_execution", "command": "cat /tmp/work/skills/research-report-writer/SKILL.md",
        "aggregated_output": body, "exit_code": exit_code,
    }}) + "\n", encoding="utf-8")

    # when
    checks = grade(tmp_path, task, repo, base, calls=[tool("Bash", {"command": "cat '"}, body)])

    # then
    assert checks["direct-skill-started"] is passed


def test_검증하지_않은_선택지와_잘못_고른_최장_사례를_잡는다(tmp_path):
    """검증에 실패한 D를 표에 넣거나 더 짧은 사례를 최장이라고 부르면 통과하지 못한다."""
    # given
    task, repo, base = task_workspace(tmp_path, "T191")
    apply_reference("T191", repo)
    report = repo / "out/report.md"
    text = report.read_text(encoding="utf-8").replace("case-38", "case-17")
    report.write_text(text + "\n후속 작업 후보로 D를 남겼다.\n", encoding="utf-8")

    # when
    checks = grade(tmp_path, task, repo, base)

    # then
    assert checks["options-share-table"]
    assert not checks["unverified-option-omitted"]
    assert not checks["longest-case-illustrated"]


@pytest.mark.parametrize(("task_id", "inline", "selection", "missing_figure", "passed"), [
    ("T191", False, "사례 기록에 있는 요청을 빠짐없이 실었다.", False, True),
    ("T192", True, "The table includes every request in the log.", False, True),
    ("T191", False, "그림은 같은 실험의 개별 요청을 보여 준다.", False, False),
    ("T192", True, "The table includes every request in the log.", True, False),
])
def test_표와_그림에_나뉜_사례도_선정_근거와_그림을_모두_확인한다(
    tmp_path, task_id, inline, selection, missing_figure, passed,
):
    """선정 기준이 공통이고 그림이 표 안이나 뒤에 있어도 각 사례의 근거와 그림을 확인한다."""
    # given
    task, repo, base = task_workspace(tmp_path, task_id)
    apply_reference(task_id, repo)
    report = repo / "out/report.md"
    intro, _, _ = report.read_text(encoding="utf-8").partition("## 가장 오래 걸린 요청")
    rows = ["| 사례 | 소요 시간 | 추적 |", "| --- | ---: | --- |"]
    gallery = []
    for case, duration in [("case-17", "450"), ("case-38", "915 (최장 소요 시간)"), ("case-52", "720")]:
        figure = f"![{case} 추적](../figures/{case}.svg)"
        if missing_figure and case == "case-52":
            figure = f"[{case} 추적](../figures/{case}.svg)"
        rows.append(f"| {case} | {duration} | {figure if inline else ''} |")
        if not inline:
            gallery.extend([f"### {case} 추적", "", figure, ""])
    case_section = "\n".join(["## 개별 요청", "", selection, "", *rows, "", *gallery])
    report.write_text(intro + case_section, encoding="utf-8")

    # when
    checks = grade(tmp_path, task, repo, base)

    # then
    assert checks["longest-case-illustrated"] is passed


def test_명시적으로_요청한_D도_검증된_표에는_넣지_않는다(tmp_path):
    """미검증 표시를 붙여도 검증된 선택지와 같은 표에 D를 넣으면 실패한다."""
    # given
    task, repo, base = task_workspace(tmp_path, "T192")
    apply_reference("T192", repo)
    report = repo / "out/report.md"
    text = report.read_text(encoding="utf-8").replace("| C | 부하에 맞게 묶음 간격 조절 | 99% | 175ms |",
                                                     "| C | 부하에 맞게 묶음 간격 조절 | 99% | 175ms |\n"
                                                     "| D | 미검증 | 100% | 105ms |")
    report.write_text(text, encoding="utf-8")

    # when
    checks = grade(tmp_path, task, repo, base)

    # then
    assert checks["options-share-table"]
    assert not checks["requested-option-marked"]


def test_새_스킬은_배포용_메타데이터_검증을_통과한다():
    """새 스킬의 메타데이터와 스킬 디렉터리 이름이 배포용 형식에 맞는다."""
    # given
    path = ROOT / "skills/skill-builder/scripts/quick_validate.py"
    spec = importlib.util.spec_from_file_location("quick_validate", path)
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)

    # when
    valid, message = validator.validate_skill(ROOT / "skills/research-report-writer")

    # then
    assert valid, message


@pytest.mark.parametrize(
    ("command", "work"),
    [
        ("pwd && rg --files -g 'AGENTS.md' -g 'logs/**' | head -80", False),
        ("ls logs", False),
        ("cat logs/timeout.csv", True),
        ("wc -lc logs/timeout.csv", True),
        ("rg error logs/", True),
    ],
)
def test_파일_이름만_나열한_명령은_동의_전_분석으로_세지_않는다(command, work):
    """동의 전 순서 검사는 logs 아래 파일 이름 나열을 분석으로 세지 않고, 내용을 읽는 명령은 분석으로 센다."""
    # given
    grader = runpy.run_path(str(ROOT / "evals/e2e/tasks/custom/T188.py"))

    # when
    result = grader["inputs_are_work"]("Bash", {"command": command})

    # then
    assert result is work
