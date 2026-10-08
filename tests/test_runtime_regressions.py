from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SPEC = importlib.util.spec_from_file_location("session_context_regression", SCRIPTS / "session_context.py")
context = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(context)


class ProvisioningRegressionTest(unittest.TestCase):
    def test_concurrent_scout_creation_keeps_user_file(self):
        """설정 파일이 확인 직후 생성되어도 사용자 내용을 덮어쓰지 않는다."""
        # Given
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "standalone-agents" / "codex-scout.toml"
            source.parent.mkdir()
            source.write_text('name = "bundled"')
            home = root / "home"
            target = home / "agents" / "scout.toml"
            target.parent.mkdir(parents=True)
            real_read = Path.read_text

            def racing_read(path, *args, **kwargs):
                if path == source:
                    target.write_text('name = "user"')
                return real_read(path, *args, **kwargs)

            # When
            with (
                patch.dict(context.os.environ, {"CODEX_HOME": str(home)}),
                patch.object(Path, "read_text", racing_read),
            ):
                context.provision_codex_agents(root)
            # Then
            self.assertEqual(target.read_text(), 'name = "user"')

    def test_concurrent_reviewer_creation_keeps_user_file(self):
        """Codex reviewer 설정을 읽는 도중 사용자가 파일을 만들면 그 파일을 덮어쓰지 않는다."""
        # Given
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "standalone-agents" / "codex-reviewer.toml"
            source.parent.mkdir()
            source.write_text('name = "bundled"')
            home = root / "home"
            target = home / "agents" / "reviewer.toml"
            target.parent.mkdir(parents=True)
            real_read = Path.read_text

            def racing_read(path, *args, **kwargs):
                if path == source:
                    target.write_text('name = "user"')
                return real_read(path, *args, **kwargs)

            # When
            with patch.dict(context.os.environ, {"CODEX_HOME": str(home)}), patch.object(Path, "read_text", racing_read):
                context.provision_codex_agents(root)

            # Then
            self.assertEqual(target.read_text(), 'name = "user"')


if __name__ == "__main__":
    unittest.main()
