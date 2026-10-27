"""Regression checks for known copies across runtime and repository instruction files.

`instructions/session/core.md` and `instructions/session/common.md` ship to every plugin user and load
on every main session; subagents load only the core. `AGENTS.md` governs development of this repository
only. These checks reject verbatim copies of the declared core and common rules. Semantically equivalent restatements remain a review concern.
"""

from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CORE = REPO_ROOT / "instructions/session/core.md"
COMMON = REPO_ROOT / "instructions/session/common.md"
ROUTING = REPO_ROOT / "instructions/model-routing.md"
VALIDATION = REPO_ROOT / "instructions/independent-model-validation.md"
AGENTS = REPO_ROOT / "AGENTS.md"
CLAUDE_AGENTS = REPO_ROOT / "instructions/claude-agents.md"
CODEX_AGENTS = REPO_ROOT / "instructions/codex-agents.md"
DELEGATION = REPO_ROOT / "instructions/implementation-delegation.md"
HOST_SESSION_FILES = (
    REPO_ROOT / "instructions/session/claude-code.md",
    REPO_ROOT / "instructions/session/codex.md",
)

# Verbatim rules every agent receives through the core session instructions.
CORE_OWNED = (
    (
        "Use English files as executable instruction sources. Korean `.ko.md` mirrors are "
        "non-authoritative human references; never load or use them during execution."
    ),
    (
        "Prefer `rg` for text and symbol search and `fd` for file discovery. Use `ast-grep` only when "
        "structural matching is clearly needed."
    ),
    (
        "Unless the approval guard decides, ask before each irreversible action and once per session before other "
        "outward writes, including production. Never reconfirm a requested or required write, even after "
        "compaction. Name the write in one line. Never expose secrets."
    ),
    "Ask nothing before local, reversible steps in scope; offer no unrequested commit, push, tag, release, publish, "
    "or install.",
    "Before writing or editing any documentation file, read [documentation rules](../documentation.md).",
)

# Verbatim rules only the main session receives through the common session instructions.
COMMON_OWNED = (
    (
        "Keep problem definition, planning decisions, trade-offs, complex debugging, and acceptance in the main "
        "session. A skill may delegate drafting, including a design document, to the capability worker it names; "
        "the main session approves the decisions and accepts the result."
    ),
    (
        "When the target is a known symbol, file path, glob, or literal string, search directly in the main "
        "session."
    ),
)

# Scheduling policy the shared implementation delegation reference owns outright.
EXECUTION_OWNED = (
    "min(6 - active implementation workers, host slots remaining, ready independent tasks)",
    "Disjoint files alone do not prove independence.",
    "Queue any excess task, such as a seventh,",
    "Fallback never bypasses a missing user decision, permission restriction, or failed acceptance check.",
)
LEGACY_SCHEDULING = ("Run at most 6",)

# Each canonical sentence lives in exactly its owner files; the other instruction files refer to it.
SENTENCE_OWNERS = (
    ("대체 보고", "Report the limitation once.", {COMMON}),
    ("준비 확인 조건", "use a readiness-only assignment only if the host can send a follow-up", {DELEGATION}),
    ("준비 확인 할당", "make no edit and report readiness", {DELEGATION}),
    ("준비 확인 이어 보내기 불가", "skip this path and use the session fallback", {DELEGATION}),
    ("준비 확인 반복 금지", "do not repeat readiness calls", {DELEGATION}),
    ("worker 자기 보고", "unsubstantiated self-report", {DELEGATION}),
    ("결과만 반환", "returns findings only", {ROUTING, VALIDATION}),
    ("재검토 금지", "Do not run another review round.", {ROUTING}),
    ("메인 한 번 검토", "reviews the same material once", {ROUTING}),
    ("호출별 모델 지정 금지", "Never pass a per-invocation model", {CLAUDE_AGENTS}),
)


def runtime_documents() -> list[Path]:
    roots = (REPO_ROOT / "instructions", REPO_ROOT / "agents", REPO_ROOT / "skills")
    return sorted(
        path
        for root in roots
        for path in root.rglob("*.md")
        if not path.name.endswith(".ko.md") and path != DELEGATION
    )


