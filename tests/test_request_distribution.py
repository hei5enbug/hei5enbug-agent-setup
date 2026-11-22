"""요청 예산 항목 1: 시드한 세션 기록이 요청마다 실행 수와 재시도 수를 주고, 커밋한 기록이 기본 한도를 준다."""
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import request_distribution as dist  # noqa: E402

RECORD = json.loads((REPO_ROOT / "config" / "request-distribution.json").read_text(encoding="utf-8"))


def user(text, origin="human", **extra):
    return {"type": "user", "turnOrigin": origin, "timestamp": "2026-11-10T00:00:00Z", "message": {"content": text}, **extra}


def launch(call_id, agent="hei5enbug-agent-setup:worker"):
    block = {"type": "tool_use", "id": call_id, "name": "Agent", "input": {"subagent_type": agent}}
    return {"type": "assistant", "message": {"content": [block]}}


def bash(call_id, command):
    block = {"type": "tool_use", "id": call_id, "name": "Bash", "input": {"command": command}}
    return {"type": "assistant", "message": {"content": [block]}}


def result(call_id, text="ok", error=False):
    block = {"type": "tool_result", "tool_use_id": call_id, "is_error": error, "content": text}
    return {"type": "user", "message": {"content": [block]}}


def counted(events):
    return dist.count_requests(dist.claude_events(events))


def codex_call(call_id, name, **fields):
    return {"type": "response_item", "payload": {"type": "function_call", "name": name, "call_id": call_id, **fields}}


def codex_output(call_id, output):
    return {"type": "response_item", "payload": {"type": "function_call_output", "call_id": call_id, "output": output}}


def codex_user(text):
    return {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}}


def test_Claude_실행과_재시도는_요청마다_세고_요청은_다음_프롬프트에서_끝난다():
    """첫 프롬프트 전 실행은 세지 않고, 오류 뒤 같은 유형의 시작은 재시도이며, 요청은 다음 프롬프트에서 끝난다."""
    # given
    events = [
        launch("before-any-prompt"),
        user("first request"),
        launch("a"), result("a", error=True), launch("b"), result("b"), launch("c", "hei5enbug-agent-setup:scout"),
        user("second request"),
        launch("d"), launch("e"),
        user("third request, nothing delegated"),
    ]

    # when
    requests = counted(events)

    # then
    assert requests == [{"runs": 3, "retries": 1}, {"runs": 2, "retries": 0}, {"runs": 0, "retries": 0}]


def test_같은_유형이_아직_실행_중일_때의_시작은_재시도가_아니다():
    """결과가 오기 전에 같은 유형을 또 시작하면 재시도로 세지 않는다."""
    # given
    events = [user("go"), launch("a"), launch("b"), result("a", error=True), result("b", error=True)]

    # when
    requests = counted(events)

    # then
    assert requests == [{"runs": 2, "retries": 0}]


def test_role_runner_실행은_지시서마다_세고_0이_아닌_종료_뒤_같은_역할의_실행은_재시도다():
    """지시서와 결과 쌍마다 한 번으로 세고, 0이 아닌 종료 뒤 같은 역할의 실행은 재시도이며 다른 역할은 아니다."""
    # given
    command = "python3 /p/scripts/role_runner.py scout --assignment a --result ra --assignment b --result rb"
    events = [
        user("go"),
        bash("r1", command), result("r1", '{"exit": 3}'),
        bash("r2", "python3 /p/scripts/role_runner.py scout --assignment a --result ra"), result("r2", '{"exit": 0}'),
        bash("r3", "python3 /p/scripts/role_runner.py reviewer --assignment a --result ra"),
    ]

    # when
    requests = counted(events)

    # then
    assert requests == [{"runs": 4, "retries": 1}]


def test_시스템_메시지와_도구_결과와_자식_실행의_입력은_프롬프트가_아니다():
    """훅 피드백, 이어가기 요약, 작업 알림, sdk 입력, 도구 결과는 요청을 시작하지 않는다."""
    # given
    events = [
        user("real"),
        user("Stop hook feedback: rewrite", origin=None, isMeta=True),
        user("This session is being continued from a previous conversation", origin="human"),
        user("<task-notification>x</task-notification>", origin="task_notification"),
        user("child run prompt", origin="sdk"),
        result("x"),
    ]

    # when
    requests = counted(events)

    # then
    assert requests == [{"runs": 0, "retries": 0}]


