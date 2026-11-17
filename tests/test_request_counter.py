"""Tests of the counter that replays session records into delegated runs and retries per user request."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("count_requests", REPO_ROOT / "evals" / "request-budget" / "count_requests.py")
counter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(counter)

START = datetime(2026, 10, 18, tzinfo=timezone.utc)
END = datetime(2026, 11, 17, tzinfo=timezone.utc)
INSIDE = "2026-11-01T10:00:00.000Z"
BEFORE = "2026-09-01T10:00:00.000Z"
PLUGIN_SCOUT = "hei5enbug-agent-setup:scout"
RUNNER = "python3 /plugin/scripts/role_runner.py"


def status_line(role: str, code: int) -> str:
    return json.dumps({"role": role, "runner": "codex", "verified": code == 0, "exit": code})


def claude_prompt(text: str, when: str = INSIDE) -> dict:
    return {"type": "user", "timestamp": when, "cwd": "/home/test/work", "message": {"role": "user", "content": text}}


def claude_call(call_id: str, name: str, tool_input: dict) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": call_id, "name": name, "input": tool_input}]}}


def claude_result(call_id: str, text: str, is_error: bool = False) -> dict:
    block = {"type": "tool_result", "tool_use_id": call_id, "content": text, "is_error": is_error}
    return {"type": "user", "message": {"role": "user", "content": [block]}}


def codex_meta(source: str = "cli", thread: str = "user") -> dict:
    return {"type": "session_meta", "payload": {"source": source, "thread_source": thread, "cwd": "/home/test/work"}}


def codex_prompt(when: str = INSIDE) -> dict:
    return {"type": "event_msg", "timestamp": when, "payload": {"type": "item_completed", "item": {"type": "UserMessage"}}}


def codex_spawn(call_id: str, agent: str) -> dict:
    arguments = json.dumps({"agent_type": agent, "message": "task"})
    return {"type": "response_item", "payload": {"type": "function_call", "name": "spawn_agent", "call_id": call_id, "arguments": arguments}}


def codex_output(call_id: str, text: str) -> dict:
    return {"type": "response_item", "payload": {"type": "function_call_output", "call_id": call_id, "output": text}}


class ClaudeRecordTest(unittest.TestCase):
    def count(self, *events: dict) -> list[tuple[int, int]]:
        return counter.claude_session(events, START, END)

    def test_요청은_다음_사용자_프롬프트에서_끝나고_에이전트와_실행기_쌍을_세고_오류_뒤_같은_종류_시작을_재시도로_센다(self):
        """첫 요청은 실행 4와 재시도 1, 둘째 요청은 0과 0, 셋째 요청은 실행기가 실패한 worker를 다시 시작해 실행 2와 재시도 1이다."""
        # Given
        events = [
            claude_prompt("first"),
            claude_call("a1", "Agent", {"subagent_type": PLUGIN_SCOUT}), claude_result("a1", "boom", is_error=True),
            claude_call("a2", "Agent", {"subagent_type": PLUGIN_SCOUT}), claude_result("a2", "ok"),
            claude_call("b1", "Bash", {"command": f"{RUNNER} scout --assignment a --result x --assignment b --result y"}),
            claude_result("b1", status_line("scout", 0) + "\n" + status_line("scout", 0)),
            claude_prompt("second"),
            claude_prompt("third"),
            claude_call("w1", "Bash", {"command": f"{RUNNER} worker --assignment a --result x"}),
            claude_result("w1", status_line("worker", 3), is_error=True),
            claude_call("w2", "Bash", {"command": f"{RUNNER} worker --assignment a --result x"}),
            claude_result("w2", status_line("worker", 0)),
        ]

        # When
        requests = self.count(*events)

        # Then
        self.assertEqual(requests, [(4, 1), (0, 0), (2, 1)])

    def test_도구_결과_사용자_줄과_메타_줄과_사이드체인_줄은_프롬프트가_아니다(self):
        """tool_result만 든 사용자 줄, isMeta 줄, 시스템 태그로 시작한 줄은 요청을 나누지 않는다."""
        # Given
        events = [
            claude_prompt("only"),
            claude_call("a1", "Agent", {"subagent_type": PLUGIN_SCOUT}), claude_result("a1", "ok"),
            {**claude_prompt("meta"), "isMeta": True},
            claude_prompt("<system-reminder>reminder</system-reminder>"),
            {**claude_prompt("nested"), "isSidechain": True},
        ]

        # When
        requests = self.count(*events)

        # Then
        self.assertEqual(requests, [(1, 0)])

    def test_숨겨진_내장_에이전트_시작은_위임_실행으로_세지_않는다(self):
        """general-purpose와 Explore 시작은 횟수에 들지 않는다."""
        # Given
        events = [claude_prompt("p"), claude_call("a", "Agent", {"subagent_type": "general-purpose"}), claude_call("b", "Agent", {"subagent_type": "Explore"})]

        # When
        requests = self.count(*events)

        # Then
        self.assertEqual(requests, [(0, 0)])

    def test_집계_기간_밖의_프롬프트와_실행기_자식_세션과_임시_폴더_세션은_세지_않는다(self):
        """기간 전의 요청, 할당 문장으로 시작한 자식 세션, /tmp 작업 폴더의 세션은 빈 결과이다."""
        # Given
        outside = [claude_prompt("old", BEFORE), claude_call("a", "Agent", {"subagent_type": PLUGIN_SCOUT})]
        child = [claude_prompt('You are an assigned reviewer under the "Assigned workers" rules: start no agents'), claude_call("a", "Agent", {"subagent_type": PLUGIN_SCOUT})]
        temporary = [{**claude_prompt("eval"), "cwd": "/private/tmp/eval-run/work"}]

        # When
        counts = [self.count(*session) for session in (outside, child, temporary)]

        # Then
        self.assertEqual(counts, [[], [], []])


class CodexRecordTest(unittest.TestCase):
    def count(self, *events: dict) -> list[tuple[int, int]]:
        return counter.codex_session(events, START, END)

    def test_spawn_agent_확인에_작업_이름이_없으면_실패로_보고_같은_종류의_다음_시작을_재시도로_센다(self):
        """첫 scout 시작이 오류로 끝나면 둘째 scout 시작은 재시도이고 요청은 실행 2와 재시도 1이다."""
        # Given
        events = [
            codex_meta(), codex_prompt(),
            codex_spawn("c1", "scout"), codex_output("c1", "error: no slot"),
            codex_spawn("c2", "scout"), codex_output("c2", json.dumps({"task_name": "scan"})),
            codex_prompt(),
        ]

        # When
        requests = self.count(*events)

        # Then
        self.assertEqual(requests, [(2, 1), (0, 0)])

    def test_exec_와_서브에이전트_세션은_사용자_요청이_아니므로_세지_않는다(self):
        """실행기가 시작한 exec 세션과 스레드 분기 세션은 빈 결과이다."""
        # Given
        exec_session = [codex_meta("exec", "user"), codex_prompt(), codex_spawn("c1", "scout")]
        subagent = [codex_meta("cli", "subagent"), codex_prompt(), codex_spawn("c1", "scout")]

        # When
        counts = [self.count(*session) for session in (exec_session, subagent)]

        # Then
        self.assertEqual(counts, [[], []])

    def test_Codex_셸_호출의_실행기_명령도_쌍마다_하나씩_센다(self):
        """같은 명령에 --assignment가 둘이면 실행 둘이고, 상태 줄의 비정상 종료 뒤 같은 역할의 첫 시작만 재시도이다."""
        # Given
        call = {"type": "response_item", "payload": {
            "type": "custom_tool_call", "name": "exec", "call_id": "x1",
            "input": f"{RUNNER} reviewer --assignment a --result r --assignment b --result s",
        }}
        events = [codex_meta(), codex_prompt(), call, codex_output("x1", status_line("reviewer", 3)),
                  {**call, "payload": {**call["payload"], "call_id": "x2"}}]

        # When
        requests = self.count(*events)

        # Then
        self.assertEqual(requests, [(4, 1)])


class DistributionTest(unittest.TestCase):
    def test_분포는_횟수별_요청_수와_가장_큰_횟수만_담고_세션_내용은_담지_않는다(self):
        """요청 (0,0) (2,0) (2,1)은 횟수별 요청 수, 가장 큰 횟수, 위임 실행이 있던 요청 수로 요약된다."""
        # Given
        requests = [(0, 0), (2, 0), (2, 1)]

        # When
        record = counter.distribution(requests, START, END)

        # Then
        self.assertEqual(record["runs_per_request"], {"0": 1, "2": 2})
        self.assertEqual(record["retries_per_request"], {"0": 2, "1": 1})
        self.assertEqual((record["largest_runs"], record["largest_retries"], record["requests_with_a_delegated_run"]), (2, 1, 2))
        self.assertEqual(set(record), {"window", "requests", "requests_with_a_delegated_run", "runs_per_request",
                                       "retries_per_request", "largest_runs", "largest_retries"})

    def test_명령줄은_기간의_파일만_읽어_분포_파일과_같은_틀의_기록을_쓴다(self):
        """작은 Claude 세션 파일 하나를 읽어 쓴 기록에 요청 1과 실행 1이 있다."""
        # Given
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "claude" / "project"
            project.mkdir(parents=True)
            lines = [claude_prompt("go"), claude_call("a1", "Agent", {"subagent_type": PLUGIN_SCOUT}), claude_result("a1", "ok")]
            (project / "s1.jsonl").write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
            (root / "codex").mkdir()
            out = root / "out.json"

            # When
            counter.main(["--end", "2026-11-17", "--claude-root", str(root / "claude"), "--codex-root", str(root / "codex"),
                          "--out", str(out)])
            record = json.loads(out.read_text(encoding="utf-8"))

        # Then
        self.assertEqual((record["requests"], record["largest_runs"], record["run_cap"], record["retry_cap"]), (1, 1, 10, 1))


if __name__ == "__main__":
    unittest.main()
