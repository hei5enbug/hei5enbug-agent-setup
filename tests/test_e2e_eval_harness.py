"""Unit tests for the end-to-end evaluation harness core: transcripts, usage and cost, scheduling, resume, and process control."""

from __future__ import annotations

import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals/e2e"))

from harness import (  # noqa: E402
    campaign, collect, command, environment, matrix, metrics, plugin_export, pricing, process, rubric, runner, summarize,
    transcript, usage,
)
from harness.config import HarnessConfig  # noqa: E402
from harness.pilot_check import command_problems  # noqa: E402

OPUS = "claude-opus-5-5"
SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-5-5"
SCOUT = "demo-plugin:scout"


def claude_usage(i: int = 2, o: int = 10, read: int = 0, w1h: int = 0, w5m: int = 0) -> dict[str, Any]:
    return {
        "input_tokens": i, "output_tokens": o, "cache_read_input_tokens": read,
        "cache_creation_input_tokens": w1h + w5m,
        "cache_creation": {"ephemeral_5m_input_tokens": w5m, "ephemeral_1h_input_tokens": w1h},
    }


def assistant(mid: str, block: dict[str, Any], usage_: dict[str, Any] | None = None, parent: str | None = None,
              model: str = OPUS, **extra: Any) -> dict[str, Any]:
    message = {"id": mid, "model": model, "role": "assistant", "content": [block], "usage": usage_ or claude_usage()}
    return {"type": "assistant", "message": message, "parent_tool_use_id": parent, **extra}


def tool_use(tool_id: str, name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}


def text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def tool_result(tool_id: str, text: str, is_error: bool = False, parent: str | None = None) -> dict[str, Any]:
    block = {"type": "tool_result", "tool_use_id": tool_id, "content": text, "is_error": is_error}
    return {"type": "user", "message": {"role": "user", "content": [block]}, "parent_tool_use_id": parent}


def result_message(**fields: Any) -> dict[str, Any]:
    return {"type": "result", "subtype": "success", "is_error": False, "result": "done", "num_turns": 3,
            "total_cost_usd": 0.5, "duration_api_ms": 900, "session_id": "s-1", "permission_denials": [], **fields}


def init_message(path: str = "/tmp/work/plugins/abc1234/hei5enbug-agent-setup") -> dict[str, Any]:
    plugins = [{"name": "hei5enbug-agent-setup", "source": "hei5enbug-agent-setup@inline", "path": path}]
    return {"type": "system", "subtype": "init", "session_id": "s-1", "permissionMode": "auto", "plugins": plugins}


def status_line(role: str, exit_code: int, rollout: str | None = None) -> str:
    evidence = {"rollout": rollout} if rollout else {}
    return json.dumps({"role": role, "runner": "codex", "model": "gpt-6-astra", "verified": True,
                       "evidence": evidence, "exit": exit_code})


def role_runner_command(role: str, body: str = "Review calc.py.") -> str:
    return (f"cat > /tmp/work/a.md <<'EOF'\n{body}\nEOF\n"
            f"python3 /tmp/plugin/scripts/role_runner.py {role} --assignment /tmp/work/a.md --result /tmp/work/r.md")


def sample_events() -> list[dict[str, Any]]:
    return [
        init_message(),
        assistant("m1", text_block("Plan: delegate a scan."), claude_usage(2, 20, 100, 500)),
        assistant("m2", tool_use("tu-agent", "Agent", {"subagent_type": SCOUT, "prompt": "List functions.", "description": "scan"}),
                  claude_usage(2, 30, 120, 10)),
        assistant("s1", tool_use("tu-read", "Read", {"file_path": "calc.py"}), claude_usage(4, 8, 0, 800), parent="tu-agent",
                  model=SONNET, subagent_type=SCOUT),
        tool_result("tu-read", "def add(a, b): ...", parent="tu-agent"),
        assistant("m3", tool_use("tu-edit", "Edit", {"file_path": "calc.py"}), claude_usage(2, 15, 150, 5)),
        tool_result("tu-edit", "edited"),
        assistant("m4", tool_use("tu-rr", "Bash", {"command": role_runner_command("reviewer")}), claude_usage(2, 12, 160, 5)),
        tool_result("tu-rr", "/tmp/x\n" + status_line("reviewer", 0, "/home/test/.codex/sessions/2026/10/25/rollout-r1.jsonl")),
        assistant("m5", text_block("All finished."), claude_usage(2, 9, 170, 5)),
        result_message(result="All finished."),
    ]


class TranscriptViewTest(unittest.TestCase):
    def test_메인_세션과_서브에이전트의_도구_호출을_출처별로_구분한다(self):
        """스트림에 섞인 도구 호출은 parent가 없으면 main, 있으면 subagent:<타입>으로 나뉜다."""
        # given
        events = sample_events()

        # when
        view = transcript.build_view(events)

        # then
        sources = {call["id"]: call["source"] for call in view["tool_calls"]}
        self.assertEqual(sources["tu-read"], f"subagent:{SCOUT}")
        self.assertEqual({sources[k] for k in ("tu-agent", "tu-edit", "tu-rr")}, {"main"})
        self.assertEqual([c["id"] for c in view["tool_calls"]], ["tu-agent", "tu-read", "tu-edit", "tu-rr"])

    def test_서브에이전트_기록에만_있는_도구_호출도_뷰에_들어온다(self):
        """스트림에 없는 서브에이전트 도구 호출은 서브에이전트 기록에서 채워진다."""
        # given
        record_events = [assistant("s9", tool_use("tu-sub", "Bash", {"command": "ls"})), tool_result("tu-sub", "a.py")]
        subagents = [{"meta": {"agentType": SCOUT, "toolUseId": "tu-agent", "model": SONNET}, "events": record_events}]

        # when
        view = transcript.build_view(sample_events(), subagents)

        # then
        added = next(call for call in view["tool_calls"] if call["id"] == "tu-sub")
        self.assertEqual((added["source"], added["parent"], added["result_text"]), (f"subagent:{SCOUT}", "tu-agent", "a.py"))

    def test_최종_답변은_결과_메시지의_result_텍스트이고_없으면_빈_문자열이다(self):
        """result 메시지가 없는 스트림의 final_answer는 빈 문자열이다."""
        # given
        events = [e for e in sample_events() if e["type"] != "result"]

        # when
        view = transcript.build_view(events)

        # then
        self.assertEqual(view["final_answer"], "")
        self.assertEqual(transcript.build_view(sample_events())["final_answer"], "All finished.")

    def test_어시스턴트_텍스트는_메인_세션_블록만_순서대로_담는다(self):
        """서브에이전트가 쓴 텍스트는 assistant_texts에 들어가지 않는다."""
        # given
        events = sample_events()
        events.insert(4, assistant("s2", text_block("sub text"), parent="tu-agent", subagent_type=SCOUT))

        # when
        view = transcript.build_view(events)

        # then
        self.assertEqual(view["assistant_texts"], ["Plan: delegate a scan.", "All finished."])

    def test_Agent_호출은_종류_분류_프롬프트와_함께_위임으로_기록된다(self):
        """Agent 도구 호출은 subagent_type과 분류, 프롬프트, 호출 순서를 가진 위임이 된다."""
        # given
        events = sample_events()

        # when
        view = transcript.build_view(events)

        # then
        agent = next(d for d in view["delegations"] if d["kind"] == "agent")
        self.assertEqual((agent["type"], agent["class"], agent["prompt"], agent["order"], agent["exit"]),
                         (SCOUT, "investigation", "List functions.", 0, None))

    def test_role_runner_호출은_역할_종료코드_할당_텍스트를_위임으로_기록한다(self):
        """role_runner Bash 호출은 상태 줄의 exit와 heredoc 할당 텍스트를 담은 review 위임이 된다."""
        # given
        events = sample_events()

        # when
        view = transcript.build_view(events)

        # then
        runner_call = next(d for d in view["delegations"] if d["kind"] == "role_runner")
        self.assertEqual((runner_call["type"], runner_call["class"], runner_call["exit"]), ("reviewer", "review", 0))
        self.assertEqual(runner_call["prompt"], "Review calc.py.")

    def test_종료코드_접두어가_있는_role_runner_결과는_그_코드를_쓴다(self):
        """상태 줄이 없고 Exit code 3으로 시작하는 결과는 exit 3이다."""
        # given
        events = [assistant("a", tool_use("t1", "Bash", {"command": role_runner_command("worker")})),
                  tool_result("t1", "Exit code 3\nfailed", is_error=True)]

        # when
        view = transcript.build_view(events)

        # then
        self.assertEqual((view["delegations"][0]["exit"], view["delegations"][0]["class"]), (3, "implementation"))

    def test_role_runner를_읽기만_하는_명령은_위임이_아니다(self):
        """role_runner.py 뒤에 역할이 없는 명령은 위임으로 세지 않는다."""
        # given
        events = [assistant("a", tool_use("t1", "Bash", {"command": "cat scripts/role_runner.py | head"})), tool_result("t1", "x")]

        # when
        view = transcript.build_view(events)

        # then
        self.assertEqual(view["delegations"], [])

    def test_승인_로그와_권한_거부가_뷰에_담긴다(self):
        """approvals.jsonl 줄과 결과 메시지의 permission_denials가 그대로 뷰에 들어간다."""
        # given
        events = [result_message(permission_denials=[{"tool_name": "Bash"}])]
        approvals = [{"tool_name": "Bash"}, {"tool_name": "Edit"}]

        # when
        view = transcript.build_view(events, approvals=approvals)

        # then
        self.assertEqual((len(view["approvals"]), len(view["permission_denials"])), (2, 1))


