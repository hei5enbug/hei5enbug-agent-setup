from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Mapping, Sequence

import refresh_core as core
from refresh_core import RefreshError
from refresh_process import find_session_process

RELOAD_LINE = re.compile(r"Reloaded: (?P<counts>\d+ plugins?[^\n]*)")
LOAD_ERRORS = re.compile(r"(\d+) errors? during load")
COUNT_SEGMENT = re.compile(r"\s*(\d+) (plugin|skill|agent|hook)s?\s*")
LIST_TIMEOUT = 60.0
SESSION_PLUGIN_VARIABLES = ("CLAUDE_CONFIG_DIR", "CLAUDE_CODE_PLUGIN_DIRS", "CLAUDE_CODE_PLUGIN_CACHE_DIR", "CLAUDE_CODE_PLUGIN_SEED_DIR")
EXPECTED_CACHE: dict[tuple[tuple[str, str], ...], int | None] = {}


def reload_report(text: str) -> dict | None:
    """The counts a `/reload-plugins` answer reports, with `errors` from its `N error(s) during load` line; None when the text
    holds no `Reloaded:` line."""
    line = RELOAD_LINE.search(text)
    if line is None:
        return None
    report: dict[str, int] = {}
    for segment in line.group("counts").split("·"):
        counted = COUNT_SEGMENT.fullmatch(segment)
        if counted:
            report.setdefault(f"{counted.group(2)}s", int(counted.group(1)))
    errors = LOAD_ERRORS.search(text[line.start():])
    report["errors"] = int(errors.group(1)) if errors else 0
    return report


def load_failed(report: dict, expected: int | None) -> bool:
    """True when the answer reports a load error or loaded fewer plugins than the host's enabled list."""
    return report.get("errors", 0) > 0 or (expected is not None and report.get("plugins", 0) < expected)


def screen_report(lines: Sequence[str], follow: int = 3) -> dict | None:
    """The report from the newest `Reloaded:` line on screen and the few lines after it."""
    starts = [index for index, line in enumerate(lines) if RELOAD_LINE.search(line)]
    if not starts:
        return None
    return reload_report("\n".join(lines[starts[-1]:starts[-1] + follow + 1]))


def enabled_count(session_env: Mapping[str, str], cwd: str | None) -> int | None:
    """Entries with `enabled: true` in `claude plugin list --json` for the session's plugin variables and working folder.

    The caller's own `SESSION_PLUGIN_VARIABLES` are dropped, so only the values in `session_env` decide what is counted.
    """
    if not cwd or not Path(cwd).is_dir():
        return None
    environment = {key: value for key, value in os.environ.items() if key not in SESSION_PLUGIN_VARIABLES}
    environment.update({name: session_env[name] for name in SESSION_PLUGIN_VARIABLES if session_env.get(name)})
    try:
        result = subprocess.run([core.executable("claude"), "plugin", "list", "--json"], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=LIST_TIMEOUT, check=False, env=environment, cwd=cwd)
        plugins = json.loads(result.stdout) if result.returncode == 0 else None
    except (RefreshError, OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    if not isinstance(plugins, list):
        return None
    return sum(1 for item in plugins if isinstance(item, dict) and item.get("enabled") is True)


def expected_plugins(entry: dict) -> int | None:
    """The lower bound of plugins the session's host should load, or None when it cannot be told.

    The count is read once per working folder and set of `SESSION_PLUGIN_VARIABLES` values, taken from the session process's own
    environment.
    """
    try:
        process = find_session_process(entry["handle"])
    except RefreshError:
        return None
    if process is None:
        return None
    session_env = {name: process.env[name] for name in SESSION_PLUGIN_VARIABLES if process.env.get(name)}
    key = (*session_env.items(), ("worktree", str(entry.get("worktree") or "")))
    if key not in EXPECTED_CACHE:
        EXPECTED_CACHE[key] = enabled_count(session_env, entry.get("worktree"))
    return EXPECTED_CACHE[key]


def local_text(records: Sequence[dict]) -> str:
    return "\n".join(str(record.get("content") or "") for record in records if record.get("subtype") == "local_command")


def judge_reload(entry: dict | None, report: dict | None) -> str:
    """`done`, or `failed:plugin_load_error` with the reported counts kept on the entry."""
    expected = expected_plugins(entry) if entry is not None and report is not None else None
    if report is None or not load_failed(report, expected):
        if entry is not None:
            entry.pop("plugin_load", None)
        return "done"
    if entry is not None:
        entry["plugin_load"] = {**report, **({"expected_plugins": expected} if expected is not None else {})}
    return "failed:plugin_load_error"
