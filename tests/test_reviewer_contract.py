from __future__ import annotations

import json
import re
import tomllib
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_ROLE = REPO_ROOT / "agents/reviewer.md"
CODEX_ROLE = REPO_ROOT / "standalone-agents/codex-reviewer.toml"


def split_definition(path: Path) -> tuple[dict, str]:
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", path.read_text(encoding="utf-8"), re.DOTALL)
    if match is None:
        raise AssertionError(f"missing frontmatter: {path}")
    return yaml.safe_load(match[1]), match[2]


class ReviewerContractTest(unittest.TestCase):
    def test_Claude_reviewer는_고정_모델과_읽기전용_도구를_선언한다(self):
        """Claude reviewer는 지정된 Opus 모델과 high, 읽기 전용 도구 제한을 선언한다."""
        # Given
        metadata, body = split_definition(CLAUDE_ROLE)

        # When
        allowed = {item.strip() for item in metadata["tools"].split(",")}
        denied = {item.strip() for item in metadata["disallowedTools"].split(",")}
        normalized_body = " ".join(body.split())

        # Then
        self.assertEqual(metadata["name"], "reviewer")
        self.assertEqual(
            metadata["description"],
            "Read-only fallback reviewer for one skill-assigned review persona, grading, comparison, or analysis "
            "role when the configured review runner is unavailable.",
        )
        self.assertEqual(allowed, {"Read", "Grep", "Glob", "Bash"})
        self.assertEqual(denied, {"Agent", "Edit", "Write", "NotebookEdit"})
        self.assertEqual(metadata["model"], "claude-opus-5-5")
        self.assertEqual(metadata["effort"], "high")
        for phrase in (
            "Base every finding or grade on quoted evidence.",
            "Return the assigned review result to the coordinating session.",
            "Never modify files, branches, or worktrees.",
            "Never run build, test, install, or network commands.",
        ):
            self.assertIn(phrase, normalized_body)

    def test_Codex_reviewer는_모델을_지정하지_않고_읽기전용_sandbox를_쓴다(self):
        """Codex reviewer 역할은 xhigh와 read-only sandbox를 쓰고 모델 키를 두지 않는다."""
        # Given
        role = tomllib.loads(CODEX_ROLE.read_text(encoding="utf-8"))

        # When
        instructions = " ".join(role["developer_instructions"].split())

        # Then
        self.assertEqual(role["name"], "reviewer")
        self.assertIn("Returns its quoted review result", role["description"])
        self.assertEqual(role["model_reasoning_effort"], "xhigh")
        self.assertEqual(role["sandbox_mode"], "read-only")
        self.assertNotIn("model", role)
        self.assertIn("Base every finding or grade on quoted evidence.", instructions)
        self.assertIn("Return the assigned review result to the coordinating session.", instructions)
        self.assertIn("Never modify files, branches, or worktrees.", instructions)
        self.assertIn("Never run build, test, install, or network commands.", instructions)

    def test_manifest와_한국어_미러는_reviewer를_등록한다(self):
        """Claude manifest는 영어 reviewer 정의를 한 번 등록하고 한국어 미러는 비권위로 표시한다."""
        # Given
        manifest = json.loads((REPO_ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
        mirror = (REPO_ROOT / "docs/ko/agents/reviewer.ko.md").read_text(encoding="utf-8")

        # When
        agents = manifest["agents"]

        # Then
        self.assertEqual(agents.count("./agents/reviewer.md"), 1)
        self.assertEqual(len(agents), 5)
        self.assertIn("reviewer", manifest["userConfig"]["role_pinning"]["description"])
        self.assertIn("영어 원본: [reviewer.md](../../../agents/reviewer.md)", mirror)
        self.assertIn("비권위", mirror)

    def test_scout는_로컬_조사만_맡는다(self):
        """Claude와 Codex scout는 로컬 조사 티켓을 포함해 조사만 맡고 검토나 채점은 맡지 않는다."""
        # Given
        claude_scout = (REPO_ROOT / "agents/scout.md").read_text(encoding="utf-8")
        codex_scout = (REPO_ROOT / "standalone-agents/codex-scout.toml").read_text(encoding="utf-8")

        # When
        combined = f"{claude_scout}\n{codex_scout}"

        # Then
        self.assertIn("one bounded local investigation", combined)
        self.assertIn("local-evidence research ticket", combined)
        self.assertNotIn("review persona", combined)
        self.assertNotIn("grading role", combined)

    def test_skill_review는_검토_모델_설정과_reviewer_대체_후_메인_검토를_쓴다(self):
        """Claude 스킬 검토는 Review model 줄로 reviewer 역할을 실행하고 실패하면 reviewer로 대체하며, 메인 세션이 한 번 판단한다."""
        # Given
        claude = (REPO_ROOT / "instructions/claude-agents.md").read_text(encoding="utf-8")
        codex = (REPO_ROOT / "instructions/codex-agents.md").read_text(encoding="utf-8")
        routing = (REPO_ROOT / "instructions/model-routing.md").read_text(encoding="utf-8")

        # When
        claude_review = " ".join(claude.split("## Skill workers", 1)[1].split("## Implementation", 1)[0].split())
        codex_review = " ".join(codex.split("## Skill workers", 1)[1].split("## Implementation", 1)[0].split())
        claude_table = " ".join(claude.split("## Role runner", 1)[1].split("## Investigation", 1)[0].split())
        routing_text = " ".join(routing.split())

        # Then
        self.assertIn('with `--model` set to the model in the session line "Review model"', claude_review)
        self.assertIn("| `reviewer` for a skill review role | `hei5enbug-agent-setup:reviewer` |", claude_table)
        self.assertIn(
            "`role_runner.py reviewer` with the `review_model` setting (default `gpt-6-astra`), `xhigh`; "
            "fallback `reviewer` with `claude-opus-5-5`, `high`",
            routing_text,
        )
        self.assertIn("fallback `reviewer` with `gpt-6.1-sol`, `xhigh`", routing_text)
        self.assertIn("Skill Builder trial execution and other non-review participants", routing_text)
        self.assertIn("role_runner.py review --host codex --instructions <role file>", codex_review)
        self.assertNotIn("modelUsage", codex_review)
        self.assertIn("On runner exit 3 or 4, spawn the plugin `reviewer` role", codex_review)
        self.assertIn("with `gpt-6.1-sol` and `xhigh` passed explicitly", codex_review)
        self.assertIn("The reviewer returns findings only.", routing_text)
        self.assertIn("reviews the same material once and makes the final decision", routing_text)
        self.assertEqual(routing_text.count("Do not run another review round."), 1)


if __name__ == "__main__":
    unittest.main()