def normalized_text(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


class CommonOwnsItsRulesTest(unittest.TestCase):
    def test_common_still_states_every_owned_rule(self):
        text = normalized_text(COMMON)
        for rule in COMMON_OWNED:
            with self.subTest(rule=rule):
                self.assertIn(rule, text)

    def test_core_still_states_every_owned_rule(self):
        text = normalized_text(CORE)
        for rule in CORE_OWNED:
            with self.subTest(rule=rule):
                self.assertIn(rule, text)

    def test_common_does_not_repeat_core_rules(self):
        text = normalized_text(COMMON)
        for rule in CORE_OWNED:
            with self.subTest(rule=rule):
                self.assertNotIn(rule, text)


class AgentsFileStaysADeltaTest(unittest.TestCase):
    def test_repository_and_host_deltas_do_not_repeat_verbatim_common_rules(self):
        for path in (AGENTS, CLAUDE_AGENTS, CODEX_AGENTS):
            text = normalized_text(path)
            for rule in COMMON_OWNED + CORE_OWNED:
                with self.subTest(path=path.relative_to(REPO_ROOT), rule=rule):
                    self.assertNotIn(rule, text)

    def test_agents_does_not_duplicate_the_host_agent_pointer(self):
        """The host session files already route to the right agent rules."""
        text = AGENTS.read_text(encoding="utf-8")
        for pointer in ("instructions/claude-agents.md", "instructions/codex-agents.md"):
            with self.subTest(pointer=pointer):
                self.assertNotIn(pointer, text)
        for path in HOST_SESSION_FILES:
            with self.subTest(path=path.relative_to(REPO_ROOT)):
                self.assertIn("agent rules", path.read_text(encoding="utf-8"))

    def test_agents_keeps_its_own_repository_rules(self):
        text = AGENTS.read_text(encoding="utf-8")
        for rule in (
            "Maintain a complete, meaning-equivalent Korean",
            "Do not duplicate code, schemas, test fixtures",
            "skills/skill-builder/SKILL.md",
            "Install only a tagged release",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, text)

    def test_agents_points_at_the_session_instructions_for_the_shared_rules(self):
        self.assertIn("instructions/session/common.md", AGENTS.read_text(encoding="utf-8"))


class HostAgentFilesStayHostSpecificTest(unittest.TestCase):
    def test_host_agent_files_keep_their_host_specific_rules(self):
        self.assertIn("`hei5enbug-agent-setup:scout`", CLAUDE_AGENTS.read_text(encoding="utf-8"))
        self.assertIn("Use the `scout` agent", CODEX_AGENTS.read_text(encoding="utf-8"))


class DelegationReferenceOwnsSchedulingTest(unittest.TestCase):
    def test_공유_위임_참조만_일정_정책을_가진다(self):
        """worker 일정 정책은 공유 위임 참조에만 있고 다른 실행 지침은 이를 복사하지 않는다."""
        # Given
        delegation = normalized_text(DELEGATION)
        documents = runtime_documents()

        # When
        copies = [
            (path.relative_to(REPO_ROOT), rule)
            for path in documents
            for rule in EXECUTION_OWNED + LEGACY_SCHEDULING
            if rule in normalized_text(path)
        ]

        # Then
        for rule in EXECUTION_OWNED:
            self.assertIn(rule, delegation)
        self.assertIn(CLAUDE_AGENTS, documents)
        self.assertIn(CODEX_AGENTS, documents)
        self.assertEqual(copies, [])


class CanonicalSentencesHaveOneOwnerTest(unittest.TestCase):
    def test_정리한_규칙_문장은_소유_파일에만_있다(self):
        """대체 보고, 준비 확인, 결과만 반환, 호출별 모델 지정 금지 문장은 정한 소유 파일 밖에 반복되지 않는다."""
        # Given
        texts = {
            path: normalized_text(path)
            for root in (REPO_ROOT / "instructions", REPO_ROOT / "agents")
            for path in root.rglob("*.md")
            if not path.name.endswith(".ko.md")
        }

        for name, sentence, owners in SENTENCE_OWNERS:
            with self.subTest(rule=name):
                # When
                holders = {path for path, text in texts.items() if sentence in text}

                # Then
                self.assertEqual(holders, owners)

    def test_호스트_지침은_준비_확인_절차를_복사하지_않고_구현_위임_규칙을_가리킨다(self):
        """Claude Code와 Codex 지침은 준비 확인 경로를 위임 규칙으로 가리키며 두 단계 절차를 다시 쓰지 않는다."""
        # Given
        hosts = (CLAUDE_AGENTS, CODEX_AGENTS)

        for path in hosts:
            with self.subTest(path=path.relative_to(REPO_ROOT)):
                # When
                text = normalized_text(path)

                # Then
                self.assertIn("readiness-only path in implementation delegation", text)
                self.assertNotIn("start each worker with a readiness-only assignment", text)
                self.assertNotIn("skip the two-phase path", text)


if __name__ == "__main__":
    unittest.main()