class UsageLimitTest(unittest.TestCase):
    def test_오류_결과_메시지의_한도_문구를_사용량_한도로_감지한다(self):
        """is_error 결과의 텍스트가 usage limit 문구와 맞으면 사유를 돌려준다."""
        # given
        events = [result_message(is_error=True, result="You have hit your limit. Resets at 5pm.")]

        # when
        reason = transcript.usage_limit_reason(events)

        # then
        self.assertIsNotNone(reason)

    def test_거절된_rate_limit_이벤트를_사용량_한도로_감지한다(self):
        """rate_limit_info.status가 rejected면 한도로 본다."""
        # given
        events = [{"type": "rate_limit_event", "rate_limit_info": {"status": "rejected"}}]

        # when
        reason = transcript.usage_limit_reason(events)

        # then
        self.assertEqual(reason, "rate_limit_event rejected")

    def test_초과분만_거절되고_상태가_allowed인_이벤트는_한도가_아니다(self):
        """overageStatus가 rejected여도 status가 allowed면 한도가 아니다."""
        # given
        info = {"status": "allowed", "overageStatus": "rejected"}
        events = [{"type": "rate_limit_event", "rate_limit_info": info}, result_message()]

        # when
        reason = transcript.usage_limit_reason(events)

        # then
        self.assertIsNone(reason)

    def test_rate_limit_재시도_뒤에_성공한_어시스턴트_메시지가_없으면_한도다(self):
        """api_retry rate_limit 뒤에 어시스턴트 메시지가 오면 한도가 아니고 없으면 한도다."""
        # given
        retry = {"type": "system", "subtype": "api_retry", "error": "rate_limit"}
        stopped = [retry]
        recovered = [retry, assistant("m1", text_block("ok"))]

        # when
        reasons = (transcript.usage_limit_reason(stopped), transcript.usage_limit_reason(recovered))

        # then
        self.assertIsNotNone(reasons[0])
        self.assertIsNone(reasons[1])

    def test_일반_오류_결과는_한도로_보지_않는다(self):
        """한도 문구가 없는 is_error 결과는 한도가 아니다."""
        # given
        events = [result_message(is_error=True, result="tool crashed")]

        # when
        reason = transcript.usage_limit_reason(events)

        # then
        self.assertIsNone(reason)


