"""Structural checks for the Codex worker adapter.

These checks confirm that the adapter states each required host policy. They do not prove that a live
Codex session follows it; native trials cover that.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CODEX_AGENTS = REPO_ROOT / "instructions/codex-agents.md"


def implementation_section() -> str:
    text = CODEX_AGENTS.read_text(encoding="utf-8")
    return " ".join(text.split("## Implementation", 1)[1].split())


class CodexWorkerContractTest(unittest.TestCase):
    def test_구현은_공유_실행_규칙과_내장_worker만_사용한다(self):
        """Codex 구현은 공유 실행 규칙을 따르고 내장 worker에 모델과 xhigh를 명시적으로 넘긴다."""
        # Given
        expected = (
            "[implementation execution rules](implementation-execution.md)",
            "Use only the plugin `worker` role for implementation.",
            "pass the pinned `gpt-6-luna` and `xhigh` explicitly on every spawn",
        )

        # When
        section = implementation_section()

        # Then
        for phrase in expected:
            self.assertIn(phrase, section)

    def test_실행_중에는_모델을_다시_찾지_않고_고정값을_쓴다(self):
        """Codex 구현과 조사는 실행할 때 모델 문서나 카탈로그를 다시 찾지 않고 고정된 Luna ID를 넘긴다."""
        # Given
        text = " ".join(CODEX_AGENTS.read_text(encoding="utf-8").split())

        # When
        section = implementation_section()

        # Then
        self.assertIn("Pass `gpt-6-luna` and `xhigh` explicitly on every spawn.", text)
        for lookup in ("developers.openai.com", "learn.chatgpt.com", "model selector"):
            self.assertNotIn(lookup, section)
        self.assertEqual({"gpt-6-luna"}, set(re.findall(r"gpt-[\w.-]+", text)))

    def test_전체_기록_fork로는_worker를_만들지_않는다(self):
        """전체 기록 fork는 재정의를 거부하므로 범위를 한정한 맥락으로 worker를 생성한다."""
        # Given
        rule = "Full-history forks inherit the parent model and effort and reject overrides."

        # When
        section = implementation_section()

        # Then
        self.assertIn(rule, section)
        self.assertIn('set `fork_turns` to `"none"` or a positive integer', section)
        self.assertIn("leave `fork_context` off", section)

    def test_worker_역할_파일은_검사하되_덮어쓰지_않는다(self):
        """worker 역할 파일과 기본값은 비밀이 아닌 항목만 확인하고, 없거나 고정값과 다르면 막으며 기존 파일은 덮어쓰지 않는다."""
        # Given
        protected = ("`~/.codex/agents/worker.toml`", "`.codex/agents/worker.toml`")

        # When
        section = implementation_section()

        # Then
        self.assertIn("inspect only the `model`, `model_reasoning_effort`, and relevant `[agents]`", section)
        self.assertIn("including the `worker` role file in the personal or project Codex agents directory", section)
        self.assertIn("it must still resolve to `gpt-6-luna` and `xhigh`", section)
        self.assertIn("a missing `worker` role file", section)
        self.assertIn("an incompatible user configuration", section)
        for path in protected:
            self.assertIn(path, section)
        self.assertIn("Never overwrite an existing", section)
        self.assertNotIn("Never install", section)
        self.assertIn("never change global model defaults", section)

    def test_worker_rollout_기록을_실제_설정의_근거로_쓴다(self):
        """생성 인수와 부모 스레드로 찾은 worker rollout의 turn_context만 실제 모델과 사고 강도의 근거로 인정한다."""
        # Given
        expected = (
            "Accept the explicit spawn arguments plus the worker's rollout record as evidence.",
            "the sessions directory under `CODEX_HOME`",
            "its `session_meta` names the parent thread from the coordinator's `CODEX_THREAD_ID`",
            "its `turn_context` names the actual `model` and `effort`",
            "A worker's self-report is not this record.",
        )

        # When
        section = implementation_section()

        # Then
        for phrase in expected:
            self.assertIn(phrase, section)

    def test_이어_보내기_지원_여부에_따라_준비_확인_경로가_갈린다(self):
        """생성 결과에 모델이 없으므로 준비 확인 뒤 같은 스레드에 구현을 보내고, 이어 보내기가 없으면 수정하지 않는다."""
        # Given
        readiness = "The spawn result does not name the model, so start each worker with a readiness-only assignment."
        supported = "Use this path only when that follow-up keeps its settings."
        unsupported = "When that continuation is unavailable, skip the two-phase path and make no edits."

        # When
        section = implementation_section()

        # Then
        self.assertIn(readiness, section)
        self.assertIn("send the implementation assignment to the same worker thread with a follow-up", section)
        self.assertIn(supported, section)
        self.assertIn(unsupported, section)
        self.assertIn("Recheck the settings after any resume.", section)

    def test_기능이_없으면_대체하지_않고_막는다(self):
        """worker 도구, 모델, xhigh, 실제 설정 근거가 없으면 구현을 막고 정확한 원인을 보고한다."""
        # Given
        blockers = (
            "Missing worker tools",
            "an unavailable model or `xhigh`",
            "unverified effective settings block the affected implementation",
            "Report the exact capability and make no edit.",
        )

        # When
        section = implementation_section()

        # Then
        for blocker in blockers:
            self.assertIn(blocker, section)

    def test_호스트가_위임을_허용하지_않으면_한_번_묻고_수정하지_않는다(self):
        """Codex가 명시적 요청 없이는 서브에이전트를 만들지 않으므로 거부할 때 위임 허가를 한 번 묻고 수정하지 않는다."""
        # Given
        expected = (
            "Codex spawns sub-agents only when the user, `AGENTS.md`, or skill instructions ask for them",
            "ask the user once to authorize worker delegation and make no edit until they answer.",
        )

        # When
        section = implementation_section()

        # Then
        for phrase in expected:
            self.assertIn(phrase, section)

    def test_호스트_한도는_메인_스레드를_빼고_세며_바꾸지_않는다(self):
        """Codex 동시 실행 한도는 생성한 스레드만 세고 조정자는 그 값을 바꾸지 않는다."""
        # Given
        limit = "`agents.max_concurrent_threads_per_session`, which counts spawned threads but not the main thread"

        # When
        section = implementation_section()

        # Then
        self.assertIn(limit, section)
        self.assertIn("never change it", section)

    def test_조사는_내장_explorer_대신_scout를_쓴다(self):
        """Codex 조사는 Claude와 같은 이름의 scout만 쓰고, 쓸 수 없거나 역할 파일이 고정값을 바꾸면 메인 세션에서 조사한다."""
        # Given
        text = CODEX_AGENTS.read_text(encoding="utf-8")

        # When
        investigation = " ".join(text.split("## Investigation", 1)[1].split("## Skill workers", 1)[0].split())

        # Then
        self.assertIn("Use the `scout` agent only for bounded, read-only investigation while planning", investigation)
        self.assertIn("Its bundled role file sets no model, so the spawn value applies.", investigation)
        self.assertIn(
            "If `scout` is unavailable, or its role file in the Codex agents directory sets another model or effort, "
            "investigate in the main session.",
            investigation,
        )
        self.assertIn("Treat results as leads.", investigation)


    def test_내장_에이전트는_모두_금지하고_플러그인_역할을_설치한다(self):
        """default와 explorer, 종류를 비운 호출을 금지하고 훅이 설치한 scout와 worker 역할만 쓴다."""
        # Given
        text = CODEX_AGENTS.read_text(encoding="utf-8")

        # When
        built_in = " ".join(text.split("## Built-in agents", 1)[1].split("## Investigation", 1)[0].split())

        # Then
        self.assertIn("Never use the built-in `default` or `explorer` agents.", built_in)
        self.assertIn("Always pass `agent_type`, because an omitted type runs `default`.", built_in)
        self.assertIn("installs the plugin's `scout` and `worker` roles in `~/.codex/agents/` when they are absent", built_in)
        self.assertIn("so it also denies the built-in `worker` until the plugin role exists", built_in)

    def test_스킬_작업자는_scout나_별도_CLI_프로세스를_쓴다(self):
        """스킬이 요구하는 읽기 전용 작업자는 scout, 시험 출력을 쓰는 작업자는 별도 codex exec 프로세스로 실행한다."""
        # Given
        text = CODEX_AGENTS.read_text(encoding="utf-8")

        # When
        skill_workers = " ".join(text.split("## Skill workers", 1)[1].split("## Implementation", 1)[0].split())

        # Then
        self.assertIn("use `scout` with the model and effort above", skill_workers)
        self.assertIn("The main session writes any file the role produces.", skill_workers)
        self.assertIn("run a separate `codex exec` process with the model and effort that the skill pins", skill_workers)


if __name__ == "__main__":
    unittest.main()
