from __future__ import annotations

import json
import os
import subprocess
from typing import Callable

import refresh_core as core
from refresh_core import RefreshError, run_json

INBOX_LIMIT = 100000
MAIL_PAGE_LIMIT = 100


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

    def orchestration(self, *args: str) -> dict | None:
        """One read-only orchestration call; None when this Orca does not know the `orchestration` command at all."""
        result = core.run([*self.command, "orchestration", *args, "--json"], timeout=15, check=False)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RefreshError("invalid_json", "Orca returned unreadable JSON for an orchestration call.") from error
        if not isinstance(payload, dict):
            raise RefreshError("orca_invalid", "Orca returned an unsupported orchestration result.")
        if payload.get("ok") is False:
            error = payload.get("error")
            if isinstance(error, dict) and error.get("code") == "invalid_argument" and str(error.get("message", "")).startswith("Unknown command"):
                return None
            code = error.get("code") if isinstance(error, dict) and isinstance(error.get("code"), str) else "orca_rejected"
            raise RefreshError(code, f"Orca rejected `orchestration {args[0]}`.")
        result_body = payload.get("result")
        if payload.get("ok") is not True or not isinstance(result_body, dict):
            raise RefreshError("orca_invalid", "Orca returned an unsupported orchestration result.")
        return result_body

    def paged(self, key: str, *args: str) -> list[dict]:
        """Every row of a paged orchestration listing, following `nextCursor` until it is absent."""
        rows: list[dict] = []
        cursor: str | None = None
        for _ in range(MAIL_PAGE_LIMIT):
            page = self.orchestration(*args, *(["--cursor", cursor] if cursor else []))
            items = page.get(key) if page is not None else None
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise RefreshError("orca_invalid", f"Orca returned an unsupported {key} list.")
            rows.extend(items)
            cursor = page.get("nextCursor")
            if not cursor:
                return rows
            if not isinstance(cursor, str):
                break
        raise RefreshError("orca_invalid", f"Orca returned too many pages of {key}.")

    def dispatch_terminals(self) -> dict[str, str]:
        """Dispatch ID to worker terminal across every run; `worker-list` alone covers only the caller's bound run."""
        terminals: dict[str, str] = {}
        for run in self.paged("runs", "run-list"):
            if not isinstance(run.get("id"), str):
                continue
            for worker in self.paged("workers", "worker-list", "--run", run["id"], "--limit", "100"):
                if isinstance(worker.get("dispatchId"), str) and isinstance(worker.get("terminal"), str):
                    terminals[worker["dispatchId"]] = worker["terminal"]
        return terminals

    def mail_pending(self, handle: str) -> bool:
        """True when Orca holds unread orchestration mail for the terminal, or cannot say.

        Orca writes a notice about unread mail into an idle agent's input line and presses Enter, so anything typed
        or sent meanwhile would be merged into that notice. An Orca without orchestration never does, so it counts
        as no mail. Mail whose recipient does not resolve to a terminal counts against no session, and so does mail
        Orca keeps only as history, which it never turns into a notice.
        """
        try:
            inbox = self.orchestration("inbox", "--limit", str(INBOX_LIMIT), "--full")
            if inbox is None:
                return False
            messages = inbox.get("messages")
            if not isinstance(messages, list) or any(not isinstance(item, dict) for item in messages) or len(messages) >= INBOX_LIMIT:
                raise RefreshError("orca_invalid", "Orca returned an unsupported or truncated inbox.")
            resolved: dict[str, str | None] = {}
            workers: dict[str, str] | None = None
            for message in messages:
                contract = message.get("delivery_contract")
                if message.get("read") or (isinstance(contract, str) and contract != "current_delivery"):
                    continue
                recipient = message.get("to_handle")
                if not isinstance(recipient, str):
                    continue
                if recipient not in resolved:
                    if recipient.startswith("run:"):
                        try:
                            run = self.orchestration("run-show", "--id", recipient[4:], "--full")
                        except RefreshError as error:
                            if error.code != "run_not_found":
                                raise
                            run = {"run": {}}
                        record = run.get("run") if run is not None else None
                        if not isinstance(record, dict):
                            raise RefreshError("orca_invalid", "Orca returned an unsupported run.")
                        coordinator = record.get("coordinator_handle")
                        resolved[recipient] = coordinator if isinstance(coordinator, str) else None
                    elif recipient.startswith("dispatch:"):
                        if workers is None:
                            workers = self.dispatch_terminals()
                        resolved[recipient] = workers.get(recipient[9:])
                    else:
                        resolved[recipient] = recipient
                if resolved[recipient] == handle:
                    return True
            return False
        except RefreshError:
            return True

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
