from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from approval_state import recorded_worker_pair  # noqa: E402
from plugin_toggles import detect_host, enabled, valid_worker_pair, worker_setting  # noqa: E402


CODEX_BUILT_INS = {"default", "explorer"}
ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "config" / "model-registry.json"
REGISTRY = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
PIN_VALUES = set(REGISTRY["pins"].values())
EFFORTS = set(REGISTRY["efforts"])
EFFORT_RULES = REGISTRY["effort_rules"]
LUNA_MODEL = REGISTRY["pins"]["gpt-luna"]
LUNA_EFFORTS = tuple(REGISTRY["effort_rules"][LUNA_MODEL])
LUNA_EFFORT_TEXT = " or ".join(f"`{effort}`" for effort in LUNA_EFFORTS)
LUNA_DENIAL = f"GPT Luna assignments must use `{LUNA_MODEL}` with {LUNA_EFFORT_TEXT}."


def toml_name(text: str) -> str | None:
    try:
        name = tomllib.loads(text).get("name")
    except tomllib.TOMLDecodeError:
        return None
    return name if isinstance(name, str) and name else None


def codex_role_settings(directories: list[Path], name: str) -> list[tuple[Path, dict]]:
    found = []
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in directory.rglob("*.toml"):
            try:
                settings = tomllib.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
                continue
            if settings.get("name") == name:
                found.append((path, settings))
    return found


