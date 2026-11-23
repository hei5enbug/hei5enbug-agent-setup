"""The Codex implementation worker row of the Orca session start model rule follows the codex_worker_model setting."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import orca_session_model  # noqa: E402

REGISTRY = json.loads((REPO_ROOT / "config" / "model-registry.json").read_text(encoding="utf-8"))
MODEL_VARIABLE = "HEI5ENBUG_CODEX_WORKER_MODEL"
EFFORT_VARIABLE = "HEI5ENBUG_CODEX_WORKER_EFFORT"


class CodexWorkerRowTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        environment = {key: value for key, value in os.environ.items() if not key.startswith("HEI5ENBUG_CODEX_")}
        environment["CLAUDE_CONFIG_DIR"] = directory.name
        patcher = mock.patch.dict(os.environ, environment, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def row(self, **settings: str) -> str:
        with mock.patch.dict(os.environ, settings):
            return orca_session_model.codex_worker_text(REGISTRY)

    def test_auto와_Sonnet_경로는_난이도별_모델을_알리고_고정_모델은_그_모델만_알린다(self):
        """auto와 claude-sonnet-5-5는 gpt-6-luna와 gpt-6.2-sol을 난이도 규칙으로, gpt-6.1-terra는 xhigh와 함께 그것만 적는다."""
        # Given
        luna, sol = REGISTRY["runner"]["worker_models"]

        # When
        default = self.row()
        sonnet = self.row(**{MODEL_VARIABLE: "claude-sonnet-5-5"})
        terra = self.row(**{MODEL_VARIABLE: "gpt-6.1-terra", EFFORT_VARIABLE: "xhigh"})

        # Then
        for text in (default, sonnet):
            self.assertIn(f"`{luna}` for easy work", text)
            self.assertIn(f"`{sol}` for hard or unsure work", text)
        self.assertIn("`gpt-6.1-terra` at `xhigh`", terra)
        self.assertNotIn(luna, terra)

    def test_시작_차단_사유는_Codex_고용_worker_행과_다른_세션_행의_gpt_sol_핀을_함께_적는다(self):
        """사유는 pin을 참조해 다른 세션 행에 gpt-sol 핀을 적고, 작업자 행에는 설정이 정한 모델을 적는다."""
        # Given
        pin = REGISTRY["pins"]["gpt-sol"]

        # When
        reason = orca_session_model.denial([None], {"transcript_path": None})

        # Then
        self.assertIn("names no model", reason)
        self.assertIn(f"`{pin}` at `high` in Codex", reason)
        self.assertIn("for easy work", reason)


if __name__ == "__main__":
    unittest.main()
