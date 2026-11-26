from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

import test_orca_plugin_refresh  # noqa: F401  (puts the skill scripts on the import path)

import refresh_core
import refresh_install
import refresh_plugins

PLUGIN_LIST_TIMEOUT = 180


class RecordingRunner:
    """A fake subprocess.run that records each call's argv and timeout and answers with an empty plugin list."""

    def __init__(self, raises: Exception | None = None) -> None:
        self.calls: list[tuple[list[str], float | None]] = []
        self.raises = raises

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs.get("timeout")))
        if self.raises is not None:
            raise self.raises
        stdout = "[]" if argv[0].endswith("claude") else '{"installed": []}'
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    def list_timeouts(self, host: str) -> list[float | None]:
        return [timeout for argv, timeout in self.calls
                if argv[0].endswith(host) and argv[1:] == ["plugin", "list", "--json"]]


def fake_executable(name: str) -> str:
    return f"/x/{name}"


class PluginListTimeoutTest(unittest.TestCase):
    def test_갱신_경로의_plugin_list_호출은_두_호스트_모두_180초_제한을_쓴다(self):
        # given
        runner = RecordingRunner()
        context: dict = {}
        # when
        with patch.object(refresh_core, "executable", fake_executable), patch.object(refresh_core.subprocess, "run", runner):
            for host in refresh_core.HOSTS:
                with self.assertRaises(refresh_core.RefreshError):
                    refresh_install.installed(host)
                refresh_plugins.describe_plugin(host, "demo@example", context)
        # then
        for host in refresh_core.HOSTS:
            self.assertEqual([PLUGIN_LIST_TIMEOUT, PLUGIN_LIST_TIMEOUT], runner.list_timeouts(host), host)


class CommandTimeoutMessageTest(unittest.TestCase):
    def test_codex_plugin_list가_시간을_넘기면_명령과_제한_시간을_밝힌_오류를_낸다(self):
        # given
        runner = RecordingRunner(raises=subprocess.TimeoutExpired(["/x/codex"], PLUGIN_LIST_TIMEOUT))
        # when
        with patch.object(refresh_core, "executable", fake_executable), patch.object(refresh_core.subprocess, "run", runner):
            with self.assertRaises(refresh_core.RefreshError) as caught:
                refresh_install.installed("codex")
        # then
        self.assertEqual("command_timeout", caught.exception.code)
        self.assertEqual("codex plugin list did not finish in 180 seconds.", caught.exception.message)

    def test_하위_명령은_옵션_앞의_단어_세_개까지만_이름에_넣는다(self):
        # given
        runner = RecordingRunner(raises=subprocess.TimeoutExpired(["/x/codex"], 5))
        argv = ["/x/codex", "plugin", "marketplace", "upgrade", "demo", "--json"]
        expected = "codex plugin marketplace upgrade did not finish in 5 seconds."
        # when
        with patch.object(refresh_core.subprocess, "run", runner):
            with self.assertRaises(refresh_core.RefreshError) as caught:
                refresh_core.run(argv, timeout=5)
        # then
        self.assertEqual(expected, caught.exception.message)


if __name__ == "__main__":
    unittest.main()
