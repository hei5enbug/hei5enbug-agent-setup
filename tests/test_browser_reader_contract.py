from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFINITION = REPO_ROOT / "agents" / "browser-reader.md"
REGISTRY = REPO_ROOT / "config" / "model-registry.json"
REGISTRY_NAME = "hei5enbug-agent-setup:browser-reader"
FORBIDDEN = {"Agent", "Edit", "Write", "NotebookEdit"}


def metadata() -> dict:
    match = re.match(r"^---\n(.*?)\n---\n", DEFINITION.read_text(encoding="utf-8"), re.DOTALL)
    if match is None:
        raise AssertionError("missing frontmatter")
    return yaml.safe_load(match[1])


class BrowserReaderContractTest(unittest.TestCase):
    def test_도구는_Bash와_Read뿐이고_쓰기와_하위_에이전트_도구는_금지한다(self):
        """browser-reader는 tools가 정확히 Bash와 Read이고 Agent, Edit, Write, NotebookEdit을 금지한다."""
        # Given
        declared = metadata()

        # When
        tools = {item.strip() for item in str(declared["tools"]).split(",")}
        disallowed = {item.strip() for item in str(declared["disallowedTools"]).split(",")}

        # Then
        self.assertEqual({"Bash", "Read"}, tools)
        self.assertEqual(FORBIDDEN, disallowed)

    def test_레지스트리_항목은_정의와_같은_모델과_effort를_읽기_접근으로_고정한다(self):
        """claude_agents의 browser-reader 항목은 정의 파일과 같은 model과 effort를 가지며 access가 read다."""
        # Given
        declared = metadata()
        entry = json.loads(REGISTRY.read_text(encoding="utf-8"))["claude_agents"][REGISTRY_NAME]

        # When
        pinned = (entry["model"], entry["effort"], entry["access"])

        # Then
        self.assertEqual((declared["model"], declared["effort"], "read"), pinned)


if __name__ == "__main__":
    unittest.main()
