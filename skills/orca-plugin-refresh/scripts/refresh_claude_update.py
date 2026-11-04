from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

from refresh_process import installed_release

UPDATE_TIMEOUT = 300.0
DETAIL_LIMIT = 200
DISABLE_VARIABLE = "DISABLE_UPDATES"
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
MANAGED_SETTINGS = {
    "darwin": Path("/Library/Application Support/ClaudeCode/managed-settings.json"),
    "linux": Path("/etc/claude-code/managed-settings.json"),
}
WARNING_CODE = "claude_update_failed"


def read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def run_command(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, check=False)


def current_release() -> str | None:
    return installed_release()[0]


@dataclass(frozen=True)
class UpdateSystem:
    """Every environment, file, and process access of the Claude Code update step, replaceable in tests."""

    environ: Callable[[], Mapping[str, str]] = field(default=lambda: os.environ)
    read_json: Callable[[Path], object] = field(default=read_json)
    which: Callable[[str], str | None] = field(default=shutil.which)
    run: Callable[[list[str], float], subprocess.CompletedProcess[str]] = field(default=run_command)
    release: Callable[[], str | None] = field(default=current_release)
    platform: str = sys.platform


def truthy(value: object) -> bool:
    return str(value).strip().lower() in TRUE_VALUES


def settings_files(system: UpdateSystem) -> list[Path]:
    config = system.environ().get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude"
    managed = MANAGED_SETTINGS.get(system.platform)
    return [Path(config) / "settings.json", *([managed] if managed else [])]


def updates_disabled(system: UpdateSystem) -> bool:
    if truthy(system.environ().get(DISABLE_VARIABLE, "")):
        return True
    for path in settings_files(system):
        document = system.read_json(path)
        env = document.get("env") if isinstance(document, dict) else None
        if isinstance(env, dict) and DISABLE_VARIABLE in env and truthy(env[DISABLE_VARIABLE]):
            return True
    return False


def short_detail(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return (lines[-1] if lines else "no output")[:DETAIL_LIMIT]


def skipped(reason: str) -> dict:
    return {"status": "skipped", "before": None, "after": None, "reason": reason}


def run_claude_update(system: UpdateSystem | None = None) -> dict:
    """Run `claude update` once and report the release before and after; a failure is reported, never raised."""
    system = system or UpdateSystem()
    if updates_disabled(system):
        return skipped("updates_disabled")
    path = system.which("claude")
    if not path:
        return skipped("claude_missing")
    before = system.release()
    failure: dict | None = None
    try:
        result = system.run([path, "update"], UPDATE_TIMEOUT)
    except subprocess.TimeoutExpired:
        failure = {"exit_status": None, "detail": f"timed out after {int(UPDATE_TIMEOUT)} seconds"}
    except (OSError, subprocess.SubprocessError):
        failure = {"exit_status": None, "detail": "claude update could not start"}
    else:
        if result.returncode != 0:
            failure = {"exit_status": result.returncode, "detail": short_detail(result.stderr or result.stdout or "")}
    after = system.release()
    if failure:
        return {"status": "failed", "before": before, "after": after, **failure}
    return {"status": "updated" if after != before else "current", "before": before, "after": after}


def attach_claude_update(hosts: dict[str, dict], step: dict) -> dict[str, dict]:
    """A copy of the host results whose Claude Code entry also holds the step and, when it failed, its warning."""
    entry = {**hosts["claude"], "claude_code": step}
    if step["status"] == "failed":
        status = "" if step["exit_status"] is None else f" (exit status {step['exit_status']})"
        message = f"claude update failed{status}: {step['detail']}"
        entry["warnings"] = [*entry.get("warnings", []), {"code": WARNING_CODE, "message": message}]
    return {**hosts, "claude": entry}
