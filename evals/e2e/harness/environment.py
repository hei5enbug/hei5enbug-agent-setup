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

from .config import INSTALLED_PLUGINS_RECORD, REMOVED_ENV_NAMES, REMOVED_ENV_PREFIX

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
    """Return the child env without ORCA_* variables and the variables that load plugins, plus the sorted removed names."""
    def dropped(name: str) -> bool:
        return name.startswith(REMOVED_ENV_PREFIX) or name in REMOVED_ENV_NAMES

    removed = sorted(name for name in base if dropped(name))
    kept = {name: value for name, value in base.items() if not dropped(name)}
    return {**kept, **extra}, removed


def _profile_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        raise ValueError(f"cannot read {path.name} of the Claude Code profile: {error}") from error
    return data if isinstance(data, dict) else {}


def profile_plugin_ids(config_dir: Path) -> list[str]:
    """Every plugin id the profile installs or enables, read from its installed-plugins record and its settings file."""
    installed = _profile_json(config_dir / INSTALLED_PLUGINS_RECORD).get("plugins")
    enabled = _profile_json(config_dir / "settings.json").get("enabledPlugins")
    ids = [*(installed if isinstance(installed, dict) else {}), *(enabled if isinstance(enabled, dict) else {})]
    return sorted(set(ids))


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


def run_snapshot(
    base: Mapping[str, Any], plugin: Mapping[str, Any], removed_env: list[str], instruction_isolation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """`instruction_isolation` names how a Claude Code run keeps the user's instruction files and auto memory out, and the limits that remain."""
    isolation = {"instruction_isolation": dict(instruction_isolation)} if instruction_isolation else {}
    return {**base, "removed_env_names": removed_env, "plugin_ref": plugin.get("ref"), "plugin_sha": plugin.get("sha"),
            "cap_transform": plugin.get("cap_transform"), "review_stand_in": plugin.get("review_stand_in"),
            "grader_review_model": (plugin.get("review_stand_in") or {}).get("model"), **isolation}
