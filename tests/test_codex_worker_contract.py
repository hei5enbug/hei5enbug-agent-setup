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
    def test_위임한_구현은_공유_위임_규칙과_플러그인_worker를_사용한다(self):
        """Codex에서 구현을 위임할 때는 Sonnet 실행기를 먼저 쓰고, 실행기가 실패하면 플러그인 worker에 모델과 effort를 명시적으로 넘긴다."""
        # Given
        expected = (
            "[implementation delegation rules](implementation-delegation.md)",
            "Delegate implementation to the `implementation` capability runner, which runs `claude-sonnet-5-5`:",
            "implementation --host codex --instructions <Source directory>/agents/worker.md --add-dir <dir> "
            "--assignment <file> --result <file>",
            "When it exits 3 or 4, inspect the partial diff and use the plugin `worker` role as the fallback.",
            "pass the model and effort from the session line \"Codex worker model\" explicitly on every spawn",
        )

        # When
        section = implementation_section()

        # Then
        for phrase in expected:
            self.assertIn(phrase, section)

    def test_Codex_worker와_designer_정의는_세션_지침이나_할당의_규칙을_따른다(self):
        """worker와 designer 정의는 연결된 파일이 아니라 세션 지침이나 할당에 있는 Assigned workers 규칙을 따른다."""
        # Given
        names = ("worker", "designer")

        for name in names:
            with self.subTest(name=name):
                # When
                text = (REPO_ROOT / f"standalone-agents/codex-{name}.toml").read_text(encoding="utf-8")

                # Then
                self.assertIn(
                    'When your session instructions or assignment carry the "Assigned workers" rules, follow them '
                    "together with your assignment, and report a missing required assignment field to the "
                    "coordinator instead of editing.",
                    text,
                )
                self.assertNotIn("link the implementation execution rules", text)
                self.assertIn("the plugin rules are inactive", text)

    def test_Codex_designer_정의는_design_기능의_기술_설계_문서와_허용_경로_문서_쓰기를_포함한다(self):
        """designer TOML의 설명과 지침은 design 기능의 기술 설계 문서 초안 작성과 허용 경로의 문서 파일 쓰기를 포함한다."""
        # Given
        text = (REPO_ROOT / "standalone-agents/codex-designer.toml").read_text(encoding="utf-8")
        description = next(line for line in text.splitlines() if line.startswith("description = "))
        instructions = " ".join(text.split("developer_instructions", 1)[1].split())

        # When
        covers = ("technical design document" in description, "the `design` capability" in instructions)

        # Then
        self.assertEqual((True, True), covers)
        self.assertIn("including writing the document file in the allowed path", instructions)

    def test_실행_중에는_모델을_다시_찾지_않고_고정값을_쓴다(self):
        """Codex 구현과 조사는 실행할 때 모델 문서나 카탈로그를 다시 찾지 않고 고정된 Luna ID를 넘긴다."""
        # Given
        text = " ".join(CODEX_AGENTS.read_text(encoding="utf-8").split())

        # When
        section = implementation_section()

        # Then
        self.assertIn(
            "Pass `gpt-5.6-luna` and `high` explicitly on every spawn, or `xhigh` under the effort rule in "
            "[shared model routing](model-routing.md#keep-role-settings-fixed).",
            " ".join(text.split()),
        )
        for lookup in ("developers.openai.com", "learn.chatgpt.com", "model selector"):
            self.assertNotIn(lookup, section)
        self.assertEqual({"gpt-5.6-luna", "gpt-6-astra", "gpt-6.1-sol"}, set(re.findall(r"gpt-[\w.-]+", text)))

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
        self.assertIn("it must still resolve to that model and effort", section)
        self.assertIn("a missing `worker` role file", section)
        self.assertIn("an incompatible user configuration", section)
        for path in protected:
            self.assertIn(path, section)
        self.assertIn("Never overwrite an existing", section)
        self.assertNotIn("Never install", section)
        self.assertIn("never change global model defaults", section)

    def test_worker_결과는_생성된_역할_검증을_통과한_뒤에만_인정한다(self):
        """worker 결과는 verify_spawn 검증을 통과한 뒤에만 쓰고, 검증 규칙은 한 곳에서 종료 코드별로 정한다."""
        # Given
        expected = (
            "Accept the worker's result only after the spawned role verification section below passes.",
        )
        verification = " ".join(CODEX_AGENTS.read_text(encoding="utf-8").split("## Spawned role verification", 1)[1].split())

        # When
        section = implementation_section()

        # Then
        for phrase in expected:
            self.assertIn(phrase, section)
        self.assertNotIn("sessions directory", section)
        self.assertIn("python3 <Source directory>/scripts/verify_spawn.py --parent \"$CODEX_THREAD_ID\"", verification)
        self.assertIn("--agent-path /root/<task_name>", verification)
        self.assertIn("--sandbox <sandbox_mode>", verification)
        self.assertIn("Exit 0 verifies the rollout.", verification)
        self.assertIn("Exit 4 means the rollout is missing or names another model, effort, or sandbox.", verification)
        self.assertIn("Do not respawn it with another pair, because the agent guard denies a fallback pair in Codex.", verification)
        self.assertIn("or continue in the main session", verification)

    def test_이어_보내기_지원_여부에_따라_준비_확인_경로가_갈린다(self):
        """생성 결과에 모델이 없으므로 구현 위임 규칙의 준비 확인 경로를 따라 같은 스레드에 구현을 보낸다."""
        # Given
        readiness = (
            "The spawn result does not name the model, so follow the readiness-only path in implementation delegation "
            "and send the implementation assignment to the same worker thread with a follow-up."
        )

        # When
        section = implementation_section()

        # Then
        self.assertIn(readiness, section)
        self.assertNotIn("Use this path only when that follow-up keeps", section)
        self.assertNotIn("self-report", section)

    def test_기능이_없으면_위임을_멈추고_메인_대체_처리를_쓴다(self):
        """worker 도구, 모델, xhigh, 실제 설정 근거가 없으면 위임을 멈추고 공통 대체 처리를 적용한다."""
        # Given
        blockers = (
            "Missing worker tools",
            "an unavailable model or effort",
            "unverified effective settings stop the affected delegation",
            "Apply the session fallback.",
        )

        # When
        section = implementation_section()

        # Then
        for blocker in blockers:
            self.assertIn(blocker, section)

    def test_호스트_위임_승인이_없으면_작업을_막지_않고_메인에서_계속한다(self):
        """Codex는 기존 위임 승인을 재사용하고 없으면 호스트 권한을 우회하지 않고 메인에서 계속한다."""
        # Given
        expected = (
            "Codex spawns sub-agents only when the user, `AGENTS.md`, or skill instructions ask for them",
            "keeps a marked block in `~/.codex/AGENTS.md` that grants this",
            "removed when `HEI5ENBUG_SUBAGENT_POLICY=off`",
            "continue in the main session under the session fallback.",
            "enables `default_mode_request_user_input`, so `request_user_input` works in Default mode",
        )

        # When
        section = implementation_section()

        # Then
        for phrase in expected:
            self.assertIn(phrase, section)

    def test_디자인_작업은_designer_역할을_먼저_쓰고_실패하면_실행기_대체를_한_번_쓴다(self):
        """디자인 작업은 designer 역할로 먼저 실행하고, 실패하면 역할 실행기의 designer 대체 항목을 한 번 쓴다."""
        # Given
        text = CODEX_AGENTS.read_text(encoding="utf-8")
        expected = (
            "The primary is the plugin `designer` role with `gpt-6-astra` and `high` passed explicitly on the spawn, or "
            "`xhigh` under the effort rule in [shared model routing](model-routing.md#keep-role-settings-fixed);",
            "verify it under the spawned role verification section below.",
            "run the fallback once through the role runner from the repository root:",
            "python3 <Source directory>/scripts/role_runner.py agent --name designer --fallback --host codex "
            "--add-dir <allowed path> --assignment <file> --result <file>",
            "Request network access through the normal Codex approval flow if the sandbox blocks it.",
            "On runner exit 3 or 4, continue in the main session.",
        )

        # When
        design = " ".join(text.split("## Design work", 1)[1].split("## Spawned role verification", 1)[0].split())

        # Then
        for phrase in expected:
            self.assertIn(phrase, design)
        self.assertNotIn("claude -p", design)
        self.assertNotIn("modelUsage", design)

    def test_호스트_한도는_메인_스레드를_빼고_세며_바꾸지_않는다(self):
        """Codex 동시 실행 한도는 생성한 스레드만 세고 조정자는 그 값을 바꾸지 않는다."""
        # Given
        limit = "`agents.max_concurrent_threads_per_session`, which counts spawned threads but not the main thread"

        # When
        section = implementation_section()

        # Then
        self.assertIn(limit, section)
        self.assertIn("never change it", section)

    def test_공유_라우팅은_배포_전에_읽고_기존_조사_설정을_유지한다(self):
        """공유 라우팅을 필요할 때 읽고 공개 조사 도구와 고정 설정이 없으면 메인에서 계속한다."""
        # Given
        text = CODEX_AGENTS.read_text(encoding="utf-8")

        # When
        normalized = " ".join(text.split())
        investigation = " ".join(text.split("## Investigation", 1)[1].split("## Skill workers", 1)[0].split())

        # Then
        self.assertIn("Read [shared model routing](model-routing.md) before dispatching", normalized)
        self.assertIn("For bounded public research, run the `researcher` role of the role runner when web search is available:", investigation)
        self.assertIn("It uses `gpt-5.6-luna` at `high` through web search and verifies it from the session record.", investigation)
        self.assertIn("verify it under the spawned role verification section below", investigation)
        self.assertNotIn("rollout record", investigation)
        self.assertIn(
            "For Skill Builder, trial execution and other non-review participants use the host's upper model",
            normalized,
        )
        self.assertIn("Do not route a review role through `scout`", normalized)
        self.assertIn(
            "Private or authenticated remote access, including external tool work such as issue trackers and pull request "
            "services, goes to the `implementation` capability, and edits go to the capability worker a skill names; "
            "otherwise keep them in the main session.",
            normalized,
        )

    def test_조사는_내장_explorer_대신_scout를_쓴다(self):
        """Codex 조사는 Claude와 같은 이름의 scout만 쓰고, 쓸 수 없거나 역할 파일이 고정값을 바꾸면 메인 세션에서 조사한다."""
        # Given
        text = CODEX_AGENTS.read_text(encoding="utf-8")

        # When
        investigation = " ".join(text.split("## Investigation", 1)[1].split("## Skill workers", 1)[0].split())

        # Then
        self.assertIn(
            "Use the `scout` agent for bounded, read-only investigation whenever the session delegation rule selects it",
            investigation,
        )
        self.assertIn("Its bundled role file sets no model, so the spawn value applies.", investigation)
        self.assertIn(
            "If `scout` is unavailable, or its role file in the Codex agents directory sets another model or effort, "
            "investigate in the main session.",
            investigation,
        )
        self.assertIn("Treat results as leads.", investigation)
        scout = (REPO_ROOT / "standalone-agents/codex-scout.toml").read_text(encoding="utf-8")
        self.assertIn("one bounded local investigation", scout)
        self.assertIn("local-evidence research ticket", scout)
        self.assertNotIn("review persona", scout)
        self.assertNotIn("grading role", scout)


    def test_내장_에이전트는_모두_금지하고_네_플러그인_역할을_설치한다(self):
        """내장 역할은 금지하고 훅이 설치한 여섯 플러그인 역할을 보존한다."""
        # Given
        text = CODEX_AGENTS.read_text(encoding="utf-8")

        # When
        built_in = " ".join(text.split("## Built-in agents", 1)[1].split("## Investigation", 1)[0].split())

        # Then
        self.assertIn("Never use the built-in `default` or `explorer` agents.", built_in)
        self.assertIn("Always pass `agent_type`, because an omitted type runs `default`.", built_in)
        self.assertIn(
            "installs the plugin's `scout`, `worker`, `designer`, and `reviewer` roles in "
            "`~/.codex/agents/` when absent",
            built_in,
        )
        self.assertIn("so it also denies the built-in `worker` until the plugin role exists", built_in)

    def test_스킬_검토는_교차_계열_Claude와_reviewer_대체를_쓴다(self):
        """Codex 스킬 검토는 Claude를 먼저 쓰고 실패하면 reviewer로 대체하며, 결과만 반환 규칙은 공유 라우팅이 맡는다."""
        # Given
        text = CODEX_AGENTS.read_text(encoding="utf-8")

        # When
        skill_workers = " ".join(text.split("## Skill workers", 1)[1].split("## Implementation", 1)[0].split())

        # Then
        self.assertIn("one skill-assigned review role", skill_workers)
        self.assertIn("run the capability runner from the repository root with its role file and the assignment file", skill_workers)
        self.assertIn(
            "python3 <Source directory>/scripts/role_runner.py review --host codex --instructions <role file> "
            "--assignment <file> --result <file>",
            skill_workers,
        )
        self.assertIn("Accept the result file only on exit 0; the runner verifies the model from the host record.", skill_workers)
        self.assertIn(
            "On runner exit 3 or 4, spawn the plugin `reviewer` role with `gpt-6.1-sol` and `high` passed explicitly, "
            "or `xhigh` under the effort rule in [shared model routing](model-routing.md#keep-role-settings-fixed)",
            skill_workers,
        )
        self.assertIn("Verify it under the spawned role verification section below.", skill_workers)
        self.assertNotIn("claude -p", skill_workers)
        self.assertNotIn("modelUsage", skill_workers)
        self.assertNotIn("substitution", skill_workers)
        self.assertNotIn("findings only", skill_workers)
        self.assertNotIn("review round", skill_workers)
        self.assertIn("Send a local-evidence research ticket to `scout`", skill_workers)
        self.assertIn("bounded public research to the `researcher` runner role", skill_workers)
        self.assertIn("run a separate `codex exec` process with the model and effort that the skill pins", skill_workers)


    def test_Codex_대체는_역할_실행기_agent_모드로_가고_대체_쌍은_다시_띄우지_않는다(self):
        """Codex 대체 절은 agent 모드와 기능 실행기 명령을 알리고, 종료 코드 4에서 같은 역할을 다른 쌍으로 다시 띄우라는 옛 문구를 남기지 않는다."""
        # Given
        text = " ".join(CODEX_AGENTS.read_text(encoding="utf-8").split())

        # When
        fallback = text.split("## Fallback", 1)[1]

        # Then
        self.assertIn("`python3 <Source directory>/scripts/role_runner.py agent --name <name> --fallback`", fallback)
        self.assertIn(
            "`via: runner` runs `python3 <Source directory>/scripts/role_runner.py <capability> --host codex --fallback`",
            fallback,
        )
        self.assertIn("On runner exit 3 or 4, continue in the main session.", fallback)
        self.assertNotIn("declared fallback pair", text)
        self.assertNotIn("Respawn the role once", text)


if __name__ == "__main__":
    unittest.main()
