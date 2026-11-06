#!/usr/bin/env python3
"""세션 개요 스크립트가 Orca 읽기 결과를 올바르게 합치고, 실패와 부분 실패를 구분해 보고하는지 검사한다."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "session_overview.py"
SPEC = importlib.util.spec_from_file_location("session_overview_under_test", SCRIPT)
overview = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(overview)

MIB = 1024 * 1024
NOW_MS = 1_800_000_000_000
PANE_A = "tab-a:leaf-a"
PANE_B = "tab-b:leaf-b"
PANE_C = "tab-c:leaf-c"
HANDLE_A = "term_demo_a"
HANDLE_B = "term_demo_b"


def agent(pane: str, **fields) -> dict:
    row = {
        "paneKey": pane,
        "agentType": "claude",
        "state": "working",
        "stateStartedAt": NOW_MS - 5 * 60_000,
        "lastAssistantMessage": "done",
        "prompt": "fix the demo",
        "interrupted": False,
        "agentWait": None,
        "conversationName": "demo chat",
    }
    row.update(fields)
    return row


def worktree(name: str, agents: list[dict], **fields) -> dict:
    row = {
        "worktreeId": f"repo-1::/tmp/work/{name}",
        "repo": "demo-repo",
        "path": f"/tmp/work/{name}",
        "branch": f"refs/heads/feature/{name}",
        "displayName": name,
        "workspaceStatus": "in-progress",
        "comment": "",
        "unread": False,
        "isMainWorktree": False,
        "parentWorktreeId": None,
        "childWorktreeIds": [],
        "liveTerminalCount": len(agents),
        "agents": agents,
    }
    row.update(fields)
    return row


def terminal(handle: str, pane: str, worktree_id: str = "repo-1::/tmp/work/a") -> dict:
    tab, leaf = pane.split(":")
    return {"handle": handle, "tabId": tab, "leafId": leaf, "worktreeId": worktree_id}


def memory(host: dict | None, sessions: dict[str, int]) -> dict:
    return {
        "host": host or {"totalMemory": 16 * 1024 * MIB, "availableMemory": 3 * 1024 * MIB},
        "worktrees": [
            {"sessions": [{"paneKey": pane, "pid": 100 + index, "memory": used} for index, (pane, used) in enumerate(sessions.items())]}
        ],
    }


def ok(result: dict) -> tuple[int, str, str]:
    return 0, json.dumps({"ok": True, "result": result}), ""


class FakeOrca:
    """Answers each Orca read from a fixture keyed by its first two arguments and records every call."""

    def __init__(self, ps=None, terminals=None, mem=None, failures=None) -> None:
        self.answers = {
            ("worktree", "ps"): ok({"worktrees": ps if ps is not None else [], "truncated": False}),
            ("terminal", "list"): ok({"terminals": terminals if terminals is not None else []}),
            ("diagnostics", "memory"): ok(mem if mem is not None else memory(None, {})),
        }
        self.answers.update(failures or {})
        self.calls: list[list[str]] = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        return self.answers[(argv[1], argv[2])]


def run(fake: FakeOrca, env: dict | None = None) -> tuple[int, dict | None, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = overview.main([], runner=fake, now_ms=NOW_MS, env=env or {})
    return code, (json.loads(out.getvalue()) if out.getvalue() else None), err.getvalue()


def standard_fake(**fields) -> FakeOrca:
    wt_a = worktree("a", [agent(PANE_A)])
    wt_b = worktree("b", [agent(PANE_B, state="done")])
    return FakeOrca(
        ps=[wt_a, wt_b],
        terminals=[terminal(HANDLE_A, PANE_A), terminal(HANDLE_B, PANE_B)],
        mem=memory(None, {PANE_A: 600 * MIB, PANE_B: 1200 * MIB}),
        **fields,
    )


class JoinCase(unittest.TestCase):
    def test_paneKey로_터미널_핸들과_메모리를_각_세션에_붙인다(self) -> None:
        """다른 세션의 핸들이나 메모리가 섞이면 엉뚱한 터미널에 입력을 보내므로 paneKey 짝을 정확히 따른다."""
        # given
        fake = standard_fake()
        # when
        code, data, _ = run(fake)
        # then
        by_name = {row["display_name"]: row for row in data["sessions"]}
        self.assertEqual(0, code)
        self.assertEqual((HANDLE_A, 600), (by_name["a"]["terminal_handle"], by_name["a"]["memory_mb"]))
        self.assertEqual((HANDLE_B, 1200), (by_name["b"]["terminal_handle"], by_name["b"]["memory_mb"]))

    def test_호스트_메모리를_MB로_보고한다(self) -> None:
        """호스트 전체와 가용 메모리 단위가 바이트로 남으면 저메모리 판단이 틀어진다."""
        # given
        fake = standard_fake()
        # when
        _, data, _ = run(fake)
        # then
        self.assertEqual((16384, 3072), (data["host_total_mb"], data["host_available_mb"]))

    def test_브랜치의_refs_heads_접두사를_떼고_자식_수를_센다(self) -> None:
        """브랜치 표기와 자식 워크트리 수가 틀리면 정리 가능 여부를 잘못 판단한다."""
        # given
        parent = worktree("p", [agent(PANE_A)], childWorktreeIds=["c1", "c2"])
        fake = FakeOrca(ps=[parent], terminals=[terminal(HANDLE_A, PANE_A)], mem=memory(None, {PANE_A: MIB}))
        # when
        _, data, _ = run(fake)
        # then
        row = data["sessions"][0]
        self.assertEqual(("feature/p", 2), (row["branch"], row["child_count"]))

    def test_에이전트가_없고_터미널만_있는_워크트리를_따로_나열한다(self) -> None:
        """에이전트 없이 터미널만 붙들고 있는 워크트리가 개요에서 빠지면 사용자가 그 메모리를 놓친다."""
        # given
        idle = worktree("shell-only", [], liveTerminalCount=1)
        empty = worktree("nothing", [], liveTerminalCount=0)
        fake = FakeOrca(ps=[idle, empty], terminals=[terminal("term_shell", "tab-s:leaf-s", idle["worktreeId"])])
        # when
        _, data, _ = run(fake)
        # then
        self.assertEqual([], data["sessions"])
        self.assertEqual([("shell-only", ["term_shell"])], [(w["display_name"], w["terminal_handles"]) for w in data["worktrees_without_agent"]])


class FieldCase(unittest.TestCase):
    def test_상태_지속_시간을_분_단위로_내림해_보고한다(self) -> None:
        """분 계산이 올림이거나 초 단위면 오래 기다린 세션 판단 기준이 어긋난다."""
        # given
        started = NOW_MS - (7 * 60_000 + 30_000)
        fake = FakeOrca(ps=[worktree("a", [agent(PANE_A, stateStartedAt=started)])], terminals=[terminal(HANDLE_A, PANE_A)])
        # when
        _, data, _ = run(fake)
        # then
        self.assertEqual(7, data["sessions"][0]["minutes_in_state"])

    def test_시작_시각을_모르거나_미래이면_분은_null_또는_0이다(self) -> None:
        """시계 오차나 누락된 시각이 음수 분이나 예외로 번지지 않는다."""
        # given
        future = agent(PANE_A, stateStartedAt=NOW_MS + 60_000)
        missing = agent(PANE_B, stateStartedAt=None)
        fake = FakeOrca(ps=[worktree("a", [future]), worktree("b", [missing])])
        # when
        _, data, _ = run(fake)
        # then
        self.assertEqual([0, None], [row["minutes_in_state"] for row in data["sessions"]])

    def test_긴_마지막_메시지는_끝부분을_남기고_프롬프트는_앞부분을_남긴다(self) -> None:
        """질문은 메시지 끝에 있으므로 끝을 잘라내면 사용자 대기 세션을 분류하지 못한다."""
        # given
        message = "앞" * 1000 + " 마지막 질문: 배포할까요?"
        prompt = "처음 요청 " + "뒤" * 500
        fake = FakeOrca(ps=[worktree("a", [agent(PANE_A, lastAssistantMessage=message, prompt=prompt)])])
        # when
        _, data, _ = run(fake)
        # then
        row = data["sessions"][0]
        self.assertTrue(row["last_assistant_message"].endswith("마지막 질문: 배포할까요?"))
        self.assertLessEqual(len(row["last_assistant_message"]), 400)
        self.assertTrue(row["prompt"].startswith("처음 요청"))
        self.assertLessEqual(len(row["prompt"]), 160)

    def test_짧은_메시지는_공백만_정리하고_그대로_둔다(self) -> None:
        """짧은 메시지를 잘라내거나 줄바꿈을 그대로 두면 표가 깨진다."""
        # given
        fake = FakeOrca(ps=[worktree("a", [agent(PANE_A, lastAssistantMessage="첫 줄\n\n  둘째 줄")])])
        # when
        _, data, _ = run(fake)
        # then
        self.assertEqual("첫 줄 둘째 줄", data["sessions"][0]["last_assistant_message"])

    def test_ORCA_TERMINAL_HANDLE과_같은_세션만_현재_세션으로_표시한다(self) -> None:
        """현재 세션을 못 알아보면 자기 자신에게 입력을 보내거나 종료할 수 있다."""
        # given
        fake = standard_fake()
        # when
        _, data, _ = run(fake, env={"ORCA_TERMINAL_HANDLE": HANDLE_B})
        # then
        self.assertEqual({"a": False, "b": True}, {row["display_name"]: row["is_current"] for row in data["sessions"]})

    def test_현재_핸들_환경변수가_없으면_어떤_세션도_현재로_표시하지_않는다(self) -> None:
        """핸들이 없는 세션이 빈 값끼리 맞아 현재 세션으로 잘못 표시되지 않는다."""
        # given
        fake = FakeOrca(ps=[worktree("a", [agent(PANE_A)])])
        # when
        _, data, _ = run(fake)
        # then
        self.assertEqual([False], [row["is_current"] for row in data["sessions"]])


class PartialJoinCase(unittest.TestCase):
    def test_메모리가_맞지_않는_세션은_null과_경고를_낸다(self) -> None:
        """메모리를 못 찾은 세션에 0을 적으면 가벼운 세션으로 오인한다."""
        # given
        fake = FakeOrca(
            ps=[worktree("a", [agent(PANE_A)]), worktree("b", [agent(PANE_B)])],
            terminals=[terminal(HANDLE_A, PANE_A), terminal(HANDLE_B, PANE_B)],
            mem=memory(None, {PANE_A: 300 * MIB}),
        )
        # when
        code, data, _ = run(fake)
        # then
        by_name = {row["display_name"]: row for row in data["sessions"]}
        self.assertEqual(0, code)
        self.assertEqual((300, None), (by_name["a"]["memory_mb"], by_name["b"]["memory_mb"]))
        self.assertEqual(1, len([w for w in data["warnings"] if PANE_B in w and "memory" in w]))

    def test_터미널이_맞지_않는_세션은_핸들_null과_경고를_낸다(self) -> None:
        """핸들이 없는 세션에 동작을 시도하지 않도록 null로 드러낸다."""
        # given
        fake = FakeOrca(ps=[worktree("a", [agent(PANE_A)])], terminals=[], mem=memory(None, {PANE_A: MIB}))
        # when
        _, data, _ = run(fake)
        # then
        self.assertIsNone(data["sessions"][0]["terminal_handle"])
        self.assertTrue(any(PANE_A in w and "terminal" in w for w in data["warnings"]))

    def test_메모리_읽기가_실패해도_종료_코드_0으로_경고만_남긴다(self) -> None:
        """무거운 메모리 조회 하나가 실패했다고 대기 중 세션 목록까지 잃지 않는다."""
        # given
        fake = standard_fake(failures={("diagnostics", "memory"): (1, "", "sweep failed\n")})
        # when
        code, data, _ = run(fake)
        # then
        self.assertEqual(0, code)
        self.assertEqual([None, None], [row["memory_mb"] for row in data["sessions"]])
        self.assertIsNone(data["host_available_mb"])
        self.assertEqual(1, len([w for w in data["warnings"] if w.startswith("memory is unknown")]))

    def test_잘린_세션_목록은_경고로_알린다(self) -> None:
        """Orca가 목록을 잘랐는데 알리지 않으면 빠진 세션을 없는 것으로 믿는다."""
        # given
        fake = FakeOrca()
        fake.answers[("worktree", "ps")] = ok({"worktrees": [], "truncated": True})
        # when
        _, data, _ = run(fake)
        # then
        self.assertTrue(any("truncated" in w for w in data["warnings"]))


class FailureCase(unittest.TestCase):
    def test_세션_목록_읽기가_실패하면_종료_코드_2와_한_줄_사유를_낸다(self) -> None:
        """Orca에 닿지 못했는데 빈 개요를 성공으로 내면 정리할 세션이 없다고 오해한다."""
        # given
        fake = standard_fake(failures={("worktree", "ps"): (1, "", "runtime not reachable\n")})
        # when
        code, data, err = run(fake)
        # then
        self.assertEqual(2, code)
        self.assertIsNone(data)
        self.assertEqual(1, len(err.strip().splitlines()))
        self.assertIn("runtime not reachable", err)

    def test_터미널_목록_읽기가_실패하면_종료_코드_2다(self) -> None:
        """핸들 없이 표를 만들면 승인된 동작을 보낼 곳이 없다."""
        # given
        fake = standard_fake(failures={("terminal", "list"): (1, "", "boom\n")})
        # when
        code, data, _ = run(fake)
        # then
        self.assertEqual((2, None), (code, data))

    def test_읽을_수_없는_JSON과_거절된_응답은_종료_코드_2다(self) -> None:
        """깨진 응답을 빈 결과로 삼키면 실패가 정상처럼 보인다."""
        # given
        garbled = standard_fake(failures={("worktree", "ps"): (0, "not json", "")})
        rejected = standard_fake(failures={("worktree", "ps"): (0, json.dumps({"ok": False}), "")})
        # when
        codes = [run(garbled)[0], run(rejected)[0]]
        # then
        self.assertEqual([2, 2], codes)

    def test_인자를_받지_않는다(self) -> None:
        """모르는 인자를 조용히 무시하면 쓰기 옵션을 붙여도 모르고 지나간다."""
        # given
        err = io.StringIO()
        # when
        with contextlib.redirect_stderr(err):
            code = overview.main(["--apply"], runner=standard_fake(), now_ms=NOW_MS, env={})
        # then
        self.assertEqual(2, code)


class ReadOnlyCase(unittest.TestCase):
    def test_정해진_세_읽기_명령을_한_번씩만_실행한다(self) -> None:
        """메모리 조회는 프로세스를 훑으므로 반복하면 느려지고, 읽기 외 명령이 섞이면 읽기 전용 약속이 깨진다."""
        # given
        fake = standard_fake()
        # when
        run(fake)
        # then
        self.assertEqual(
            [["orca", "worktree", "ps", "--agent-wait", "--json"], ["orca", "terminal", "list", "--json"], ["orca", "diagnostics", "memory", "--json"]],
            fake.calls,
        )

    def test_ORCA_CLI_COMMAND가_있으면_그_실행_파일로_읽는다(self) -> None:
        """설정된 Orca 실행 파일을 무시하면 개발용 Orca가 아닌 다른 런타임을 읽는다."""
        # given
        fake = standard_fake()
        # when
        run(fake, env={"ORCA_CLI_COMMAND": "/tmp/work/orca-dev"})
        # then
        self.assertEqual({"/tmp/work/orca-dev"}, {call[0] for call in fake.calls})


class ProcessCase(unittest.TestCase):
    def test_실제_하위_프로세스로_실행한_가짜_orca의_결과를_합친다(self) -> None:
        """러너 주입 없이 명령줄 경로를 타도 종료 코드 0과 JSON 출력이 유지된다."""
        # given
        with tempfile.TemporaryDirectory() as folder:
            fixture = Path(folder) / "answers.json"
            fixture.write_text(
                json.dumps(
                    {
                        "ps": {"ok": True, "result": {"worktrees": [worktree("a", [agent(PANE_A)])]}},
                        "list": {"ok": True, "result": {"terminals": [terminal(HANDLE_A, PANE_A)]}},
                        "memory": {"ok": True, "result": memory(None, {PANE_A: 50 * MIB})},
                    }
                ),
                encoding="utf-8",
            )
            fake = Path(folder) / "fake-orca"
            fake.write_text(
                "#!/usr/bin/env python3\nimport json, sys\n"
                f"answers = json.load(open({str(fixture)!r}))\n"
                "key = {'ps': 'ps', 'list': 'list', 'memory': 'memory'}[sys.argv[2]]\n"
                "print(json.dumps(answers[key]))\n",
                encoding="utf-8",
            )
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            env = {**os.environ, "ORCA_CLI_COMMAND": str(fake)}
            # when
            done = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, env=env, check=False)
        # then
        self.assertEqual(0, done.returncode, done.stderr)
        rows = json.loads(done.stdout)["sessions"]
        self.assertEqual([(HANDLE_A, 50)], [(row["terminal_handle"], row["memory_mb"]) for row in rows])

    def test_Orca_실행_파일이_없으면_종료_코드_2와_한_줄_사유를_낸다(self) -> None:
        """Orca가 설치되지 않은 환경에서 트레이스백 대신 읽을 수 있는 사유로 끝난다."""
        # given
        env = {**os.environ, "ORCA_CLI_COMMAND": "/tmp/work/no-such-orca"}
        # when
        done = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, env=env, check=False)
        # then
        self.assertEqual(2, done.returncode)
        self.assertEqual("", done.stdout)
        self.assertEqual(1, len(done.stderr.strip().splitlines()))


if __name__ == "__main__":
    unittest.main()
