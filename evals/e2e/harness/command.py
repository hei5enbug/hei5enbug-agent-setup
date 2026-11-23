"""Variant loading and the exact `claude -p` command line, settings, and MCP config for one run."""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable, Iterable

from .config import (
    AGENT_EFFORT, APPROVER_SERVER, APPROVER_TOOL, CLAUDE_SETTING_SOURCES, FORBIDDEN_ARGS, HARNESS_DIR, HOST_CLAUDE, HOST_CODEX, HOSTS,
    ANCESTOR_INSTRUCTION_FILES, INSTALLED_PLUGIN_KEY, MAIN_MODELS, RESERVED_ARGS, HarnessConfig,
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


def is_reserved_arg(item: str) -> bool:
    """True for a flag the harness owns or that bypasses permissions, also in the `--flag=value` form."""
    flag = item.split("=", 1)[0] if item.startswith("-") else item
    return flag in FORBIDDEN_ARGS or flag in RESERVED_ARGS or item.startswith("--permission-mode")


def validate_variant(variant: Any, name: str = "variant") -> dict[str, Any]:
    if not isinstance(variant, dict) or not isinstance(variant.get("name"), str) or not isinstance(variant.get("ref"), str):
        raise ConfigError(f"{name}: a variant needs string 'name' and 'ref'")
    for key, kind in (("settings", dict), ("env", dict), ("extra_args", list)):
        if not isinstance(variant.get(key, kind()), kind):
            raise ConfigError(f"{name}: '{key}' must be a {kind.__name__}")
    extra = [str(item) for item in variant.get("extra_args", [])]
    banned = sorted(item for item in extra if is_reserved_arg(item))
    if banned:
        raise ConfigError(f"{name}: extra_args may not contain {banned}")
    if variant["name"].endswith("-codex"):
        raise ConfigError(f"{name}: a variant name may not end with '-codex', which marks a Codex run id")
    models = variant.get("models", {})
    if not isinstance(models, dict) or set(models) - set(HOSTS) or not all(isinstance(v, str) for v in models.values()):
        raise ConfigError(f"{name}: 'models' must map a host ({', '.join(HOSTS)}) to a model name")
    return {"name": variant["name"], "ref": variant["ref"], "settings": dict(variant.get("settings", {})),
            "env": {str(k): str(v) for k, v in variant.get("env", {}).items()}, "extra_args": extra,
            "models": dict(models)}


def validate_hosts(hosts: list[str]) -> list[str]:
    unknown = [host for host in hosts if host not in HOSTS]
    if unknown or not hosts:
        raise ConfigError(f"--hosts takes {', '.join(HOSTS)}; got {', '.join(unknown) or 'nothing'}")
    return list(dict.fromkeys(hosts))


def resolve_host_binaries(cfg: HarnessConfig, hosts: Iterable[str], which: Callable[[str], str | None] = shutil.which) -> HarnessConfig:
    """The config with each requested host's CLI replaced by its absolute path, found on the harness's own PATH, so that a
    task's `PATH` can never change which host binary starts. A CLI that cannot be found fails the invocation."""
    names = {HOST_CLAUDE: "claude_bin", HOST_CODEX: "codex_bin"}
    found: dict[str, str] = {}
    for host in hosts:
        configured = getattr(cfg, names[host])
        path = which(configured)
        if not path:
            raise ConfigError(f"the {host} host needs the `{configured}` command, which is not on PATH or not executable")
        found[names[host]] = os.path.abspath(path)
    return dataclasses.replace(cfg, **found)


def main_model(variant: dict[str, Any], host: str) -> str:
    """The main session model of a host: the variant's own choice, else the host's pinned default."""
    return str((variant.get("models") or {}).get(host) or MAIN_MODELS[host])


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


def task_environment(task: dict[str, Any], repo: Path, work: Path) -> dict[str, str]:
    """The task's own environment for the agent; `{repo}`, `{work}`, and `{PATH}` in a value name the run's folders and the current PATH."""
    tokens = {"{repo}": str(repo), "{work}": str(work), "{PATH}": os.environ.get("PATH", "")}
    result: dict[str, str] = {}
    for key, value in (task.get("env") or {}).items():
        text = str(value)
        for token, replacement in tokens.items():
            text = text.replace(token, replacement)
        result[str(key)] = text
    return result


def read_prompt(tasks_root: Path, task: dict[str, Any]) -> str:
    return (tasks_root / task["prompt_file"]).read_text(encoding="utf-8").strip()


def merge_settings(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in extra.items():
        merged[key] = merge_settings(merged[key], value) if isinstance(value, dict) and isinstance(merged.get(key), dict) else value
    return merged


def ancestor_excludes(cwd: Path) -> list[str]:
    """`claudeMdExcludes` patterns for every instruction file of each directory above `cwd`, by its resolved and its given path.

    Claude Code loads `CLAUDE.md`, `CLAUDE.local.md`, `.claude/CLAUDE.md`, and `.claude/rules/` of every ancestor of the working
    directory as project memory whatever `--setting-sources` says; `cwd` itself and below stay as the fixture defines them."""
    ancestors = dict.fromkeys(str(parent) for base in (cwd.absolute(), cwd.resolve()) for parent in base.parents)
    return [f"{folder.rstrip('/')}/{name}" for folder in ancestors for name in ANCESTOR_INSTRUCTION_FILES]


def run_settings(variant: dict[str, Any], profile_plugins: Iterable[str] = (), ancestor_patterns: Iterable[str] = ()) -> dict[str, Any]:
    """Default settings plus the variant's; the installed plugin and every plugin of the profile stay off whatever the variant says,
    and the ancestor instruction files named by `ancestor_patterns` stay excluded next to any `claudeMdExcludes` of the variant.

    The variant under test loads through `--plugin-dir`, so no `enabledPlugins` entry names it."""
    off = {key: False for key in (*profile_plugins, INSTALLED_PLUGIN_KEY)}
    merged = merge_settings({"enabledPlugins": off}, variant["settings"])
    enabled = merged.get("enabledPlugins")
    own = merged.get("claudeMdExcludes")
    excludes = list(dict.fromkeys([*(own if isinstance(own, list) else []), *ancestor_patterns]))
    return {**merged, "enabledPlugins": {**(enabled if isinstance(enabled, dict) else {}), **off},
            **({"claudeMdExcludes": excludes} if excludes else {})}


def user_env(task: dict[str, Any], tasks_root: Path, result_dir: Path) -> dict[str, str]:
    """The scripted user's files for the approver server: the task's answer sheet, the exchange log, and the agent stream."""
    sheet = (task.get("user") or {}).get("sheet")
    if not sheet:
        return {}
    return {"EVAL_ANSWER_SHEET": str(tasks_root / sheet), "EVAL_USER_LOG": str(result_dir / "user-log.jsonl"),
            "EVAL_STREAM": str(result_dir / "stream.jsonl")}


def mcp_config(
    approval_log: Path, run_folder: Path | None = None, cwd: Path | None = None, read_roots: tuple[str, ...] = (),
    user: dict[str, str] | None = None,
) -> dict[str, Any]:
    """The approver server config; it denies file tools outside `run_folder`, allows reads inside `read_roots`, and reads relative paths from `cwd`.
    With `user` it answers `AskUserQuestion` calls from the task's answer sheet."""
    folder = {"EVAL_RUN_FOLDER": str(run_folder)} if run_folder else {}
    roots = {"EVAL_READ_ROOTS": os.pathsep.join(read_roots)} if run_folder and read_roots else {}
    env = {"EVAL_APPROVAL_LOG": str(approval_log), **folder, **({"EVAL_RUN_CWD": str(cwd)} if run_folder and cwd else {}), **roots,
           **(user or {})}
    return {"mcpServers": {APPROVER_SERVER: {
        "type": "stdio", "command": "python3", "args": [str(APPROVER_SCRIPT)], "env": env,
    }}}


def build_command(
    cfg: HarnessConfig, task: dict[str, Any], variant: dict[str, Any], prompt: str, plugin_dir: str, run_dir: Path,
) -> list[str]:
    """The full agent command. It never passes bypass or permission-mode flags: runs start in the user's default mode.

    The prompt follows `--`, so a prompt that starts with a dash, such as `--version ...`, is not read as an option."""
    return [
        cfg.claude_bin, "-p", "--model", main_model(variant, HOST_CLAUDE), "--effort", AGENT_EFFORT,
        "--output-format", "stream-json", "--verbose", "--include-hook-events",
        "--plugin-dir", plugin_dir,
        "--settings", str(run_dir / "settings.json"), "--setting-sources", CLAUDE_SETTING_SOURCES,
        "--mcp-config", str(run_dir / "mcp.json"), "--strict-mcp-config",
        "--permission-prompt-tool", APPROVER_TOOL,
        "--max-budget-usd", str(task["limits"]["max_budget_usd"]),
        *variant["extra_args"],
        "--", prompt,
    ]
