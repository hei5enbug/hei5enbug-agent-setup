"""요청 예산의 등록: 옵션 기본값은 커밋한 분포에서 나오고, 훅은 두 호스트의 이벤트에 등록되며, 지시문은 고정된 6 대신 플러그인이 알리는 한도를 가리킨다."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = "request_budget_hook.py"
EVENTS = {"PreToolUse", "PostToolUse", "PostToolUseFailure", "UserPromptSubmit", "SubagentStop", "Stop"}


def registered_events(path: Path) -> dict[str, list[str]]:
    hooks = json.loads(path.read_text(encoding="utf-8"))["hooks"]
    found: dict[str, list[str]] = {}
    for event, groups in hooks.items():
        for group in groups:
            if any(SCRIPT in hook["command"] for hook in group["hooks"]):
                found.setdefault(event, []).append(group.get("matcher", ""))
    return found


class RequestBudgetRegistrationTest(unittest.TestCase):
    def test_옵션_기본값은_커밋한_분포의_기본_한도와_같다(self):
        """request_run_cap 과 request_retry_cap 의 기본값은 config/request-distribution.json 의 값이다."""
        # given
        record = json.loads((REPO_ROOT / "config" / "request-distribution.json").read_text(encoding="utf-8"))
        manifest = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["userConfig"]

        # when
        defaults = (manifest["request_run_cap"]["default"], manifest["request_retry_cap"]["default"])

        # then
        self.assertEqual(defaults, (str(record["run_cap_default"]), str(record["retry_cap_default"])))

    def test_훅은_공용_훅_파일에서_에이전트_도구_이벤트_다섯에_등록된다(self):
        """hooks/hooks.json 은 UserPromptSubmit, SubagentStop, Stop 에 매처 없이, 나머지 셋에는 Agent|Task 매처로 훅을 등록한다."""
        # given / when
        found = registered_events(REPO_ROOT / "hooks" / "hooks.json")

        # then
        self.assertEqual(set(found), EVENTS)
        self.assertEqual(found["PreToolUse"], ["Agent|Task"])
        self.assertEqual(found["UserPromptSubmit"], [""])
        self.assertEqual(found["Stop"], [""])

    def test_지시문은_고정된_여섯_대신_플러그인이_알리는_한도를_가리킨다(self):
        """위임, 실행, 빠른 모드 지시문은 플러그인이 알리는 한도를 쓰고 6 - 식이나 여섯 병렬을 남기지 않는다."""
        # given
        delegation = (REPO_ROOT / "instructions" / "implementation-delegation.md").read_text(encoding="utf-8")
        agents = (REPO_ROOT / "instructions" / "claude-agents.md").read_text(encoding="utf-8")
        fast = (REPO_ROOT / "instructions" / "fast-mode.md").read_text(encoding="utf-8")

        # when / then
        self.assertIn("the limit the plugin reports", delegation)
        self.assertNotIn("6 - active", delegation)
        self.assertIn("the limit the plugin reports", agents)
        self.assertNotIn("up to six in parallel", agents)
        self.assertIn("the limit the plugin reports", fast)
        self.assertNotIn("nproc", fast)


if __name__ == "__main__":
    unittest.main()
