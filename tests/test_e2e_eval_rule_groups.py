"""Tests for listing the rule groups of the always-loaded session instructions with their bytes and `remove` entries."""

from __future__ import annotations

import io
import json
import sys
import unittest
from argparse import Namespace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals/e2e"))

from harness import markdown_parts, rule_groups as rg, rules_cli  # noqa: E402
from harness.config import HarnessConfig  # noqa: E402

CORE = "instructions/session/core.md"
CLAUDE = "instructions/session/claude-code.md"
CODEX = "instructions/session/codex.md"
SEEDED = {
    CORE: "# Core\n\nIntro paragraph for everyone.\n\n- Before writing any code, read the guide.\n- Before writing any text, read the guide.\n",
    CLAUDE: "# Claude\n\n- Claude only rule applies.\n",
    CODEX: "# Codex\n\n- Codex only rule applies here.\n",
}


class RuleGroupsTest(unittest.TestCase):
    def test_불릿과_문단마다_그룹이_되고_첫_단어는_파일_안에서_유일하며_크기는_줄_바이트다(self):
        """같은 세 단어로 시작하는 두 불릿은 더 길게 갈라지고 크기는 줄과 줄바꿈의 바이트다."""
        # given
        lines = SEEDED[CORE].split("\n")

        # when
        groups = [group for group in rg.list_groups(SEEDED) if group.file == CORE]

        # then
        self.assertEqual([group.start for group in groups],
                         ["Intro paragraph for", "Before writing any code,", "Before writing any text,"])
        self.assertEqual([group.size for group in groups], [len(lines[index].encode()) + 1 for index in (2, 4, 5)])

    def test_호스트별_합계는_공통_파일과_그_호스트_파일만_더하고_작업자는_core만_더한다(self):
        """claude 합계에는 codex 파일 그룹이 없고 codex 합계에는 claude 파일 그룹이 없다."""
        # given
        groups = rg.list_groups(SEEDED)
        sizes = {name: sum(g.size for g in groups if g.file == name) for name in (CORE, CLAUDE, CODEX)}

        # when
        totals = rg.host_totals(groups)

        # then
        self.assertEqual(totals, {"claude": sizes[CORE] + sizes[CLAUDE], "codex": sizes[CORE] + sizes[CODEX], "worker": sizes[CORE]})

    def test_저장소_세션_지침의_모든_그룹은_자기_remove_항목이_정확히_그_부분_하나만_가리킨다(self):
        """모든 그룹의 `remove` 항목이 한 부분에만 일치해야 제거 변형이 모호함 없이 내보내진다."""
        # given
        texts = rg.read_texts(REPO_ROOT)
        groups = rg.list_groups(texts)

        # when
        spans = {group.slug: markdown_parts.span_of(texts[group.file], start=group.removal["start"], label=group.file)
                 for group in groups}

        # then
        self.assertEqual(set(texts), set(rg.SESSION_FILES))
        self.assertEqual(len(spans), len(groups), "two groups share a slug")
        for group in groups:
            first, stop = spans[group.slug]
            self.assertEqual(len("\n".join(texts[group.file].split("\n")[first:stop]).encode()) + 1, group.size)


class RulesCommandTest(unittest.TestCase):
    def run_command(self, **overrides: object) -> str:
        cfg = HarnessConfig(repo_root=REPO_ROOT)
        out = io.StringIO()
        rules_cli.run(Namespace(**{"json": False, "min_bytes": 0, **overrides}), cfg, out)
        return out.getvalue()

    def test_표는_가장_큰_그룹부터_바이트와_로드하는_호스트를_보여준다(self):
        """첫 줄이 합계이고 그 아래 줄이 바이트 내림차순이며 core 그룹에는 worker 표시가 붙는다."""
        # given / when
        lines = self.run_command().splitlines()
        sizes = [int(line.split()[0]) for line in lines[1:]]

        # then
        self.assertIn("rule groups; file bytes per context: claude", lines[0])
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        self.assertTrue(any("[claude+codex+worker]" in line for line in lines))

    def test_JSON은_총계와_그룹별_remove_항목을_내고_min_bytes_아래는_뺀다(self):
        """각 행이 `remove` 항목을 가지며 `--min-bytes` 아래의 그룹은 목록에서 빠진다."""
        # given / when
        data = json.loads(self.run_command(json=True, min_bytes=200))

        # then
        self.assertEqual(set(data["totals"]), {"claude", "codex", "worker"})
        self.assertTrue(data["groups"])
        self.assertTrue(all(row["bytes"] >= 200 and set(row["remove"]) == {"file", "start"} for row in data["groups"]))


if __name__ == "__main__":
    unittest.main()