def defined_codex_roles(directories: list[Path]) -> set[str]:
    names = set()
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in directory.rglob("*.toml"):
            try:
                name = toml_name(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
            if name:
                names.add(name)
    return names


def entry_problem(entry: object) -> str | None:
    if not isinstance(entry, dict):
        return "an entry is not an object"
    model, effort = entry.get("model"), entry.get("effort")
    if model not in PIN_VALUES:
        return f"{model} is not a pinned model"
    if effort not in EFFORTS:
        return f"{effort} is not a known effort"
    allowed = EFFORT_RULES.get(model)
    if allowed is not None and effort not in allowed:
        return f"{effort} is not allowed for {model}"
    return None


def declaration_problem(agents: dict) -> str | None:
    for name, entry in agents.items():
        problem = entry_problem(entry)
        if problem is None and isinstance(entry, dict) and "fallback" in entry:
            problem = entry_problem(entry["fallback"])
        if problem is not None:
            return f"`{name}`: {problem}"
    return None


VERSION_CORE = re.compile(r"[0-9]+(?:\.[0-9]+)*")


def version_key(version: Path) -> tuple[int, ...] | None:
    core = re.split(r"[+-]", version.name, maxsplit=1)[0]
    if VERSION_CORE.fullmatch(core) is None:
        return None
    return tuple(int(part) for part in core.split("."))


def newest_version(versions: list[Path]) -> Path:
    if all(version_key(version) is not None for version in versions):
        return max(versions, key=lambda version: (version_key(version), version.stat().st_mtime))
    return max(versions, key=lambda version: version.stat().st_mtime)


def cached_roles_files(home: Path) -> list[Path]:
    """Return the model roles file of the newest cached version of each marketplace plugin."""
    files = []
    for plugin in sorted(home.glob("plugins/cache/*/*")):
        if not plugin.is_dir():
            continue
        versions = [version for version in plugin.iterdir() if version.is_dir()]
        if not versions:
            continue
        roles = newest_version(versions) / ".codex-plugin" / "model-roles.json"
        if roles.exists():
            files.append(roles)
    return files


def read_declaration(path: Path) -> tuple[dict | None, str | None]:
    """Return the agents object and its first entry problem, or None and the reason when the file itself is unusable."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None, "cannot be read"
    try:
        data = json.loads(text)
    except ValueError:
        return None, "is not valid JSON"
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("agents"), dict):
        return None, "has no version 1 agents object"
    return data["agents"], declaration_problem(data["agents"])


def declared_codex_roles(home: Path) -> tuple[dict[str, list[dict]], dict[str, str], list[str]]:
    pins: dict[str, list[dict]] = {}
    problems: dict[str, str] = {}
    unusable: list[str] = []
    for path in cached_roles_files(home):
        agents, problem = read_declaration(path)
        if agents is None:
            unusable.append(f"`{path}` {problem}")
            continue
        for name, entry in agents.items():
            if name in REGISTRY["codex_agents"]:
                continue
            if problem is not None:
                problems[name] = problem
                pins.pop(name, None)
            elif name not in problems and name not in pins:
                pins[name] = [{"model": entry["model"], "effort": entry["effort"]}]
    return pins, problems, unusable


def pinned_pairs(name: str, home: Path, session=None) -> tuple[list[dict] | None, str | None]:
    """Return the only pair a Codex role may be spawned with: its primary pair, since a fallback is cross-family.

    The worker pair is the one recorded at this session's start when it is still valid, else the live setting.
    """
    if name == "worker":
        recorded = recorded_worker_pair("codex", session)
        if recorded is not None and valid_worker_pair("codex", *recorded):
            model, effort = recorded
        else:
            model, effort, _ = worker_setting("codex")
        return [{**REGISTRY["codex_agents"][name], "model": model, "effort": effort}], None
    if name in REGISTRY["codex_agents"]:
        return [REGISTRY["codex_agents"][name]], None
    pins, problems, _ = declared_codex_roles(home)
    if name in problems:
        return None, problems[name]
    return pins.get(name), None


def role_file_denial(name: str, requested: tuple, directories: list[Path]) -> str | None:
    """A role file's own model or effort must equal the requested one; a key the file leaves out is not checked."""
    for path, settings in codex_role_settings(directories, name):
        if "model" not in settings and "model_reasoning_effort" not in settings:
            continue
        pinned = (settings.get("model", requested[0]), settings.get("model_reasoning_effort", requested[1]))
        if pinned != requested:
            return (
                f"The role file {path} pins `{name}` to {pinned[0]!r} with {pinned[1]!r}, so this assignment must use "
                f"that pair, not {requested[0]!r} with {requested[1]!r}."
            )
    return None


def pin_denial(name: str, tool_input: dict, home: Path, directories: list[Path], session=None) -> str | None:
    pairs, problem = pinned_pairs(name, home, session)
    if problem is not None:
        return (
            f"The model roles declared for `{name}` are invalid ({problem}), so hei5enbug-agent-setup did not start it. "
            "Use `scout` or `worker`, another defined agent, or the main session."
        )
    if pairs is None:
        return None
    requested = (tool_input.get("model"), tool_input.get("reasoning_effort"))
    if any(requested == (pair["model"], pair["effort"]) for pair in pairs):
        return role_file_denial(name, requested, directories)
    allowed = " or ".join(f"`{pair['model']}` with `{pair['effort']}`" for pair in pairs)
    return (
        f"`{name}` assignments must use {allowed}. A fallback is the other model family and cannot be spawned in Codex; "
        f"run it with `python3 {ROOT}/scripts/role_runner.py agent --name {name} --fallback --assignment <file> --result <file>`."
    )


def unusable_denial(name: str, unusable: list[str]) -> str:
    return (
        f"A model roles file under the plugin cache is unusable: {'; '.join(unusable)}. "
        f"hei5enbug-agent-setup did not start `{name}`. "
        "Use `scout` or `worker`, another defined agent, or the main session."
    )


def denial(event: dict) -> str | None:
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    model = tool_input.get("model")
    if isinstance(model, str) and model.startswith("gpt-") and model.endswith("-luna"):
        if model != LUNA_MODEL:
            return LUNA_DENIAL
        effort = tool_input.get("reasoning_effort")
        if effort is not None and effort not in LUNA_EFFORTS:
            return LUNA_DENIAL
    name = tool_input.get("agent_type") or "default"
    cwd = Path(event.get("cwd") or os.getcwd())
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    if name not in REGISTRY["codex_agents"]:
        _, _, unusable = declared_codex_roles(home)
        if unusable:
            return unusable_denial(name, unusable)
    directories = [home / "agents", cwd / ".codex" / "agents"]
    allowed = defined_codex_roles(directories) - CODEX_BUILT_INS
    if name in allowed:
        return pin_denial(name, tool_input, home, directories, event.get("session_id"))
    return (
        f"The built-in `{name}` agent is disabled while hei5enbug-agent-setup is installed. "
        "Use `scout` or `worker`, another defined agent, or the main session."
    )


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (OSError, ValueError):
        return 0
    if not isinstance(event, dict) or event.get("hook_event_name") != "PreToolUse":
        return 0
    if detect_host() != "codex" or not enabled("agent_guard"):
        return 0
    reason = denial(event)
    if reason:
        output = {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}
        print(json.dumps({"hookSpecificOutput": output}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