class TokenUsageTest(unittest.TestCase):
    def test_같은_메시지_ID가_블록마다_반복되어도_한_번만_센다(self):
        """같은 메시지 ID의 반복 줄은 하나의 요청이고 마지막 사용량을 쓴다."""
        # given
        events = [assistant("m1", text_block("a"), claude_usage(2, 5)), assistant("m1", tool_use("t", "Bash", {}), claude_usage(2, 90)),
                  assistant("m2", text_block("b"), claude_usage(3, 7))]

        # when
        requests = usage.claude_requests(events)

        # then
        self.assertEqual([(r["id"], r["input"], r["output"]) for r in requests], [("m1", 2, 90), ("m2", 3, 7)])

    def test_합성_모델과_사용량_없는_메시지는_건너뛴다(self):
        """model이 <synthetic>이거나 usage가 없으면 요청으로 세지 않는다."""
        # given
        events = [assistant("m1", text_block("a"), model="<synthetic>"), {"type": "assistant", "message": {"id": "m2", "model": OPUS}}]

        # when
        requests = usage.claude_requests(events)

        # then
        self.assertEqual(requests, [])

    def test_토큰은_출처_모델별로_집계되고_캐시_쓰기는_5분과_1시간으로_나뉜다(self):
        """main과 서브에이전트 기록의 토큰이 출처, 모델별로 합산된다."""
        # given
        main = [assistant("m1", text_block("a"), claude_usage(2, 10, 100, 40, 30)), assistant("m2", text_block("b"), claude_usage(1, 5, 50, 0, 20))]
        sub = [{"meta": {"agentType": SCOUT}, "events": [assistant("s1", text_block("c"), claude_usage(4, 8, 0, 0, 800), model=SONNET)]}]

        # when
        by_source, label = usage.claude_requests_by_source(main, sub, [])
        report = usage.claude_token_report(by_source)

        # then
        self.assertEqual(label, "transcripts")
        self.assertEqual(report["tokens"]["main"][OPUS], {"input": 3, "output": 15, "cache_read": 150, "cache_write_5m": 50,
                                                          "cache_write_1h": 40, "cache_write": 90})
        self.assertEqual(report["tokens"][f"subagent:{SCOUT}"][SONNET]["cache_write_5m"], 800)

    def test_기록이_없으면_스트림의_사용량으로_대신한다(self):
        """메인 기록이 없으면 스트림 이벤트에서 출처를 나눠 쓰고 라벨이 stream이다."""
        # given
        events = sample_events()

        # when
        by_source, label = usage.claude_requests_by_source(None, [], events)

        # then
        self.assertEqual(label, "stream")
        self.assertEqual(sorted(by_source), ["main", f"subagent:{SCOUT}"])

    def test_파일럿_사용량의_Claude_목록가는_0점2211772와_같다(self):
        """입력 6, 1시간 쓰기 24101, 읽기 82726, 출력 590은 opus에서 0.2211772 달러다."""
        # given
        events = [assistant("a", text_block("x"), claude_usage(2, 100, 30000, 20000)),
                  assistant("b", text_block("y"), claude_usage(2, 200, 30000, 3000)),
                  assistant("c", text_block("z"), claude_usage(2, 290, 22726, 1101))]

        # when
        report = usage.claude_token_report({"main": usage.claude_requests(events)})

        # then
        self.assertAlmostEqual(report["list_cost_usd"], 0.2211772, delta=1e-6)

    def test_Haiku는_프롬프트가_10만_토큰을_넘으면_긴_프롬프트_단가를_쓴다(self):
        """프롬프트 10만 이하는 짧은 단가, 초과는 긴 단가다."""
        # given
        short = {"input": 100_000, "output": 1000, "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0}
        long = {**short, "input": 100_001}

        # when
        costs = (pricing.claude_cost(HAIKU, short), pricing.claude_cost(HAIKU, long))

        # then
        self.assertAlmostEqual(costs[0], 100_000 * 0.10 / 1e6 + 1000 * 0.50 / 1e6)
        self.assertAlmostEqual(costs[1], 100_001 * 0.50 / 1e6 + 1000 * 2.50 / 1e6)

    def test_가격표에_없는_Claude_모델은_비용이_None이고_보고서에_표시된다(self):
        """가격이 없는 모델은 비용 대신 unpriced_models에 이름이 남는다."""
        # given
        events = [assistant("a", text_block("x"), model="claude-unknown-9")]

        # when
        report = usage.claude_token_report({"main": usage.claude_requests(events)})

        # then
        self.assertEqual(report["unpriced_models"], ["claude-unknown-9"])
        self.assertIsNone(pricing.claude_cost("claude-unknown-9", {}))


def codex_events(model: str, requests: list[tuple[dict[str, int], dict[str, int]]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = [{"type": "session_meta", "payload": {"cwd": "/tmp/work/repo"}},
                                    {"type": "turn_context", "payload": {"model": model}}]
    for total, last in requests:
        info = {"total_token_usage": total, "last_token_usage": last}
        events.append({"type": "event_msg", "payload": {"type": "token_count", "info": info}})
    return events


def codex_usage(inp: int, cached: int = 0, out: int = 0, write: int = 0) -> dict[str, int]:
    return {"input_tokens": inp, "cached_input_tokens": cached, "cache_write_input_tokens": write,
            "output_tokens": out, "reasoning_output_tokens": 0}


class CodexCostTest(unittest.TestCase):
    def test_롤아웃의_같은_누적치_토큰_이벤트는_한_요청으로_센다(self):
        """total_token_usage가 같은 반복 이벤트는 중복이고 마지막 사용량 기준으로 요청마다 집계된다."""
        # given
        first, second = codex_usage(1000, 400, 50), codex_usage(500, 100, 20)
        events = codex_events("gpt-6.1-sol", [(first, first), (first, first), ({**first, "input_tokens": 1500}, second)])

        # when
        requests = usage.codex_requests(events)

        # then
        self.assertEqual(len(requests), 2)
        self.assertEqual((requests[0]["input"], requests[0]["cache_read"], requests[1]["input"]), (600, 400, 400))

    def test_Codex_추정_비용은_캐시_입력을_뺀_입력과_출력을_단가대로_더한다(self):
        """sol 요청 하나: 비캐시 600, 캐시 400, 출력 50의 추정 비용이다."""
        # given
        first = codex_usage(1000, 400, 50)
        rollout = {"role": "reviewer", "events": codex_events("gpt-6.1-sol", [(first, first)])}

        # when
        report = usage.codex_token_report([rollout])

        # then
        self.assertAlmostEqual(report["list_cost_usd_estimate"], (600 * 2 + 400 * 0.10 + 50 * 10) / 1e6)
        self.assertEqual(report["tokens"]["codex:reviewer"]["gpt-6.1-sol"]["input"], 600)

    def test_요청_입력이_27만2천_토큰을_넘으면_긴_컨텍스트_단가를_쓴다(self):
        """한 요청의 입력이 272000 초과면 sol의 긴 컨텍스트 단가가 적용된다."""
        # given
        request = {"input": 300_000, "cache_read": 0, "cache_write": 0, "output": 100}

        # when
        cost = pricing.codex_cost("gpt-6.1-sol", request)

        # then
        self.assertAlmostEqual(cost, (300_000 * 4 + 100 * 15) / 1e6)

    def test_가격표에_없는_Codex_모델은_토큰만_세고_비용에서_뺀다(self):
        """알 수 없는 모델은 비용 0으로 더해지지 않고 unpriced_models에 표시된다."""
        # given
        only = codex_usage(1000, 0, 10)
        rollout = {"role": "unknown", "events": codex_events("gpt-9-mystery", [(only, only)])}

        # when
        report = usage.codex_token_report([rollout])

        # then
        self.assertEqual((report["list_cost_usd_estimate"], report["unpriced_models"]), (0.0, ["gpt-9-mystery"]))
        self.assertEqual(report["tokens"]["codex:unknown"]["gpt-9-mystery"]["output"], 10)

    def test_롤아웃은_role_runner_상태_줄의_경로로_역할에_연결된다(self):
        """Bash 결과의 status 줄에 적힌 롤아웃 파일 이름이 그 역할로 매핑된다."""
        # given
        view = transcript.build_view(sample_events())

        # when
        roles = collect.rollout_roles(view["tool_calls"])

        # then
        self.assertEqual(roles, {"rollout-r1.jsonl": "reviewer"})


class RetriesAndMetricsTest(unittest.TestCase):
    def test_같은_실패_명령_재실행_Agent_재호출_role_runner_재실행을_재시도로_센다(self):
        """세 종류의 재시도가 각각 하나씩 있으면 합계는 3이다."""
        # given
        events = [
            assistant("a", tool_use("b1", "Bash", {"command": "pytest -q"})), tool_result("b1", "Exit code 1\nfail", True),
            assistant("b", tool_use("b2", "Bash", {"command": "pytest -q"})), tool_result("b2", "ok"),
            assistant("c", tool_use("g1", "Agent", {"subagent_type": SCOUT, "prompt": "p"})), tool_result("g1", "boom", True),
            assistant("d", tool_use("g2", "Agent", {"subagent_type": SCOUT, "prompt": "p"})), tool_result("g2", "fine"),
            assistant("e", tool_use("r1", "Bash", {"command": role_runner_command("reviewer")})), tool_result("r1", "Exit code 3\nx", True),
            assistant("f", tool_use("r2", "Bash", {"command": role_runner_command("reviewer")})), tool_result("r2", status_line("reviewer", 0)),
        ]
        view = transcript.build_view(events)

        # when
        retries = metrics.count_retries(view)

        # then
        self.assertEqual(retries, {"bash": 1, "agent": 1, "role_runner": 1, "total": 3})

    def test_다른_출처에서_같은_명령을_실행해도_재시도가_아니다(self):
        """메인의 실패 명령을 서브에이전트가 다시 실행해도 같은 출처가 아니므로 세지 않는다."""
        # given
        events = [assistant("a", tool_use("b1", "Bash", {"command": "make"})), tool_result("b1", "Exit code 2", True),
                  assistant("s", tool_use("b2", "Bash", {"command": "make"}), parent="g", subagent_type=SCOUT), tool_result("b2", "ok", parent="g")]
        view = transcript.build_view(events)

        # when
        retries = metrics.count_retries(view)

        # then
        self.assertEqual(retries["bash"], 0)

    def test_승인_프롬프트_수는_승인_로그_줄_수이고_도구_호출은_출처별로_센다(self):
        """metrics의 approval_prompts는 approvals 줄 수, 도구 호출은 main/subagent/total로 나뉜다."""
        # given
        view = transcript.build_view(sample_events(), approvals=[{"tool_name": "Bash"}, {"tool_name": "Edit"}, {"tool_name": "Bash"}])
        run = {"run_id": "T01-baseline-r1", "task": "T01", "variant": "baseline", "rep": 1, "status": "complete"}
        empty = {"tokens": {}, "list_cost_usd": 0.0, "unpriced_models": []}
        codex = {"tokens": {}, "list_cost_usd_estimate": 0.0, "unpriced_models": []}

        # when
        result = metrics.build_metrics(run=run, task={}, view=view, facts=metrics.stream_facts(sample_events()), claude_report=empty,
                                       codex_report=codex, grade={"success": True, "constraints": []}, rubric=None,
                                       checks={}, usage_source="stream")

        # then
        self.assertEqual(result["approval_prompts"], 3)
        self.assertEqual(result["tool_calls_by_tool"]["total"]["Read"], 1)
        self.assertEqual(result["tool_calls_by_tool"]["main"].get("Read"), None)
        self.assertEqual(result["role_runner_calls"], {"reviewer": {"0": 1}})
        self.assertEqual(result["subagent_launches_by_type"], {SCOUT: 1})

    def test_인계_누락은_채점_결과의_제약_누락과_추적된_실패로_센다(self):
        """grade의 constraints에서 누락 위임 수와 추적된 실패 체크 ID를 모은다."""
        # given
        grade = {"constraints": [{"id": "c1", "missing_in": ["a", "b"], "traced_failures": ["mirror"]},
                                 {"id": "c2", "missing_in": [], "traced_failures": []}]}

        # when
        result = metrics.handoff(grade)

        # then
        self.assertEqual(result, {"constraints": 2, "missing": 2, "traced_failures": ["mirror"]})

    def test_루브릭이_있는_과제는_평균이_기준을_넘어야_성공이다(self):
        """결정적 채점을 통과해도 루브릭이 통과하지 못하면 성공이 아니다."""
        # given
        task = {"rubric": {"pass_mean": 3.5}}
        grade = {"success": True}

        # when
        outcomes = (metrics.merged_success(grade, task, {"passed": False}), metrics.merged_success(grade, task, {"passed": True}))

        # then
        self.assertEqual(outcomes, (False, True))

    def test_플러그인_점검은_내보낸_경로와_설치본_부재와_모드_표식을_본다(self):
        """init 이벤트와 메인 기록에서 세 가지 플러그인 사실을 읽는다."""
        # given
        facts = metrics.stream_facts([init_message("/tmp/work/export")])
        attachment = {"attachment": {"type": "hook_additional_context", "content": ["hei5enbug-agent-setup mod: role pinning active"]}}

        # when
        checks = metrics.plugin_checks(facts, "/tmp/work/export", [attachment], [])

        # then
        self.assertEqual((checks["loaded_from_export"], checks["installed_absent"], checks["mod_marker_present"]), (True, True, True))
        self.assertEqual(checks["permission_mode"], "auto")


class MatrixTest(unittest.TestCase):
    def test_변형이_둘이면_짝마다_시작_변형이_번갈아_ABAB_BABA_순서가_된다(self):
        """과제 두 개, 반복 두 번이면 AB, BA, AB, BA 순서로 변형이 돈다."""
        # given
        tasks, variants = ["T01", "T02"], ["A", "B"]

        # when
        order = matrix.plan_matrix(tasks, variants, 2)

        # then
        self.assertEqual([(r, t, v) for r, t, v in order],
                         [(1, "T01", "A"), (1, "T01", "B"), (1, "T02", "B"), (1, "T02", "A"),
                          (2, "T01", "A"), (2, "T01", "B"), (2, "T02", "B"), (2, "T02", "A")])

    def test_변형이_하나면_반복이_바깥이고_과제가_안쪽인_순서다(self):
        """변형 하나는 과제 곱하기 반복 순서 그대로다."""
        # given
        tasks = ["T01", "T02"]

        # when
        order = matrix.plan_matrix(tasks, ["baseline"], 2)

        # then
        self.assertEqual(order, [(1, "T01", "baseline"), (1, "T02", "baseline"), (2, "T01", "baseline"), (2, "T02", "baseline")])

    def test_실행_ID는_과제_변형_반복으로_만든다(self):
        """run_id 형식은 <과제>-<변형>-r<k>이다."""
        # given / when
        run_id = matrix.run_id_for("T03", "baseline", 2)

        # then
        self.assertEqual(run_id, "T03-baseline-r2")


class ResumeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def spec(self, task: str = "T01", rep: int = 1) -> matrix.RunSpec:
        return matrix.make_spec(self.root, "camp", task, "baseline", rep)

    def test_완료와_시간초과_실행은_건너뛰고_나머지는_다시_시작한다(self):
        """complete/timed_out은 건너뛰고 usage_limited/infra_failed/미기록은 시작 목록에 든다."""
        # given
        specs = [self.spec(f"T0{i}") for i in range(1, 6)]
        state = {specs[0].run_id: "complete", specs[1].run_id: "timed_out", specs[2].run_id: "usage_limited",
                 specs[3].run_id: "infra_failed"}

        # when
        start, skipped = matrix.runs_to_start(specs, state)

        # then
        self.assertEqual([s.task for s in skipped], ["T01", "T02"])
        self.assertEqual([s.task for s in start], ["T03", "T04", "T05"])

    def test_only_rerun에_적힌_완료_실행은_다시_시작한다(self):
        """완료된 실행도 only-rerun 목록에 있으면 시작 목록에 든다."""
        # given
        spec = self.spec()

        # when
        start, skipped = matrix.runs_to_start([spec], {spec.run_id: "complete"}, frozenset({spec.run_id}))

        # then
        self.assertEqual((len(start), len(skipped)), (1, 0))

    def test_다시_시작하는_실행의_이전_결과는_attempts_아래로_옮겨진다(self):
        """기존 결과 폴더는 attempts/rep<k>/<n>으로 이동하고 횟수가 늘어난다."""
        # given
        spec = self.spec()
        spec.result_dir.mkdir(parents=True)
        (spec.result_dir / "run.json").write_text("{}", encoding="utf-8")
        matrix.move_aside(spec)
        spec.result_dir.mkdir(parents=True)
        (spec.result_dir / "marker.txt").write_text("second", encoding="utf-8")

        # when
        moved = matrix.move_aside(spec)

        # then
        self.assertEqual(moved.name, "2")
        self.assertTrue((moved / "marker.txt").is_file())
        self.assertTrue((moved.parent / "1" / "run.json").is_file())
        self.assertFalse(spec.result_dir.exists())
        self.assertEqual(matrix.prior_attempts(spec), 2)

    def test_상태_파일은_실행_ID별_상태를_저장하고_다시_읽는다(self):
        """CampaignState는 set한 상태를 파일로 남기고 새 인스턴스가 읽는다."""
        # given
        path = self.root / "state.json"
        matrix.CampaignState(path).set("T01-baseline-r1", "complete")

        # when
        reloaded = matrix.CampaignState(path).snapshot()

        # then
        self.assertEqual(reloaded, {"T01-baseline-r1": "complete"})


def fake_run_function(statuses: dict[str, str], calls: list[str]):
    def run(spec, task, variant, plugin, cfg, snapshot):
        calls.append(spec.run_id)
        spec.result_dir.mkdir(parents=True, exist_ok=True)
        return {"run_id": spec.run_id, "status": statuses.get(spec.run_id, "complete")}
    return run


class CampaignTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        tasks = self.root / "tasks"
        (tasks / "prompts").mkdir(parents=True)
        for task_id in ("T01", "T02", "T03"):
            body = {"id": task_id, "fixture": "demo", "prompt_file": f"prompts/{task_id}.txt",
                    "limits": {"wall_seconds": 60, "max_budget_usd": 1}}
            (tasks / f"{task_id}.json").write_text(json.dumps(body), encoding="utf-8")
            (tasks / "prompts" / f"{task_id}.txt").write_text("do it\n", encoding="utf-8")
        variants = self.root / "variants"
        variants.mkdir()
        (variants / "baseline.json").write_text('{"name": "baseline", "ref": "HEAD"}', encoding="utf-8")
        self.cfg = HarnessConfig(run_root=self.root / "runs", tasks_root=tasks, variants_root=variants)
        patches = [mock.patch.object(campaign.plugin_export, "export_plugin", return_value={"ref": "HEAD", "sha": "abc", "path": "/tmp/p"}),
                   mock.patch.object(campaign.environment, "capture_base", return_value={})]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def run_all(self, statuses: dict[str, str], calls: list[str], parallel: int = 1) -> int:
        return campaign.run_campaign(self.cfg, "c1", ["T01", "T02", "T03"], ["baseline"], 1, parallel, frozenset(), io.StringIO(),
                                     fake_run_function(statuses, calls))

    def test_사용량_한도를_만나면_새_실행을_멈추고_종료코드_75를_돌려준다(self):
        """두 번째 실행이 usage_limited면 세 번째는 시작하지 않고 75로 끝난다."""
        # given
        calls: list[str] = []

        # when
        code = self.run_all({"T02-baseline-r1": "usage_limited"}, calls)

        # then
        self.assertEqual(code, 75)
        self.assertEqual(calls, ["T01-baseline-r1", "T02-baseline-r1"])

    def test_이어서_실행하면_완료된_실행은_건너뛰고_한도로_멈춘_실행부터_다시_한다(self):
        """재개 때 T01은 건너뛰고 T02, T03만 실행하며 종료코드는 0이다."""
        # given
        self.run_all({"T02-baseline-r1": "usage_limited"}, [])
        calls: list[str] = []

        # when
        code = self.run_all({}, calls)

        # then
        self.assertEqual((code, calls), (0, ["T02-baseline-r1", "T03-baseline-r1"]))

    def test_한도로_멈췄던_실행의_결과는_다시_실행하기_전에_attempts로_옮겨진다(self):
        """재시도할 때 이전 결과 폴더가 attempts/rep1/1로 이동한다."""
        # given
        self.run_all({"T02-baseline-r1": "usage_limited"}, [])
        spec = matrix.make_spec(self.cfg.run_root, "c1", "T02", "baseline", 1)
        (spec.result_dir / "old.txt").write_text("first attempt", encoding="utf-8")

        # when
        self.run_all({}, [])

        # then
        self.assertTrue((spec.result_dir.parent / "attempts" / "rep1" / "1" / "old.txt").is_file())

    def test_실행이_예외를_던지면_infra_failed로_기록하고_나머지는_계속한다(self):
        """한 실행의 예외가 전체를 멈추지 않고 상태에 infra_failed로 남는다."""
        # given
        def crashing(spec, *args):
            if spec.task == "T02":
                raise RuntimeError("boom")
            return {"run_id": spec.run_id, "status": "complete"}

        # when
        code = campaign.run_campaign(self.cfg, "c1", ["T01", "T02", "T03"], ["baseline"], 1, 1, frozenset(), io.StringIO(), crashing)

        # then
        state = matrix.CampaignState(self.cfg.run_root / "c1" / "state.json").snapshot()
        self.assertEqual((code, state["T02-baseline-r1"], state["T03-baseline-r1"]), (0, "infra_failed", "complete"))

    def test_드라이런은_계획과_전체_명령을_출력하고_아무것도_쓰지_않는다(self):
        """dry-run 출력에 run id와 필수 플래그가 있고 실행 루트에 파일이 생기지 않는다."""
        # given
        out = io.StringIO()
        tasks, variants = campaign.load_plan(self.cfg, ["T01"], ["baseline"])
        specs = campaign.build_specs(self.cfg, "c1", ["T01"], ["baseline"], 1)
        with mock.patch.object(campaign.plugin_export, "resolve_ref", return_value="abcdef1234567"):
            # when
            campaign.print_plan(out, self.cfg, specs, tasks, variants)

        # then
        text = out.getvalue()
        self.assertIn("T01-baseline-r1", text)
        self.assertIn("--max-budget-usd 1", text)
        self.assertFalse(self.cfg.run_root.exists())


class CommandLineTest(unittest.TestCase):
    def setUp(self):
        self.task = {"limits": {"wall_seconds": 60, "max_budget_usd": 7}}
        self.variant = command.validate_variant({"name": "baseline", "ref": "HEAD", "settings": {}, "env": {}, "extra_args": []})

    def build(self, variant: dict[str, Any] | None = None) -> list[str]:
        return command.build_command(HarnessConfig(), self.task, variant or self.variant, "prompt", "/tmp/p", Path("/tmp/run"))

    def test_명령줄에는_우회_플래그와_permission_mode가_없다(self):
        """권한 우회, bare, permission-mode 어느 것도 명령줄에 들어가지 않는다."""
        # given / when
        argv = self.build()

        # then
        for banned in ("--dangerously-skip-permissions", "--bare", "--permission-mode", "bypassPermissions"):
            self.assertNotIn(banned, argv)

    def test_명령줄에는_플러그인_설정_승인도구_예산_플래그가_항상_있다(self):
        """네 필수 플래그와 값이 들어 있고 pilot-check가 문제를 찾지 못한다."""
        # given / when
        argv = self.build()

        # then
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "7")
        self.assertEqual(argv[argv.index("--plugin-dir") + 1], "/tmp/p")
        self.assertEqual(argv[argv.index("--settings") + 1], "/tmp/run/settings.json")
        self.assertEqual(argv[argv.index("--permission-prompt-tool") + 1], "mcp__eval_approver__approve")
        self.assertEqual(command_problems(argv), [])

    def test_변형의_extra_args에_우회_플래그가_있으면_거부한다(self):
        """변형 파일이 우회 플래그를 넣으려 하면 ConfigError다."""
        # given
        variant = {"name": "bad", "ref": "HEAD", "extra_args": ["--permission-mode", "plan"]}

        # when / then
        with self.assertRaises(command.ConfigError):
            command.validate_variant(variant)

    def test_변형_설정은_기본_설정_위에_깊게_합쳐진다(self):
        """enabledPlugins는 설치본 끄기를 유지하면서 변형 키가 추가된다."""
        # given
        variant = command.validate_variant({"name": "v", "ref": "HEAD", "settings": {"enabledPlugins": {"other@x": True}, "model": "m"}})

        # when
        settings = command.run_settings(variant)

        # then
        self.assertEqual(settings["enabledPlugins"], {"hei5enbug-agent-setup@hei5enbug": False, "other@x": True})
        self.assertEqual(settings["model"], "m")

    def test_승인_MCP_설정은_로그_경로를_환경으로_넘긴다(self):
        """mcp.json은 eval_approver 서버와 EVAL_APPROVAL_LOG 경로를 가진다."""
        # given / when
        config = command.mcp_config(Path("/tmp/run/approvals.jsonl"))

        # then
        server = config["mcpServers"]["eval_approver"]
        self.assertEqual(server["env"], {"EVAL_APPROVAL_LOG": "/tmp/run/approvals.jsonl"})
        self.assertTrue(server["args"][0].endswith("approval_mcp.py"))

    def test_자식_환경에서_ORCA_변수만_빠지고_이름이_기록된다(self):
        """ORCA_로 시작하는 변수는 제거되고 제거된 이름 목록이 돌아온다."""
        # given
        base = {"ORCA_TERMINAL": "t", "ORCA_X": "1", "PATH": "/bin", "HOME": "/home/test"}

        # when
        env, removed = environment.child_environment(base, {"EXTRA": "e"})

        # then
        self.assertEqual(removed, ["ORCA_TERMINAL", "ORCA_X"])
        self.assertEqual(env, {"PATH": "/bin", "HOME": "/home/test", "EXTRA": "e"})


FAKE_CLAUDE = """#!{python}
import json, os, signal, sys, time
out = os.environ["FAKE_OUT"]
with open(out, "w") as handle:
    json.dump({{"argv": sys.argv[1:], "env": sorted(os.environ)}}, handle)
mode = os.environ.get("FAKE_MODE", "complete")
if mode == "stubborn":
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(30)
print(json.dumps({{"type": "system", "subtype": "init", "session_id": "fake-1", "permissionMode": "auto", "plugins": []}}))
print(json.dumps({{"type": "assistant", "message": {{"id": "m1", "model": "claude-opus-5-5", "content": [{{"type": "text", "text": "ok"}}],
    "usage": {{"input_tokens": 2, "output_tokens": 5, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}}}, "parent_tool_use_id": None}}))
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "result": "ok", "num_turns": 1,
    "total_cost_usd": 0.01, "session_id": "fake-1", "permission_denials": []}}))
"""


class ProcessAndRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fake = self.root / "fake_claude"
        self.fake.write_text(FAKE_CLAUDE.format(python=sys.executable), encoding="utf-8")
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IEXEC)
        self.out = self.root / "fake_out.json"
        tasks = self.root / "tasks"
        (tasks / "prompts").mkdir(parents=True)
        (tasks / "prompts" / "T09.txt").write_text("clean up\n", encoding="utf-8")
        self.task = {"id": "T09", "fixture": "demo", "prompt_file": "prompts/T09.txt", "limits": {"wall_seconds": 1, "max_budget_usd": 1}}
        self.variant = command.validate_variant({"name": "baseline", "ref": "HEAD"})
        self.plugin = {"ref": "HEAD", "sha": "abc", "path": "/tmp/p"}
        self.cfg = HarnessConfig(run_root=self.root / "runs", tasks_root=tasks, claude_bin=str(self.fake), sigint_grace=0.3,
                                 sigterm_grace=0.3, extra_env={"FAKE_OUT": str(self.out)})
        self.spec = matrix.make_spec(self.cfg.run_root, "c", "T09", "baseline", 1)
        env_patch = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.root / "claude"), "CODEX_HOME": str(self.root / "codex"),
                                                  "ORCA_TERMINAL_HANDLE": "term-1"})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.graders = SimpleNamespace(materialize_fixture=self.materialize, grade_run=self.grade)
        patch = mock.patch.object(runner, "load_graders", return_value=self.graders)
        patch.start()
        self.addCleanup(patch.stop)

    def materialize(self, task, fixtures_root, tasks_root, dest):
        Path(dest).mkdir(parents=True)
        return "base123"

    def grade(self, task, repo, base, view, tasks_root, work):
        return {"checks": [], "success": True, "correctness": 1.0, "test_pass_rate": 1.0, "regressions": 0, "constraints": []}

    def test_제한_시간을_넘기면_SIGINT_SIGTERM을_무시해도_SIGKILL로_끝내고_timed_out이다(self):
        """신호를 무시하는 프로세스도 유예 뒤 강제 종료되고 timed_out으로 기록된다."""
        # given
        env = {**os.environ, "FAKE_OUT": str(self.out), "FAKE_MODE": "stubborn"}

        # when
        result = process.run_agent([str(self.fake)], self.root, env, self.root / "s.jsonl", self.root / "e.txt", 1.0, 0.3, 0.3)

        # then
        self.assertTrue(result.timed_out)
        self.assertLess(result.wall_seconds, 10)
        self.assertLess(result.returncode, 0)

    def test_실행이_끝난_프로세스는_timed_out이_아니고_출력이_파일에_남는다(self):
        """정상 종료한 가짜 claude의 stdout이 stream.jsonl로 저장된다."""
        # given
        env = {**os.environ, "FAKE_OUT": str(self.out)}

        # when
        result = process.run_agent([str(self.fake)], self.root, env, self.root / "s.jsonl", self.root / "e.txt", 20.0, 0.3, 0.3)

        # then
        self.assertFalse(result.timed_out)
        self.assertEqual(len(transcript.read_jsonl(self.root / "s.jsonl")), 3)

    def test_시간_초과_실행은_timed_out으로_기록되고_채점과_메트릭까지_만들어진다(self):
        """가짜 claude를 설정으로 바꿔 끼운 실행이 timed_out 상태로 끝나고 metrics.json을 쓴다."""
        # given
        cfg = HarnessConfig(**{**self.cfg.__dict__, "extra_env": {"FAKE_OUT": str(self.out), "FAKE_MODE": "stubborn"}})

        # when
        run = runner.execute_run(self.spec, self.task, self.variant, self.plugin, cfg, {})

        # then
        self.assertEqual((run["status"], run["timed_out"]), ("timed_out", True))
        data = json.loads((self.spec.result_dir / "metrics.json").read_text(encoding="utf-8"))
        self.assertTrue(data["timed_out"])

    def test_정상_실행은_complete이고_자식_환경에는_ORCA_변수가_없다(self):
        """실행은 complete로 끝나고, 가짜 claude가 본 환경 변수 이름에 ORCA_*가 없으며 필수 플래그가 전달된다."""
        # given
        cfg = HarnessConfig(**{**self.cfg.__dict__, "tasks_root": self.cfg.tasks_root})

        # when
        run = runner.execute_run(self.spec, {**self.task, "limits": {"wall_seconds": 30, "max_budget_usd": 2}}, self.variant, self.plugin, cfg, {})

        # then
        seen = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(run["status"], "complete")
        self.assertEqual([name for name in seen["env"] if name.startswith("ORCA_")], [])
        self.assertIn("--max-budget-usd", seen["argv"])
        env_record = json.loads((self.spec.result_dir / "env.json").read_text(encoding="utf-8"))
        self.assertIn("ORCA_TERMINAL_HANDLE", env_record["removed_env_names"])
        self.assertTrue(json.loads((self.spec.result_dir / "metrics.json").read_text(encoding="utf-8"))["success"])

    def test_결과_메시지가_없이_끝난_실행은_infra_failed다(self):
        """result 메시지 없이 종료되면 상태는 infra_failed이고 채점하지 않는다."""
        # given
        facts = {"has_result": False}

        # when
        status = runner.decide_status(facts, None, False)

        # then
        self.assertEqual(status, "infra_failed")
        self.assertEqual(runner.decide_status(facts, "limit", True), "usage_limited")

    def test_작업_저장소를_만들지_못하면_infra_failed로_기록한다(self):
        """materialize_fixture가 실패하면 에이전트를 시작하지 않고 infra_failed 실행 기록을 쓴다."""
        # given
        def broken(*args):
            raise OSError("no fixture")

        self.graders.materialize_fixture = broken

        # when
        run = runner.execute_run(self.spec, self.task, self.variant, self.plugin, self.cfg, {})

        # then
        self.assertEqual(run["status"], "infra_failed")
        self.assertFalse((self.spec.result_dir / "stream.jsonl").exists())


