from __future__ import annotations

import json
import os
import subprocess
from typing import Callable

import refresh_core as core
from refresh_core import RefreshError, run_json


class Orca:
    """Thin wrapper over the Orca CLI so the refresh logic can be tested without Orca."""

    def __init__(self) -> None:
        configured = os.environ.get("ORCA_CLI_COMMAND")
        if configured:
            self.command = [configured]
        elif os.environ.get("ORCA_DEV_REPO_ROOT"):
            self.command = [core.executable("orca-dev")]
        else:
            self.command = [core.executable("orca")]

    def call(self, *args: str, timeout: float = 30.0) -> dict:
        payload = run_json([*self.command, *args, "--json"], timeout=timeout)
        if not isinstance(payload, dict) or payload.get("ok") is False:
            raise RefreshError("orca_rejected", f"Orca rejected `{' '.join(args[:2])}`.")
        result = payload.get("result", payload)
        if not isinstance(result, dict):
            raise RefreshError("orca_invalid", "Orca returned an unsupported result.")
        return result

    def terminals(self) -> list[dict]:
        result = self.call("terminal", "list")
        terminals = result.get("terminals")
        if not isinstance(terminals, list):
            raise RefreshError("orca_invalid", "Orca returned an unsupported terminal list.")
        truncated = result.get("truncated")
        total_count = result.get("totalCount")
        if truncated is not None and not isinstance(truncated, bool):
            raise RefreshError("orca_invalid", "Orca returned unsupported terminal-list metadata.")
        if total_count is not None and (not isinstance(total_count, int) or isinstance(total_count, bool) or total_count < len(terminals)):
            raise RefreshError("orca_invalid", "Orca returned unsupported terminal-list metadata.")
        if truncated is True or (total_count is not None and total_count > len(terminals)):
            raise RefreshError("terminal_list_truncated", "Orca truncated the terminal list, so some sessions could be missed.")
        if any(not isinstance(item, dict) for item in terminals):
            raise RefreshError("orca_invalid", "Orca returned unsupported terminal data.")
        return terminals

    @staticmethod
    def wait_result(stdout: str) -> bool:
        """Read an idle wait: True when satisfied, False when it timed out, an error for anything else."""
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as error:
            raise RefreshError("invalid_json", "Orca returned unreadable JSON for a wait.") from error
        if isinstance(payload, dict) and payload.get("ok") is False:
            error = payload.get("error")
            if isinstance(error, dict) and error.get("code") == "timeout":
                return False
            raise RefreshError("orca_rejected", "Orca could not report whether the terminal is idle.")
        wait = payload.get("result", {}).get("wait") if isinstance(payload, dict) else None
        return isinstance(wait, dict) and wait.get("satisfied") is True

    def idle(self, handle: str) -> bool:
        result = core.run([*self.command, "terminal", "wait", "--terminal", handle, "--for", "tui-idle", "--timeout-ms", "500", "--json"], timeout=15, check=False)
        return self.wait_result(result.stdout)

    def wait_idle(self, handle: str, timeout_ms: float, track: Callable[[subprocess.Popen], None] | None = None) -> bool:
        """Block until Orca reports the agent idle, which acts as the completion callback; False when the wait times out."""
        argv = [*self.command, "terminal", "wait", "--terminal", handle, "--for", "tui-idle", "--timeout-ms", str(max(1, int(timeout_ms))), "--json"]
        try:
            process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        except OSError as error:
            raise RefreshError("orca_wait_failed", "Orca could not start an idle wait.") from error
        if track:
            track(process)
        try:
            stdout, _ = process.communicate(timeout=timeout_ms / 1000 + 30)
        except subprocess.TimeoutExpired as error:
            process.kill()
            process.communicate()
            raise RefreshError("orca_wait_hung", "Orca did not finish an idle wait.") from error
        return self.wait_result(stdout)

    def screen(self, handle: str) -> tuple[list[str], object]:
        terminal = self.call("terminal", "read", "--terminal", handle, "--screen").get("terminal")
        if not isinstance(terminal, dict):
            raise RefreshError("orca_invalid", "Orca returned an unsupported screen.")
        tail = terminal.get("tail")
        lines = [line for line in tail if isinstance(line, str)] if isinstance(tail, list) else []
        return lines, terminal.get("draft")

    def draft(self, handle: str) -> object:
        terminal = self.call("terminal", "read", "--terminal", handle, "--limit", "1").get("terminal")
        return terminal.get("draft") if isinstance(terminal, dict) else None

    def keys(self, handle: str, text: str) -> None:
        send = self.call("terminal", "send", "--terminal", handle, "--text", text).get("send")
        if not isinstance(send, dict) or send.get("accepted") is not True:
            raise RefreshError("input_not_accepted", "Orca did not accept the keystroke.")

    def close(self, handle: str) -> None:
        self.call("terminal", "close", "--terminal", handle)

    def send(self, handle: str, text: str) -> None:
        send = self.call("terminal", "send", "--terminal", handle, "--text", text, "--enter").get("send")
        if not isinstance(send, dict) or send.get("accepted") is not True:
            raise RefreshError("input_not_accepted", "Orca did not accept the command.")