def test_창_밖에서_시작한_요청은_뺀다():
    """30일 창보다 앞선 프롬프트의 요청은 세지 않는다."""
    # given
    old = user("old")
    old["timestamp"] = "2026-09-01T00:00:00Z"
    since = datetime(2026, 10, 17, tzinfo=timezone.utc)
    events = [old, launch("a"), user("new"), launch("b"), launch("c")]

    # when
    requests = dist.count_requests(dist.claude_events(events), since)

    # then
    assert requests == [{"runs": 2, "retries": 0}]


def test_Codex_spawn_agent와_맥락_메시지():
    """AGENTS 맥락 메시지는 프롬프트가 아니고, 오류 뒤 같은 유형의 spawn_agent 는 재시도다."""
    # given
    events = [
        codex_user("# AGENTS.md instructions for /x"),
        codex_user("do it"),
        codex_call("1", "spawn_agent", arguments=json.dumps({"agent_type": "scout"})),
        codex_output("1", '{"error": "no thread"}'),
        codex_call("2", "spawn_agent", arguments=json.dumps({"agent_type": "scout"})),
    ]

    # when
    requests = dist.count_requests(dist.codex_events(events))

    # then
    assert requests == [{"runs": 2, "retries": 1}]


def test_codex_exec로_시작한_세션은_자식_실행이라_아무것도_세지_않는다():
    """source 가 exec 인 Codex 세션은 role runner 자식이므로 요청으로 세지 않는다."""
    # given
    events = [{"type": "session_meta", "payload": {"source": "exec"}}, codex_user("child task"), codex_call("1", "spawn_agent")]

    # when
    requests = dist.count_requests(dist.codex_events(events))

    # then
    assert requests == []


def test_기본_한도는_가장_큰_개수에서_나온다():
    """실행 한도는 가장 큰 개수 위의 가장 작은 10의 배수이고, 재시도 한도는 가장 큰 개수에 1을 더한 값이다."""
    # given
    def caps(runs, retries):
        return dist.default_caps({"requests_with_delegated_run": 1, "largest_runs": runs, "largest_retries": retries})

    # when
    results = [caps(30, 2), caps(33, 4), caps(9, 0)]

    # then
    assert results == [
        {"run_cap_default": 40, "retry_cap_default": 3},
        {"run_cap_default": 40, "retry_cap_default": 5},
        {"run_cap_default": 10, "retry_cap_default": 1},
    ]


def test_위임_실행이_있는_요청이_없는_기간은_두_한도를_0으로_두고_이유를_남긴다():
    """위임 실행이 있는 요청이 하나도 없으면 두 기본 한도는 0이고 이유가 기록에 있다."""
    # given
    requests = [{"runs": 0, "retries": 0}]

    # when
    record = dist.distribution(requests, date(2026, 11, 16))

    # then
    assert (record["run_cap_default"], record["retry_cap_default"]) == (0, 0)
    assert "no request" in record["reason"]


def test_분포는_개수만_담는다():
    """분포는 요청 수와 개수별 요청 수만 담는다."""
    # given
    requests = [{"runs": 2, "retries": 1}, {"runs": 0, "retries": 0}]

    # when
    record = dist.distribution(requests, date(2026, 11, 16))

    # then
    assert record["runs_per_request"] == {"0": 1, "2": 1}
    assert record["requests"] == 2 and record["requests_with_delegated_run"] == 1


def test_커밋한_기록은_세션_내용_없이_분포와_유도한_기본값만_담는다():
    """커밋한 기록의 합계와 최댓값과 기본 한도가 분포에서 다시 계산한 값과 같고 키가 정해진 집합이다."""
    # given
    derived = dist.default_caps(RECORD)

    # when
    keys = set(RECORD)

    # then
    assert RECORD["window_days"] == 30 and RECORD["requests"] == sum(RECORD["runs_per_request"].values())
    assert RECORD["requests"] == sum(RECORD["retries_per_request"].values())
    assert RECORD["largest_runs"] == max(int(count) for count in RECORD["runs_per_request"])
    assert RECORD["largest_retries"] == max(int(count) for count in RECORD["retries_per_request"])
    assert (RECORD["run_cap_default"], RECORD["retry_cap_default"]) == (derived["run_cap_default"], derived["retry_cap_default"])
    assert keys == {
        "window_days", "through", "requests", "requests_with_delegated_run", "runs_per_request", "retries_per_request",
        "largest_runs", "largest_retries", "run_cap_default", "retry_cap_default", "sessions_with_requests",
    }


def test_커밋한_기록의_어떤_요청도_기본_한도에서_거부되지_않는다():
    """가장 큰 실행 수와 재시도 수가 각각 기본 한도보다 작다."""
    # given / when
    largest = (RECORD["largest_runs"], RECORD["largest_retries"])

    # then
    assert largest[0] < RECORD["run_cap_default"]
    assert largest[1] < RECORD["retry_cap_default"]
