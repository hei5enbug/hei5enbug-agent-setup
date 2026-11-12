"""No hook or session instruction writes an Orca board status, worktree comment, or unread flag."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOVED_OPTION = "orca_status_" + "writes"
REMOVED_VARIABLE = "ORCA_STATUS_" + "WRITES"
MANIFESTS = (".claude-plugin/plugin.json", ".codex-plugin/plugin.json", "hooks/hooks.json", "hooks/claude-hooks.json",
             "hooks/codex-hooks.json")
STATUS_FLAG = re.compile(r"--workspace-status(?:\s+|=)(\S+)")


def tracked_text(*patterns: str) -> dict[str, str]:
    found = {}
    for pattern in patterns:
        for path in sorted(ROOT.glob(pattern)):
            if path.is_file():
                found[path.relative_to(ROOT).as_posix()] = path.read_text(encoding="utf-8")
    return found


class RemovedOptionTest(unittest.TestCase):
    def test_제거한_옵션_이름은_매니페스트_훅_스크립트_문서_어디에도_없다(self):
        """옵션이 다시 생기거나 문서에 남으면 훅이 Orca에 쓴다는 오해가 되살아난다."""
        # Given
        files = tracked_text(*MANIFESTS, "scripts/*.py", "instructions/**/*.md", "skills/**/*.md", "docs/**/*.md",
                             "README.md", "hooks/mod/*")

        # When
        found = sorted(
            name for name, text in files.items() if REMOVED_OPTION in text or REMOVED_VARIABLE in text
        )

        # Then
        self.assertTrue(files)
        self.assertEqual(found, [])

    def test_플러그인_매니페스트의_옵션_목록에_없다(self):
        """사용자 설정 목록에서도 사라져야 한다."""
        # Given
        options = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8")).get("userConfig", {})

        # When
        names = set(options)

        # Then
        self.assertTrue(names)
        self.assertNotIn(REMOVED_OPTION, names)


class NoCommentRequestTest(unittest.TestCase):
    def test_Orca_훅의_메시지는_코멘트를_쓰라고_하지_않는다(self):
        """completed 거부와 탭 제목 줄이 더 이상 쓰지 않는 코멘트를 요구하지 않는다."""
        # Given
        files = tracked_text("scripts/orca_status_hook.py", "scripts/orca_placement_hook.py")

        # When
        found = sorted(name for name, text in files.items() if "--comment" in text or "worktree comment" in text)

        # Then
        self.assertEqual(len(files), 2)
        self.assertEqual(found, [])

    def test_세션_지침은_완료_기록_말고는_상태_코멘트_읽지_않음_플래그를_쓰지_않는다(self):
        """instructions 아래 어디에도 --comment와 --unread가 없고, --workspace-status는 completed뿐이다."""
        # Given
        files = tracked_text("instructions/**/*.md")

        # When
        comment_or_unread = sorted(name for name, text in files.items() if "--comment" in text or "--unread" in text)
        statuses = {name: STATUS_FLAG.findall(text) for name, text in files.items() if "--workspace-status" in text}

        # Then
        self.assertTrue(files)
        self.assertEqual(comment_or_unread, [])
        self.assertEqual(statuses, {"instructions/orca-worktree-status.md": ["completed"]})


if __name__ == "__main__":
    unittest.main()
