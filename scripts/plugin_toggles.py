from __future__ import annotations

import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OFF_VALUES = {"false", "0", "off", "no"}
PLUGIN_NAME = "hei5enbug-agent-setup"


def detect_host() -> str:
    root = Path(__file__).resolve().parents[1]
    codex_root = os.environ.get("PLUGIN_ROOT")
    return "codex" if codex_root and Path(codex_root).resolve() == root else "claude"


def variable_name(key: str, host: str) -> str:
    prefix = "HEI5ENBUG_" if host == "codex" else "CLAUDE_PLUGIN_OPTION_"
    return prefix + key.upper()


def enabled(key: str) -> bool:
    """Return False only when the host's toggle for `key` is set to an off value."""
    value = os.environ.get(variable_name(key, detect_host()), "")
    return value.strip().casefold() not in OFF_VALUES


def option_value(key: str) -> str:
    """Return the current host's string option value, normalized or empty when unset."""
    return os.environ.get(variable_name(key, detect_host()), "").strip().lower()


def worker_option_keys(host: str) -> tuple[str, str]:
    return ("codex_worker_model", "codex_worker_effort") if host == "codex" else ("worker_model", "worker_effort")


def saved_options(keys: tuple[str, ...]) -> tuple[dict, str | None]:
    """Read this plugin's saved options from the Claude user settings without writing; return the values and a problem."""
    config = os.environ.get("CLAUDE_CONFIG_DIR")
    path = (Path(config) if config else Path.home() / ".claude") / "settings.json"
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, None
    except (OSError, ValueError):
        return {}, "Claude settings file is unreadable or malformed"
    configs = settings.get("pluginConfigs") if isinstance(settings, dict) else None
    if configs is None:
        return {}, None
    if not isinstance(configs, dict):
        return {}, "Claude settings pluginConfigs is malformed"
    for name in sorted(configs):
        if name.startswith(f"{PLUGIN_NAME}@") and isinstance(configs[name], dict):
            options = configs[name].get("options")
            if isinstance(options, dict):
                return {key: options[key] for key in keys if key in options}, None
    return {}, None


def valid_worker_pair(host: str, model: object, effort: object) -> bool:
    """Whether the pair is in the manifest option lists and allowed by the registry effort rules."""
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["userConfig"]
    registry = json.loads((ROOT / "config" / "model-registry.json").read_text(encoding="utf-8"))
    model_key, effort_key = worker_option_keys(host)
    return (
        model in manifest[model_key]["options"]
        and effort in manifest[effort_key]["options"]
        and effort in registry["effort_rules"].get(model, [effort])
    )


def worker_setting(host: str) -> tuple[str, str, str | None]:
    """Resolve the worker model and effort for `host` from the manifest, with an optional notice for an ignored value.

    Codex reads each key from its HEI5ENBUG_ variable and otherwise from the saved Claude plugin options.
    On Claude the configured pair applies only through role pinning, so with it off the manifest defaults stand.
    An invalid value or pair resets both keys to the manifest defaults; a broken settings file ignores only the saved keys.
    """
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["userConfig"]
    registry = json.loads((ROOT / "config" / "model-registry.json").read_text(encoding="utf-8"))
    keys = worker_option_keys(host)
    defaults = tuple(manifest[key]["default"] for key in keys)
    if host != "codex" and os.environ.get(variable_name("role_pinning", host), "").strip().casefold() in OFF_VALUES:
        return *defaults, "role pinning is off, so the worker runs on its definition's model"
    values: dict = {}
    for key in keys:
        text = os.environ.get(variable_name(key, host), "").strip().lower()
        if text:
            values[key] = text
    problem = None
    if host == "codex" and len(values) < len(keys):
        saved, problem = saved_options(keys)
        for key in keys:
            if key not in values and key in saved:
                values[key] = saved[key].strip().lower() if isinstance(saved[key], str) else saved[key]
    note = f"Ignored the saved worker settings: {problem}; using defaults." if problem else None
    pair = [values.get(key, default) for key, default in zip(keys, defaults)]
    for key, value in zip(keys, pair):
        if value not in manifest[key]["options"]:
            return *defaults, f"Ignored {key} {ascii(value)[:40]}; using defaults."
    if pair[1] not in registry["effort_rules"].get(pair[0], [pair[1]]):
        return *defaults, f"Ignored {keys[0]} {pair[0]} at {pair[1]}, which is not allowed; using defaults."
    return pair[0], pair[1], note
