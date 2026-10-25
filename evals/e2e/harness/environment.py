"""Per-run environment snapshot: tool versions, installed plugins, config hashes, and what was removed."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

from .config import REMOVED_ENV_PREFIX

Runner = Callable[[list[str], Path | None], str | None]


def claude_config_dir(env: Mapping[str, str] | None = None) -> Path:
    source = os.environ if env is None else env
    return Path(source.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def codex_home(env: Mapping[str, str] | None = None) -> Path:
    source = os.environ if env is None else env
    return Path(source.get("CODEX_HOME") or Path.home() / ".codex")


def run_command(command: list[str], cwd: Path | None = None) -> str | None:
    """Run a short read-only command and return stdout, or None when it cannot run or fails."""
    try:
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def child_environment(base: Mapping[str, str], extra: Mapping[str, str]) -> tuple[dict[str, str], list[str]]:
    """Return the child env without ORCA_* variables plus the sorted names that were removed."""
    removed = sorted(name for name in base if name.startswith(REMOVED_ENV_PREFIX))
    kept = {name: value for name, value in base.items() if not name.startswith(REMOVED_ENV_PREFIX)}
    return {**kept, **extra}, removed


def _parsed(text: str | None) -> Any:
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


def capture_base(claude_bin: str, repo_root: Path, run: Runner = run_command, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Facts that do not change between runs of one campaign; capture them once."""
    source = os.environ if env is None else env
    dirty = run(["git", "status", "--porcelain"], repo_root)
    return {
        "claude_version": run([claude_bin, "--version"], None),
        "codex_version": run(["codex", "--version"], None),
        "claude_plugin_list": _parsed(run([claude_bin, "plugin", "list", "--json"], None)),
        "claude_settings_sha256": file_sha256(claude_config_dir(source) / "settings.json"),
        "codex_config_sha256": file_sha256(codex_home(source) / "config.toml"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "harness_git_head": run(["git", "rev-parse", "HEAD"], repo_root),
        "harness_git_dirty": bool(dirty),
    }


def run_snapshot(base: Mapping[str, Any], plugin: Mapping[str, Any], removed_env: list[str]) -> dict[str, Any]:
    return {**base, "removed_env_names": removed_env, "plugin_ref": plugin.get("ref"), "plugin_sha": plugin.get("sha")}
