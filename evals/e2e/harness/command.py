"""Variant loading and the exact `claude -p` command line, settings, and MCP config for one run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import (
    AGENT_EFFORT, AGENT_MODEL, APPROVER_SERVER, APPROVER_TOOL, FORBIDDEN_ARGS, HARNESS_DIR, INSTALLED_PLUGIN_KEY,
    HarnessConfig,
)

APPROVER_SCRIPT = HARNESS_DIR / "approval_mcp.py"


class ConfigError(ValueError):
    pass


def load_variant(variants_root: Path, name: str) -> dict[str, Any]:
    path = variants_root / f"{name}.json"
    try:
        variant = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ConfigError(f"cannot read variant {name}: {error}") from error
    return validate_variant(variant, name)


def validate_variant(variant: Any, name: str = "variant") -> dict[str, Any]:
    if not isinstance(variant, dict) or not isinstance(variant.get("name"), str) or not isinstance(variant.get("ref"), str):
        raise ConfigError(f"{name}: a variant needs string 'name' and 'ref'")
    for key, kind in (("settings", dict), ("env", dict), ("extra_args", list)):
        if not isinstance(variant.get(key, kind()), kind):
            raise ConfigError(f"{name}: '{key}' must be a {kind.__name__}")
    extra = [str(item) for item in variant.get("extra_args", [])]
    banned = sorted(item for item in extra if item in FORBIDDEN_ARGS or item.startswith("--permission-mode"))
    if banned:
        raise ConfigError(f"{name}: extra_args may not contain {banned}")
    return {"name": variant["name"], "ref": variant["ref"], "settings": dict(variant.get("settings", {})),
            "env": {str(k): str(v) for k, v in variant.get("env", {}).items()}, "extra_args": extra}


def load_task(tasks_root: Path, task_id: str) -> dict[str, Any]:
    path = tasks_root / f"{task_id}.json"
    try:
        task = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ConfigError(f"cannot read task {task_id}: {error}") from error
    limits = task.get("limits") if isinstance(task, dict) else None
    missing = [key for key in ("id", "fixture", "prompt_file") if not isinstance(task, dict) or key not in task]
    if missing or not isinstance(limits, dict) or "wall_seconds" not in limits or "max_budget_usd" not in limits:
        raise ConfigError(f"{task_id}: task needs id, fixture, prompt_file, and limits.wall_seconds/max_budget_usd")
    return task


def read_prompt(tasks_root: Path, task: dict[str, Any]) -> str:
    return (tasks_root / task["prompt_file"]).read_text(encoding="utf-8").strip()


def merge_settings(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in extra.items():
        merged[key] = merge_settings(merged[key], value) if isinstance(value, dict) and isinstance(merged.get(key), dict) else value
    return merged


def run_settings(variant: dict[str, Any]) -> dict[str, Any]:
    return merge_settings({"enabledPlugins": {INSTALLED_PLUGIN_KEY: False}}, variant["settings"])


def mcp_config(approval_log: Path) -> dict[str, Any]:
    return {"mcpServers": {APPROVER_SERVER: {
        "type": "stdio", "command": "python3", "args": [str(APPROVER_SCRIPT)],
        "env": {"EVAL_APPROVAL_LOG": str(approval_log)},
    }}}


def build_command(
    cfg: HarnessConfig, task: dict[str, Any], variant: dict[str, Any], prompt: str, plugin_dir: str, run_dir: Path,
) -> list[str]:
    """The full agent command. It never passes bypass or permission-mode flags: runs start in the user's default mode."""
    return [
        cfg.claude_bin, "-p", prompt, "--model", AGENT_MODEL, "--effort", AGENT_EFFORT,
        "--output-format", "stream-json", "--verbose", "--include-hook-events",
        "--plugin-dir", plugin_dir,
        "--settings", str(run_dir / "settings.json"),
        "--mcp-config", str(run_dir / "mcp.json"),
        "--permission-prompt-tool", APPROVER_TOOL,
        "--max-budget-usd", str(task["limits"]["max_budget_usd"]),
        *variant["extra_args"],
    ]