class PluginExportTest(unittest.TestCase):
    def test_지정한_ref의_파일만_내보내고_같은_sha는_다시_쓰지_않는다(self):
        """git archive로 풀린 디렉터리와 plugin-export.json이 생기고 재호출은 같은 결과를 돌려준다."""
        # given
        with tempfile.TemporaryDirectory() as tmp:
            repo, run_root = Path(tmp) / "repo", Path(tmp) / "runs"
            repo.mkdir()
            git = ["git", "-c", "user.name=Demo Dev", "-c", "user.email=dev@example.com", "-c", "commit.gpgsign=false"]
            subprocess.run([*git, "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "a.txt").write_text("one", encoding="utf-8")
            subprocess.run([*git, "add", "."], cwd=repo, check=True)
            subprocess.run([*git, "commit", "-q", "-m", "init"], cwd=repo, check=True)
            (repo / "a.txt").write_text("two", encoding="utf-8")

            # when
            first = plugin_export.export_plugin(repo, run_root, "HEAD")
            second = plugin_export.export_plugin(repo, run_root, "HEAD")

            # then
            self.assertEqual((Path(first["path"]) / "a.txt").read_text(encoding="utf-8"), "one")
            self.assertEqual(first, second)
            self.assertTrue((Path(first["path"]).parent / "plugin-export.json").is_file())

    def test_내보낸_플러그인에는_평가_폴더가_없어서_숨은_테스트가_보이지_않는다(self):
        """에이전트가 플러그인 소스를 읽어도 evals 아래 숨은 테스트와 기준 해답을 볼 수 없다."""
        # given
        with tempfile.TemporaryDirectory() as tmp:
            repo, run_root = Path(tmp) / "repo", Path(tmp) / "runs"
            (repo / "evals/e2e/tasks/hidden").mkdir(parents=True)
            git = ["git", "-c", "user.name=Demo Dev", "-c", "user.email=dev@example.com", "-c", "commit.gpgsign=false"]
            subprocess.run([*git, "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "a.txt").write_text("one", encoding="utf-8")
            (repo / "evals/e2e/tasks/hidden/test_secret.py").write_text("x = 1\n", encoding="utf-8")
            subprocess.run([*git, "add", "."], cwd=repo, check=True)
            subprocess.run([*git, "commit", "-q", "-m", "init"], cwd=repo, check=True)

            # when
            exported = plugin_export.export_plugin(repo, run_root, "HEAD")

            # then
            self.assertTrue((Path(exported["path"]) / "a.txt").is_file())
            self.assertFalse((Path(exported["path"]) / "evals").exists())
            self.assertEqual(exported["excluded"], ["evals"])

    def test_없는_ref를_내보내려_하면_오류가_난다(self):
        """해석되지 않는 ref는 ExportError다."""
        # given
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", tmp], check=True)

            # when / then
            with self.assertRaises(plugin_export.ExportError):
                plugin_export.export_plugin(Path(tmp), Path(tmp) / "runs", "no-such-ref")


RUBRIC = {"artifact": {"kind": "final_answer"}, "scale": [1, 5], "pass_mean": 3.5,
          "criteria": [{"id": "a", "description": "Accuracy", "weight": 3}, {"id": "b", "description": "Clarity", "weight": 1}]}


def completed(code: int, stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr="")


class RubricTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.task = {"rubric": RUBRIC}
        self.commands: list[list[str]] = []

    def grade(self, runner_fn) -> dict[str, Any]:
        return rubric.grade(self.task, "The answer text.", "Explain the flow.", self.work, run=runner_fn)

    def test_검토자가_점수를_돌려주면_가중_평균으로_통과를_판정한다(self):
        """reviewer 종료 0이면 결과 파일의 점수로 가중 평균 (5*3+3*1)/4 = 4.5를 계산한다."""
        # given
        def fake(command, **kwargs):
            self.commands.append(command)
            Path(command[command.index("--result") + 1]).write_text('```json\n{"scores": {"a": 5, "b": 3}, "rationale": {"a": "ok"}}\n```', encoding="utf-8")
            return completed(0)

        # when
        result = self.grade(fake)

        # then
        self.assertEqual((result["mean"], result["passed"], result["fallback"]), (4.5, True, False))
        self.assertEqual(result["grader"], "gpt-6-astra")
        self.assertIn("--effort", self.commands[0])
        self.assertIn("reviewer", self.commands[0])

    def test_할당_파일에는_변형_이름이나_모델_이름이_없다(self):
        """블라인드 할당은 과제 프롬프트, 루브릭, 산출물만 담는다."""
        # given
        def fake(command, **kwargs):
            Path(command[command.index("--result") + 1]).write_text('{"scores": {"a": 1, "b": 1}}', encoding="utf-8")
            return completed(0)

        # when
        self.grade(fake)

        # then
        text = (self.work / "assignment.md").read_text(encoding="utf-8").lower()
        for hidden in ("baseline", "opus", "claude", "gpt", "variant"):
            self.assertNotIn(hidden, text)
        self.assertIn("the answer text.", text)

    def test_종료코드_3이나_4이면_Claude_대체_검토자로_채점하고_기록한다(self):
        """reviewer가 3으로 끝나면 claude -p 대체 경로를 쓰고 fallback true, 모델 이름을 남긴다."""
        # given
        def fake(command, **kwargs):
            self.commands.append(command)
            if command[0] == "claude":
                return completed(0, json.dumps({"result": '{"scores": {"a": 2, "b": 2}}'}))
            return completed(3)

        # when
        result = self.grade(fake)

        # then
        self.assertEqual((result["fallback"], result["grader"], result["passed"]), (True, "claude-opus-5-5", False))
        self.assertIn("--strict-mcp-config", self.commands[1])

    def test_채점_폴더는_git_저장소가_되고_러너_상태_줄을_결과에_남긴다(self):
        """Codex는 git 저장소 밖에서 실행을 거부하므로 채점 폴더를 git 저장소로 만들고, 실패 원인을 기록한다."""
        # given
        status = {"role": "reviewer", "verified": False, "evidence": {"error": "codex exited with 1"}, "exit": 3}

        def fake(command, **kwargs):
            if command[0] == "claude":
                return completed(0, json.dumps({"result": '{"scores": {"a": 4, "b": 4}}'}))
            return completed(3, "role_runner: codex exited with 1\n" + json.dumps(status))

        # when
        result = self.grade(fake)

        # then
        self.assertTrue((self.work / ".git").is_dir())
        self.assertEqual(result["runner_status"], status)

    def test_점수가_빠졌거나_범위를_벗어나면_오류로_기록하고_통과시키지_않는다(self):
        """기준 하나가 빠진 응답은 error를 가진 불통과 결과다."""
        # given
        def fake(command, **kwargs):
            Path(command[command.index("--result") + 1]).write_text('{"scores": {"a": 9}}', encoding="utf-8")
            return completed(0)

        # when
        result = self.grade(fake)

        # then
        self.assertFalse(result["passed"])
        self.assertIn("error", result)

    def test_산출물이_비어_있으면_검토자를_부르지_않고_최저점을_준다(self):
        """빈 산출물은 모델 호출 없이 모든 기준 1점이다."""
        # given
        def fake(command, **kwargs):
            raise AssertionError("must not run")

        # when
        result = rubric.grade(self.task, "  ", "p", self.work, run=fake)

        # then
        self.assertEqual((result["scores"], result["passed"], result["empty_artifact"]), ({"a": 1, "b": 1}, False, True))


def metrics_row(task: str, variant: str, rep: int, success: bool, cost: float, wall: float, status: str = "complete") -> dict[str, Any]:
    return {"run_id": f"{task}-{variant}-r{rep}", "task": task, "variant": variant, "rep": rep, "status": status,
            "success": success, "correctness": 1.0 if success else 0.5, "test_pass_rate": 1.0, "wall_seconds": wall,
            "num_turns": 5, "cost": {"claude_total_cost_usd": cost, "codex_list_cost_usd_estimate": 0.0},
            "tool_calls_by_tool": {"total": {"Bash": 4}}, "subagent_launches_by_type": {}, "role_runner_calls": {},
            "approval_prompts": 1, "retries": {"total": 0}, "handoff": {"missing": 0}}


def write_rows(root: Path, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        spec = matrix.make_spec(root, "camp", row["task"], row["variant"], row["rep"])
        matrix.write_json(spec.result_dir / "run.json", {k: row[k] for k in ("run_id", "task", "variant", "rep", "status")})
        if row["status"] in ("complete", "timed_out"):
            matrix.write_json(spec.result_dir / "metrics.json", row)


class SummarizeTest(unittest.TestCase):
    def test_백분위수는_최근접_순위법으로_계산한다(self):
        """n=4의 p50은 2번째, n=10의 p95는 10번째 값이다."""
        # given
        small, ten = [4.0, 1.0, 3.0, 2.0], [float(i) for i in range(1, 11)]

        # when
        values = (summarize.nearest_rank(small, 50), summarize.nearest_rank(ten, 95), summarize.nearest_rank(ten, 50), summarize.nearest_rank([], 50))

        # then
        self.assertEqual(values, (2.0, 10.0, 5.0, None))

    def test_변형_비교는_짝지은_반복의_성공_뒤집힘과_다수결_뒤집힘을_센다(self):
        """A만 통과한 반복과 B만 통과한 반복을 세고, 과제 다수결이 달라지면 flip 표시를 한다."""
        # given
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a_pass = [True, True, False]
            b_pass = [False, False, True]
            rows = [metrics_row("T01", "A", k + 1, a_pass[k], 1.0 + k, 100.0) for k in range(3)]
            rows += [metrics_row("T01", "B", k + 1, b_pass[k], 2.0 + k, 150.0) for k in range(3)]
            write_rows(root, rows)

            # when
            text = summarize.summarize(root, "camp", ("A", "B"))

            # then
            self.assertIn("| T01 | 3 | 2 | 1 | yes | +1.000 | +50 | +0 | +0 |", text)

    def test_요약은_상태별_개수를_세고_완료되지_않은_실행은_통계에서_뺀다(self):
        """usage_limited 실행은 개수에만 들어가고 과제 표의 n에는 들어가지 않는다."""
        # given
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_rows(root, [metrics_row("T01", "A", 1, True, 1.0, 10.0), metrics_row("T01", "A", 2, False, 1.0, 10.0, "usage_limited")])

            # when
            text = summarize.summarize(root, "camp")

            # then
            self.assertIn("complete=1, timed_out=0, infra_failed=0, usage_limited=1", text)
            self.assertIn("| T01 | 1 | 1/1 |", text)

    def test_비용_백분위수_옆에는_표본_수를_함께_적는다(self):
        """비용 칸은 p50 / p95와 (n=표본수) 형식이다."""
        # given
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_rows(root, [metrics_row("T01", "A", k, True, float(k), 10.0 * k) for k in range(1, 5)])

            # when
            text = summarize.summarize(root, "camp")

            # then
            self.assertIn("2.000 / 4.000 (n=4)", text)


class CollectTest(unittest.TestCase):
    def test_메인_기록과_서브에이전트_기록을_세션_ID로_찾아_복사한다(self):
        """projects/*/<세션>.jsonl과 같은 이름 폴더의 subagents가 결과 폴더로 복사된다."""
        # given
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "claude"
            project = config / "projects" / "-tmp-demo"
            (project / "sess-1" / "subagents").mkdir(parents=True)
            (project / "sess-1.jsonl").write_text('{"type": "user"}\n', encoding="utf-8")
            (project / "sess-1" / "subagents" / "agent-a1.jsonl").write_text('{"type": "assistant"}\n', encoding="utf-8")
            (project / "sess-1" / "subagents" / "agent-a1.meta.json").write_text('{"agentType": "demo:scout"}', encoding="utf-8")
            destination = Path(tmp) / "out"

            # when
            found = collect.collect_claude(config, "sess-1", destination)

            # then
            self.assertEqual(found["main"], "main.jsonl")
            records = collect.load_subagents(destination / "subagents")
            self.assertEqual([r["meta"]["agentType"] for r in records], ["demo:scout"])

    def test_작업_폴더와_시간_창에_맞는_Codex_롤아웃만_고른다(self):
        """cwd가 작업 폴더 안이고 시작 시각이 실행 창 안인 롤아웃만 복사 대상이다."""
        # given
        from datetime import datetime, timezone
        start = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
        end = datetime(2026, 10, 25, 12, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            home, work = Path(tmp) / "codex", Path(tmp) / "work"
            day = home / "sessions" / "2026" / "10" / "25"
            day.mkdir(parents=True)
            cases = {"rollout-in.jsonl": (str(work / "repo"), "2026-10-25T12:10:00Z"),
                     "rollout-other-cwd.jsonl": ("/tmp/elsewhere", "2026-10-25T12:10:00Z"),
                     "rollout-late.jsonl": (str(work / "repo"), "2026-10-25T14:10:00Z")}
            for name, (cwd, stamp) in cases.items():
                (day / name).write_text(json.dumps({"type": "session_meta", "payload": {"cwd": cwd, "timestamp": stamp}}) + "\n", encoding="utf-8")

            # when
            matches = collect.find_rollouts(home, work, start, end)

            # then
            self.assertEqual([m.name for m in matches], ["rollout-in.jsonl"])


if __name__ == "__main__":
    unittest.main()
