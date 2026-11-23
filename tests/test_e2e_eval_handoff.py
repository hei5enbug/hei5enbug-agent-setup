"""Unit tests for T31 to T34: the fake Orca's terminals and messages, the seeded state, and each task's graders."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_ROOT = REPO_ROOT / "evals/e2e"
TASKS_ROOT = E2E_ROOT / "tasks"
FIXTURES_ROOT = E2E_ROOT / "fixtures"
sys.path.insert(0, str(E2E_ROOT))
sys.path.insert(0, str(TASKS_ROOT / "reference"))

from harness import graders  # noqa: E402
from handoff_tools import orca as run_orca  # noqa: E402

OWN, SENDER = "term_demo_a", "term_sender"
TASK_IDS = ("T31", "T32", "T33", "T34")
REPORT = "page_size is 20"
BRIEF = "Read README.md. This terminal belongs to the handoff; close it after your report. Report to term_demo_a."


def make_view(answer: str = "", commands: tuple[str, ...] = ()) -> dict[str, Any]:
    calls = [{"name": "Bash", "input": {"command": command}, "result_text": ""} for command in commands]
    return {"final_answer": answer, "assistant_texts": [], "tool_calls": calls, "delegations": [], "approvals": [],
            "permission_denials": []}


def load_shared(origin: Path) -> Any:
    path = TASKS_ROOT / "custom" / "handoff_shared.py"
    module = types.ModuleType("handoff_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
    return module, types.SimpleNamespace(origin=origin)


class HandoffCase(unittest.TestCase):
    task_id = "T31"

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.task = json.loads((TASKS_ROOT / f"{self.task_id}.json").read_text(encoding="utf-8"))
        self.repo = self.root / "work" / "repo"
        self.work = self.repo.parent
        self.base = graders.materialize_fixture(self.task, FIXTURES_ROOT, TASKS_ROOT, self.repo)

    def orca(self, *arguments: str, handle: str = OWN, cwd: Path | None = None) -> dict:
        return run_orca(self.repo, *arguments, handle=handle, cwd=cwd)

    def refused(self, *arguments: str, handle: str = OWN) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "FAKE_ORCA_STATE": str(self.work / "orca-state" / "state.json"),
               "ORCA_TERMINAL_HANDLE": handle}
        return subprocess.run([str(self.work / "fake-bin" / "orca"), *arguments, "--json"], cwd=self.repo, env=env,
                              capture_output=True, text=True, check=False)

    def state(self) -> dict[str, Any]:
        return json.loads((self.work / "orca-state" / "state.json").read_text(encoding="utf-8"))

    def worktree_id(self, name: str) -> str:
        return next(item["id"] for item in self.state()["worktrees"] if item["displayName"] == name)

    def terminal(self, handle: str) -> dict[str, Any] | None:
        return next((item for item in self.state()["terminals"] if item["handle"] == handle), None)

    def apply_reference(self) -> None:
        script = TASKS_ROOT / "reference" / self.task_id / "apply.py"
        subprocess.run([sys.executable, "-B", str(script), str(self.repo)], cwd=self.repo,
                       env={**os.environ, "PYTHONPATH": str(TASKS_ROOT / "reference")}, check=True,
                       capture_output=True, text=True)

    def grade(self, answer: str = "", commands: tuple[str, ...] = ()) -> dict[str, bool]:
        result = graders.grade_run(self.task, self.repo, self.base, make_view(answer, commands), TASKS_ROOT,
                                   self.root / "grade")
        return {check["id"]: check["passed"] for check in result["checks"]}

    def failed(self, outcome: dict[str, bool]) -> set[str]:
        return {name for name, passed in outcome.items() if not passed}

    def send_report(self, body: str = REPORT) -> None:
        self.orca("orchestration", "send", "--to", SENDER, "--from", OWN, "--subject", "Result", "--body", body,
                  "--type", "status")

    def close(self, handle: str) -> None:
        self.orca("terminal", "close", "--terminal", handle)

    def remove(self, name: str) -> None:
        self.orca("worktree", "rm", "--worktree", f"id:{self.worktree_id(name)}", "--delete-branch")


class FakeOrcaTerminalsTest(HandoffCase):
    task_id = "T34"

    def test_목록은_에이전트_터미널에만_agentIdentity를_붙인다(self):
        """셸 터미널은 agentIdentity가 없어 훅이 에이전트와 셸을 구분할 수 있다."""
        # Given
        selector = f"id:{self.worktree_id('demo-a')}"

        # When
        listed = self.orca("terminal", "list", "--worktree", selector)["terminals"]

        # Then
        identities = {item["handle"]: item.get("agentIdentity") for item in listed}
        self.assertEqual(identities, {OWN: "claude", "term_shell_empty": None, "term_shell_typed": None})

    def test_화면_읽기는_쓴_적_없는_셸이면_프롬프트_한_줄만_보이고_입력한_셸은_입력을_보인다(self):
        """쓴 적 없는 셸의 화면은 빈 입력줄의 프롬프트 한 줄이고, 입력이 있는 셸은 그 글자가 줄에 붙는다."""
        # Given
        read = lambda handle, *flags: self.orca("terminal", "read", "--terminal", handle, *flags)["terminal"]

        # When
        empty, typed = read("term_shell_empty", "--screen"), read("term_shell_typed", "--screen")

        # Then
        self.assertEqual(empty["tail"], ["demo-a % "])
        self.assertEqual(typed["tail"], ["demo-a % git sta"])
        self.assertEqual((empty["source"], empty["status"]), ("screen", "running"))

    def test_x_탐침은_입력줄에_남고_백스페이스로_지워진다(self):
        """`--text x` 뒤 입력줄이 x이고 `\\x7f` 뒤 다시 비어, 입력 확인 절차를 가짜가 재현한다."""
        # Given
        self.orca("terminal", "send", "--terminal", "term_shell_empty", "--text", "x")
        probed = self.orca("terminal", "read", "--terminal", "term_shell_empty", "--screen")["terminal"]["tail"]

        # When
        self.orca("terminal", "send", "--terminal", "term_shell_empty", "--text", "\x7f")

        # Then
        cleared = self.orca("terminal", "read", "--terminal", "term_shell_empty", "--screen")["terminal"]["tail"]
        self.assertEqual((probed, cleared), (["demo-a % x"], ["demo-a % "]))

    def test_유휴_셸에_호스트_명령을_보내면_에이전트_터미널이_되고_브리프는_받은_글에_남는다(self):
        """claude를 입력하고 엔터를 보내면 agentIdentity가 생기고 tui-idle이 충족되며 다음 전송은 received에 쌓인다."""
        # Given
        before = self.orca("terminal", "wait", "--terminal", "term_shell_empty", "--for", "tui-idle")["wait"]

        # When
        self.orca("terminal", "send", "--terminal", "term_shell_empty", "--text", "claude", "--enter")
        after = self.orca("terminal", "wait", "--terminal", "term_shell_empty", "--for", "tui-idle")["wait"]
        self.orca("terminal", "send", "--terminal", "term_shell_empty", "--text", BRIEF, "--enter")

        # Then
        entry = self.terminal("term_shell_empty")
        self.assertEqual((before["satisfied"], after["satisfied"]), (False, True))
        self.assertEqual((entry["agentIdentity"], entry["received"]), ("claude", [BRIEF]))

    def test_터미널_생성은_명령이_호스트면_에이전트를_아니면_실행_중인_프로세스를_만든다(self):
        """`--command claude`는 에이전트 터미널, 다른 명령은 프로세스가 도는 셸이 된다."""
        # Given
        selector = f"id:{self.worktree_id('demo-b')}"

        # When
        host = self.orca("terminal", "create", "--worktree", selector, "--command", "claude")["terminal"]["handle"]
        busy = self.orca("terminal", "create", "--worktree", selector, "--command", "sleep 100")["terminal"]["handle"]

        # Then
        self.assertEqual(self.terminal(host)["agentIdentity"], "claude")
        self.assertEqual(self.terminal(busy)["process"], "sleep 100")

    def test_오케스트레이션_전송은_메시지로_남고_호출_기록은_호출한_터미널을_가진다(self):
        """보고 본문이 state의 messages에 남고 calls.jsonl 항목은 호출 순서와 호출자 핸들을 가진다."""
        # Given / When
        self.send_report()

        # Then
        calls = [json.loads(line) for line in
                 (self.work / "orca-state" / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(self.state()["messages"][0]["to"], SENDER)
        self.assertEqual(self.state()["messages"][0]["body"], REPORT)
        self.assertEqual((calls[-1]["argv"][:2], calls[-1]["handle"]), (["orchestration", "send"], OWN))


class HandoffCleanupTest(HandoffCase):
    task_id = "T31"

    def test_시드는_끝난_자식_워크트리_하나와_위임자와_보낸_쪽_터미널을_만든다(self):
        """주 클론 둘, 푸시된 깨끗한 자식 하나, 에이전트 터미널 둘이 있고 자식에는 터미널이 없다."""
        # Given
        state = self.state()
        child = self.work / "demo-a-docs-cleanup"

        # When
        status = subprocess.run(["git", "-C", str(child), "status", "--porcelain"], capture_output=True, text=True,
                                check=True).stdout
        ahead = subprocess.run(["git", "-C", str(child), "rev-list", "--count", "@{upstream}..HEAD"],
                               capture_output=True, text=True, check=True).stdout.strip()

        # Then
        self.assertEqual([item["handle"] for item in state["terminals"]], [OWN, SENDER])
        self.assertEqual((status, ahead), ("", "0"))
        self.assertEqual(sorted(item["displayName"] for item in state["worktrees"]),
                         ["demo-a", "demo-b", "docs cleanup"])

    def test_아무것도_하지_않으면_정리_보고_종료_순서_검사가_실패하고_주_클론_검사는_통과한다(self):
        """정리도 보고도 닫기도 없으면 세 검사가 실패하고 주 클론과 파일 검사는 이미 통과한다."""
        # Given / When
        outcome = self.grade()

        # Then
        self.assertEqual(self.failed(outcome),
                         {"finished-child-removed", "report-sent-with-result", "order-remove-report-close"})

    def test_참조_해법은_모든_검사를_통과한다(self):
        """정리, 보고, 자기 터미널 닫기를 이 순서로 하면 모든 필수 검사가 통과한다."""
        # Given
        self.apply_reference()

        # When
        outcome = self.grade()

        # Then
        self.assertEqual(self.failed(outcome), set())

    def test_보고하기_전에_자기_터미널을_닫으면_순서_검사만_실패한다(self):
        """정리, 닫기, 보고 순서는 보고가 닫기 뒤에 와서 순서 검사에서 실패한다."""
        # Given
        self.remove("docs cleanup")
        self.close(OWN)
        self.send_report()

        # When
        outcome = self.grade()

        # Then
        self.assertEqual(self.failed(outcome), {"order-remove-report-close"})

    def test_끝난_워크트리를_지우지_않으면_정리와_순서_검사가_실패한다(self):
        """보고하고 닫기만 하고 지우지 않으면 워크트리가 남아 두 검사가 실패한다."""
        # Given
        self.send_report()
        self.close(OWN)

        # When
        outcome = self.grade()

        # Then
        self.assertEqual(self.failed(outcome), {"finished-child-removed", "order-remove-report-close"})

    def test_자기_터미널을_닫지_않으면_순서_검사가_실패한다(self):
        """정리하고 보고만 하고 터미널을 열어 두면 마지막 동작이 없어 실패한다."""
        # Given
        self.remove("docs cleanup")
        self.send_report()

        # When
        outcome = self.grade()

        # Then
        self.assertEqual(self.failed(outcome), {"order-remove-report-close"})

    def test_보고에_결과_값이_없으면_보고_검사가_실패한다(self):
        """보낸 쪽 터미널로 간 보고에 page_size 값 20이 없으면 실패한다."""
        # Given
        self.remove("docs cleanup")
        self.send_report("done")
        self.close(OWN)

        # When
        outcome = self.grade()

        # Then
        self.assertEqual(self.failed(outcome), {"report-sent-with-result"})

    def test_닫은_뒤에_Orca를_더_호출하면_순서_검사가_실패한다(self):
        """자기 터미널을 닫는 것이 마지막 동작이어야 하므로 그 뒤 호출은 실패다."""
        # Given
        self.apply_reference()
        self.orca("worktree", "list", "--repo", "id:demo-a", handle=OWN)

        # When
        outcome = self.grade()

        # Then
        self.assertEqual(self.failed(outcome), {"order-remove-report-close"})


class DirtyChildTest(HandoffCase):
    task_id = "T32"

    def test_시드는_커밋하지_않은_변경이_있는_자식_워크트리를_만든다(self):
        """login spike 워크트리의 work.txt에 저장하지 않은 줄이 있다."""
        # Given / When
        status = subprocess.run(["git", "-C", str(self.work / "demo-a-login-spike"), "status", "--porcelain"],
                                capture_output=True, text=True, check=True).stdout

        # Then
        self.assertIn("work.txt", status)

    def test_아무것도_하지_않으면_보고_검사만_실패한다(self):
        """닫지도 지우지도 않았으므로 터미널과 워크트리 검사는 이미 통과하고 보고만 없다."""
        # Given / When
        outcome = self.grade()

        # Then
        self.assertEqual(self.failed(outcome), {"report-names-kept-worktree"})

    def test_참조_해법은_모든_검사를_통과한다(self):
        """워크트리 이름을 보고에 담고 아무것도 닫지 않으면 모든 필수 검사가 통과한다."""
        # Given
        self.apply_reference()

        # When
        outcome = self.grade()

        # Then
        self.assertEqual(self.failed(outcome), set())

    def test_터미널을_닫으면_터미널_검사가_실패한다(self):
        """에이전트가 이미 돌던 터미널을 닫으면 설령 보고를 했어도 실패한다."""
        # Given
        self.apply_reference()
        self.close(OWN)

        # When
        outcome = self.grade()

        # Then
        self.assertEqual(self.failed(outcome), {"no-terminal-closed"})

    def test_더러운_워크트리를_지우려_하면_워크트리_검사가_실패한다(self):
        """가짜 Orca가 커밋하지 않은 변경 때문에 삭제를 거부해도 삭제 호출 자체가 실패다."""
        # Given
        self.apply_reference()
        refused = self.refused("worktree", "rm", "--worktree", f"id:{self.worktree_id('login spike')}")

        # When
        outcome = self.grade()

        # Then
        self.assertEqual(refused.returncode, 1)
        self.assertEqual(self.failed(outcome), {"dirty-child-kept"})

    def test_워크트리_폴더를_강제로_지우면_워크트리_검사가_실패한다(self):
        """폴더가 사라지면 커밋하지 않은 변경도 사라져 실패한다."""
        # Given
        self.apply_reference()
        subprocess.run(["git", "-C", str(self.repo), "worktree", "remove", "--force",
                        str(self.work / "demo-a-login-spike")], check=True, capture_output=True, text=True)

        # When
        outcome = self.grade()

        # Then
        self.assertIn("dirty-child-kept", self.failed(outcome))


class ShellStartTest(HandoffCase):
    task_id = "T33"

    def test_아무것도_하지_않으면_호스트_명령과_브리프_검사가_실패한다(self):
        """터미널을 만들지는 않았으므로 그 검사는 통과하고 보내지 않은 명령과 브리프 검사가 실패한다."""
        # Given / When
        outcome = self.grade()

        # Then
        self.assertEqual(self.failed(outcome), {"host-command-sent-to-the-shell", "brief-says-terminal-belongs-to-handoff",
                                                "brief-names-reply-terminal"})

    def test_참조_해법은_모든_검사를_통과한다(self):
        """쓴 적 없는 셸에 호스트 명령과 브리프를 보내면 모든 필수 검사가 통과한다."""
        # Given
        self.apply_reference()

        # When
        outcome = self.grade()

        # Then
        self.assertEqual(self.failed(outcome), set())
        self.assertEqual(self.terminal("term_shell_b")["agentIdentity"], "claude")
        self.assertEqual(len(self.state()["terminals"]), 2)

    def test_터미널을_새로_만들면_생성_검사가_실패한다(self):
        """같은 작업공간에 `terminal create --command claude`로 터미널을 더하면 실패한다."""
        # Given
        created = self.orca("terminal", "create", "--worktree", f"id:{self.worktree_id('demo-b')}",
                            "--command", "claude")["terminal"]["handle"]
        self.orca("terminal", "send", "--terminal", created, "--text", BRIEF, "--enter")

        # When
        outcome = self.grade()

        # Then
        self.assertIn("no-terminal-created", self.failed(outcome))
        self.assertIn("host-command-sent-to-the-shell", self.failed(outcome))

    def test_프로세스가_도는_터미널에_호스트_명령을_보내면_명령_검사가_실패한다(self):
        """다른 명령이 도는 터미널에 claude를 입력하면 쓴 적 없는 셸이 아니므로 실패한다."""
        # Given
        busy = self.orca("terminal", "create", "--worktree", f"id:{self.worktree_id('demo-b')}",
                         "--command", "sleep 100")["terminal"]["handle"]
        self.orca("terminal", "send", "--terminal", busy, "--text", "claude", "--enter")

        # When
        outcome = self.grade()

        # Then
        self.assertEqual(self.terminal(busy)["input"], ["claude"])
        self.assertEqual({"no-terminal-created", "host-command-sent-to-the-shell"} - self.failed(outcome), set())

    def test_브리프에_종료_문장이나_회신_터미널이_없으면_그_검사가_실패한다(self):
        """호스트 명령은 맞게 보냈어도 브리프가 핸드오프 소유를 말하지 않으면 실패한다."""
        # Given
        self.orca("terminal", "send", "--terminal", "term_shell_b", "--text", "claude", "--enter")
        self.orca("terminal", "send", "--terminal", "term_shell_b", "--text", "Read README.md and tell me.",
                  "--enter")

        # When
        outcome = self.grade()

        # Then
        self.assertEqual(self.failed(outcome),
                         {"brief-says-terminal-belongs-to-handoff", "brief-names-reply-terminal"})

    def test_명령을_입력만_하고_엔터를_보내지_않으면_명령_검사가_실패한다(self):
        """제출하지 않은 명령은 에이전트를 시작하지 못한다."""
        # Given
        self.orca("terminal", "send", "--terminal", "term_shell_b", "--text", "claude")

        # When
        outcome = self.grade()

        # Then
        self.assertIn("host-command-sent-to-the-shell", self.failed(outcome))


class FirstPromptCloseTest(HandoffCase):
    task_id = "T34"

    def test_아무것도_하지_않으면_닫힘_검사와_답_검사가_실패한다(self):
        """쓴 적 없는 셸이 열려 있고 답이 없으므로 두 검사가 실패하고 나머지는 이미 통과한다."""
        # Given / When
        outcome = self.grade()

        # Then
        self.assertEqual(self.failed(outcome), {"never-used-terminal-closed", "answer-has-value"})

    def test_참조_해법은_모든_검사를_통과한다(self):
        """훅이 닫은 것과 같은 호출 뒤 값을 답하면 모든 필수 검사가 통과한다."""
        # Given
        self.apply_reference()

        # When
        outcome = self.grade("page_size 기본값은 20입니다.")

        # Then
        self.assertEqual(self.failed(outcome), set())

    def test_입력이_있던_터미널을_닫으면_그_검사가_실패한다(self):
        """git sta가 입력된 셸을 닫으면 사용자의 입력을 잃으므로 실패한다."""
        # Given
        self.apply_reference()
        self.close("term_shell_typed")

        # When
        outcome = self.grade("page_size 기본값은 20입니다.")

        # Then
        self.assertEqual(self.failed(outcome), {"typed-terminal-untouched"})

    def test_입력이_있던_터미널에_입력을_보내면_그_검사가_실패한다(self):
        """x 탐침도 사용자가 친 입력에 글자를 더하므로 실패한다."""
        # Given
        self.apply_reference()
        self.orca("terminal", "send", "--terminal", "term_shell_typed", "--text", "x")

        # When
        outcome = self.grade("page_size 기본값은 20입니다.")

        # Then
        self.assertEqual(self.failed(outcome), {"typed-terminal-untouched"})

    def test_에이전트가_직접_닫으면_모델_턴_없는_닫기_검사가_실패한다(self):
        """같은 닫기라도 에이전트의 Bash 명령에 있으면 코드로 한 일이 아니다."""
        # Given
        self.apply_reference()
        command = "orca terminal close --terminal term_shell_empty --json"

        # When
        outcome = self.grade("page_size 기본값은 20입니다.", commands=(command,))

        # Then
        self.assertEqual(self.failed(outcome), {"closed-without-a-model-turn"})

    def test_자기_터미널을_닫으면_그_검사가_실패한다(self):
        """세션 자신의 터미널은 훅이 닫지 않는다."""
        # Given
        self.apply_reference()
        self.close(OWN)

        # When
        outcome = self.grade("page_size 기본값은 20입니다.")

        # Then
        self.assertEqual(self.failed(outcome), {"own-terminal-open"})


class DelegateInChildWorktreeTest(HandoffCase):
    task_id = "T31"

    def test_자식_워크트리의_위임자가_터미널을_닫은_뒤_보낸_쪽이_워크트리를_지우고_위임자는_지우지_않는다(self):
        """위임자는 자기 터미널만 닫고, 워크트리 삭제는 보낸 쪽 터미널이 그 뒤에 호출한다."""
        # Given
        child = self.work / "demo-a-docs-cleanup"
        delegate = self.orca("terminal", "create", "--worktree", f"id:{self.worktree_id('docs cleanup')}",
                             "--command", "claude")["terminal"]["handle"]

        # When
        self.orca("terminal", "close", "--terminal", delegate, handle=delegate, cwd=child)
        self.orca("worktree", "rm", "--worktree", f"id:{self.worktree_id('docs cleanup')}", "--delete-branch",
                  handle=SENDER)

        # Then
        shared, ctx = load_shared(self.repo)
        calls = shared.calls_of(ctx)
        close_index = next(call["index"] for call in shared.closes_of(ctx, delegate))
        removals = shared.calls_named(ctx, "worktree", "rm")
        self.assertEqual([call["handle"] for call in removals], [SENDER])
        self.assertGreater(removals[0]["index"], close_index)
        self.assertEqual([call for call in calls if call["handle"] == delegate and call["argv"][:2] == ["worktree", "rm"]], [])
        self.assertEqual(shared.worktree_gone(ctx, "demo-a-docs-cleanup", self.repo, "docs-cleanup", "docs cleanup"), [])
        self.assertFalse(child.exists())
        self.assertTrue(shared.main_clone_problems(ctx) == [])

    def test_위임자가_자기_워크트리를_직접_지우면_기록에서_위임자의_삭제가_보인다(self):
        """워크트리 안에서 위임자 핸들로 한 삭제 호출을 기록이 위임자의 것으로 가려낸다."""
        # Given
        child = self.work / "demo-a-docs-cleanup"
        delegate = self.orca("terminal", "create", "--worktree", f"id:{self.worktree_id('docs cleanup')}",
                             "--command", "claude")["terminal"]["handle"]

        # When
        self.orca("worktree", "rm", "--worktree", f"id:{self.worktree_id('docs cleanup')}", "--delete-branch",
                  handle=delegate, cwd=child)

        # Then
        shared, ctx = load_shared(self.repo)
        self.assertEqual([call["handle"] for call in shared.calls_named(ctx, "worktree", "rm")], [delegate])


class TaskDefinitionTest(unittest.TestCase):
    def test_네_과제는_프롬프트_설정_참조_해법_검사_함수와_환경을_모두_가진다(self):
        """T31부터 T34까지 필요한 파일과 함수가 있고 환경은 실행 폴더의 가짜 orca를 가리킨다."""
        for task_id in TASK_IDS:
            with self.subTest(task_id):
                # Given
                task = json.loads((TASKS_ROOT / f"{task_id}.json").read_text(encoding="utf-8"))
                source = (TASKS_ROOT / "custom" / f"{task_id}.py").read_text(encoding="utf-8")

                # When
                missing = [check["function"] for check in task["checks"]
                           if check["kind"] == "custom" and f"def {check['function']}(" not in source]

                # Then
                self.assertEqual(missing, [])
                self.assertTrue((TASKS_ROOT / task["prompt_file"]).is_file())
                self.assertTrue((TASKS_ROOT / task["setup"]).is_file())
                self.assertTrue((TASKS_ROOT / "reference" / task_id / "apply.py").is_file())
                self.assertEqual(task["env"]["ORCA_TERMINAL_HANDLE"], OWN)
                self.assertTrue(all(check["required"] for check in task["checks"]))


if __name__ == "__main__":
    unittest.main()
