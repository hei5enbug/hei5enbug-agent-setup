"""Regression checks for known copies across runtime and repository instruction files.

`instructions/session/common.md` ships to every plugin user and loads on every session. `AGENTS.md`
governs development of this repository only. These checks reject verbatim copies of the declared common
rules. Semantically equivalent restatements remain a review concern.
"""

from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
COMMON = REPO_ROOT / "instructions/session/common.md"
AGENTS = REPO_ROOT / "AGENTS.md"
CLAUDE_AGENTS = REPO_ROOT / "instructions/claude-agents.md"
CODEX_AGENTS = REPO_ROOT / "instructions/codex-agents.md"
HOST_SESSION_FILES = (
    REPO_ROOT / "instructions/session/claude-code.md",
    REPO_ROOT / "instructions/session/codex.md",
)

# Verbatim rules the always-loaded session instructions own outright.
COMMON_OWNED = (
    (
        "Use English files as executable instruction sources. Korean `.ko.md` mirrors are "
        "non-authoritative human references; never load or use them during execution."
    ),
    (
        "Keep planning, architecture, trade-offs, problem definition, complex debugging, review, and key "
        "decisions in the main session. Never delegate high-level reasoning."
    ),
    (
        "Prefer `rg` for text and symbol search and `fd` for file discovery. Use `ast-grep` only when "
        "structural matching is clearly needed."
    ),
    (
        "When the target is a known symbol, file path, glob, or literal string, search directly in the main "
        "session. Delegate investigation only when at least two targets share no file and each needs more "
        "than one file read."
    ),
    (
        "Before writing or editing any documentation file, read [documentation "
        "rules](../documentation.md)."
    ),
)


def normalized_text(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


class CommonOwnsItsRulesTest(unittest.TestCase):
    def test_common_still_states_every_owned_rule(self):
        text = normalized_text(COMMON)
        for rule in COMMON_OWNED:
            with self.subTest(rule=rule):
                self.assertIn(rule, text)


class AgentsFileStaysADeltaTest(unittest.TestCase):
    def test_repository_and_host_deltas_do_not_repeat_verbatim_common_rules(self):
        for path in (AGENTS, CLAUDE_AGENTS, CODEX_AGENTS):
            text = normalized_text(path)
            for rule in COMMON_OWNED:
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
            "Use a cachebuster for local reinstalls",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, text)

    def test_agents_points_at_the_session_instructions_for_the_shared_rules(self):
        self.assertIn("instructions/session/common.md", AGENTS.read_text(encoding="utf-8"))


class HostAgentFilesStayHostSpecificTest(unittest.TestCase):
    def test_host_agent_files_keep_their_host_specific_rules(self):
        self.assertIn("`hei5enbug-agent-setup:scout`", CLAUDE_AGENTS.read_text(encoding="utf-8"))
        self.assertIn("`explorer`", CODEX_AGENTS.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
