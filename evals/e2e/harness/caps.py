"""The model cap of a measurement: reject a campaign that could start a stronger model, and find one in a run's records."""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

from . import plugin_export, rubric
from .command import ConfigError, main_model
from .config import HOST_CLAUDE, HOST_CODEX, HOSTS, MODEL_CAP, HarnessConfig
from .transcript import result_event, role_runner_status

OPTION_PREFIXES = {HOST_CLAUDE: "CLAUDE_PLUGIN_OPTION_", HOST_CODEX: "HEI5ENBUG_"}
HOST_LABELS = {HOST_CLAUDE: "Claude Code", HOST_CODEX: "Codex"}
MODEL_OPTION_SUFFIX = "_model"
MANIFEST_PATH = ".claude-plugin/plugin.json"
IGNORED_MODELS = frozenset({"", "unknown", "<synthetic>", "None"})
BRACKET_SUFFIX = re.compile(r"\[[^\]]*\]$")
DATE_SUFFIX = re.compile(r"-\d{8}$")


def normalize(model: Any) -> str:
    return DATE_SUFFIX.sub("", BRACKET_SUFFIX.sub("", str(model).strip()))


def within_cap(model: Any) -> bool:
    return normalize(model) in MODEL_CAP


def cap_text() -> str:
    return ", ".join(sorted(MODEL_CAP))


def violation_message(owner: str, role: str, model: str) -> str:
    return f"{owner}: role {role} would run {model}, which is outside the model cap ({cap_text()})"


def manifest_defaults(cfg: HarnessConfig, ref: str) -> dict[str, str]:
    """Default value of each model option (a key ending in `_model`) in the plugin manifest of `ref`."""
    try:
        sha = plugin_export.resolve_ref(cfg.repo_root, ref)
        config = json.loads(plugin_export._git(cfg.repo_root, "show", f"{sha}:{MANIFEST_PATH}"))["userConfig"]
    except (plugin_export.ExportError, ValueError, KeyError, TypeError):
        return {}
    return {key: str(spec.get("default") or "") for key, spec in config.items()
            if key.endswith(MODEL_OPTION_SUFFIX) and isinstance(spec, dict) and spec.get("default")}


def option_names(prefix: str, key: str) -> list[str]:
    return [prefix + key.upper(), prefix + key]


def check_variant(cfg: HarnessConfig, variant: dict[str, Any]) -> list[str]:
    """Problems of one variant: a main model, or a plugin model option left at its manifest default, outside the cap."""
    owner, problems = f"variant {variant['name']}", []
    for host in HOSTS:
        model = main_model(variant, host)
        if not within_cap(model):
            problems.append(violation_message(owner, f"main session ({HOST_LABELS[host]})", model))
    defaults = manifest_defaults(cfg, variant["ref"])
    env = variant["env"]
    for host, prefix in OPTION_PREFIXES.items():
        set_here = {name: value for name, value in env.items()
                    if name.upper().startswith(prefix.upper()) and name.lower().endswith(MODEL_OPTION_SUFFIX)}
        for name, value in sorted(set_here.items()):
            if not within_cap(value):
                key = name[len(prefix):].lower().removesuffix(MODEL_OPTION_SUFFIX)
                problems.append(violation_message(owner, f"{key} ({HOST_LABELS[host]}, option {name})", value))
        for key, default in sorted(defaults.items()):
            if any(name in env for name in option_names(prefix, key)) or within_cap(default):
                continue
            role = f"{key.removesuffix(MODEL_OPTION_SUFFIX)} ({HOST_LABELS[host]}, option {key} left at its default)"
            problems.append(violation_message(owner, role, default) + f"; set {prefix}{key.upper()} in the variant env")
    return problems


def check_graders() -> list[str]:
    return [violation_message("rubric grader", role, model)
            for role, model in (("rubric grader", rubric.RUBRIC_MODEL), ("rubric grader fallback", rubric.RUBRIC_FALLBACK_MODEL))
            if not within_cap(model)]


def check_campaign(cfg: HarnessConfig, variants: Iterable[dict[str, Any]]) -> None:
    """Raise ConfigError naming every role whose model is outside the cap; a campaign with such a role never starts."""
    problems = [problem for variant in variants for problem in check_variant(cfg, variant)] + check_graders()
    if problems:
        raise ConfigError("model cap: " + "; ".join(problems))


def _note(found: dict[tuple[str, str], None], model: Any, role: str) -> None:
    text = str(model or "")
    if text not in IGNORED_MODELS and not within_cap(text):
        found.setdefault((normalize(text), role), None)


def scan_run(
    *, stream_events: list[dict[str, Any]], by_source: dict[str, list[dict[str, Any]]], tool_calls: list[dict[str, Any]],
    rollouts: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Every model outside the cap that answered in a run, with the role: Claude stream and transcripts, the role runner
    status lines, and the `turn_context` of each Codex rollout. An empty list means none did."""
    found: dict[tuple[str, str], None] = {}
    result = result_event(stream_events) or {}
    for model in (result.get("modelUsage") or {}) if isinstance(result.get("modelUsage"), dict) else ():
        _note(found, model, "main session or subagent (stream modelUsage)")
    for source, requests in by_source.items():
        for request in requests:
            _note(found, request.get("model"), source)
    for call in tool_calls:
        status = role_runner_status(str(call.get("result_text", "")))
        if status:
            _note(found, status.get("model"), f"role_runner:{status.get('role') or 'unknown'}")
    for rollout in rollouts:
        for event in rollout.get("events", []):
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            if event.get("type") == "turn_context":
                _note(found, payload.get("model"), f"codex:{rollout.get('role', 'unknown')}")
    return [{"model": model, "role": role} for model, role in found]


def violation_summary(violations: list[dict[str, str]]) -> str:
    return "; ".join(f"{item['model']} as {item['role']}" for item in violations)
