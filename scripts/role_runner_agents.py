from __future__ import annotations

import argparse
import json
import os
import tomllib
from pathlib import Path

import agent_guard
from role_runner_config import AGENT_TARGET, REGISTRY, ROOT, WEB_TOOLS, WRITING_CAPABILITIES, Run, UsageError
from role_runner_evidence import claude_home, codex_home
from role_runner_prompt import without_frontmatter


def default_host() -> str:
    return "codex" if os.environ.get("CODEX_THREAD_ID") else "claude"


def runner_for(model: str) -> str:
    return "claude" if model.startswith("claude-") else "codex"


def accepts_add_dir(target: str) -> bool:
    return target in ("worker", AGENT_TARGET) or target in WRITING_CAPABILITIES


def definition_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise UsageError(f"Cannot read the agent definition {path}: {error}") from error


def definition_body(path: Path) -> str:
    try:
        return without_frontmatter(definition_text(path), path.as_posix())
    except ValueError as error:
        raise UsageError(str(error)) from error


def web_tools_in(path: Path | None) -> tuple[str, ...]:
    """Return the web tools a Claude agent definition lists in its frontmatter; a missing definition lists none."""
    if path is None or not path.is_file():
        return ()
    lines = definition_text(path).splitlines()
    if not lines or lines[0].rstrip() != "---":
        return ()
    closing = next((index for index in range(1, len(lines)) if lines[index].rstrip() == "---"), len(lines))
    for line in lines[1:closing]:
        key, _, value = line.partition(":")
        if key.strip() == "tools":
            listed = {item.strip() for item in value.split(",")}
            return tuple(tool for tool in WEB_TOOLS if tool in listed)
    return ()


def codex_instructions(name: str, paths: list[Path]) -> str | None:
    """Return the developer_instructions of the first role TOML in paths whose name is name."""
    for path in paths:
        try:
            settings = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            continue
        text = settings.get("developer_instructions")
        if settings.get("name") == name and isinstance(text, str) and text.strip():
            return text.strip()
    return None


def codex_body(name: str, registry: bool) -> str:
    """Find a Codex role's instructions in the personal, then project, then (for a registry role) plugin role TOML files."""
    paths = [*sorted((codex_home() / "agents").glob("*.toml")), *sorted((Path.cwd() / ".codex" / "agents").glob("*.toml"))]
    if registry:
        paths.append(ROOT / "standalone-agents" / f"codex-{name}.toml")
    text = codex_instructions(name, paths)
    if text is None:
        raise UsageError(f"No developer_instructions for the Codex role {name} in a role TOML file")
    return text


def declared_claude_agent(name: str) -> tuple[dict, Path] | None:
    """Return the entry an installed Claude plugin declares for name, with the install path it came from."""
    if ":" not in name:
        return None
    try:
        installed = json.loads((claude_home() / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    plugins = installed.get("plugins") if isinstance(installed, dict) else None
    if not isinstance(plugins, dict):
        return None
    plugin = name.split(":", 1)[0]
    for key, installs in plugins.items():
        if key.split("@", 1)[0] != plugin or not isinstance(installs, list):
            continue
        for install in installs:
            install_path = install.get("installPath") if isinstance(install, dict) else None
            if not isinstance(install_path, str):
                continue
            agents, problem = agent_guard.read_declaration(Path(install_path) / ".claude-plugin" / "model-roles.json")
            if agents is not None and name in agents:
                if problem is not None:
                    raise UsageError(f"The model roles declared for {name} are invalid: {problem}")
                return agents[name], Path(install_path)
    return None


def declared_codex_role(name: str) -> dict | None:
    """Return the entry the newest cached Codex plugin declares for name."""
    for path in agent_guard.cached_roles_files(codex_home()):
        agents, problem = agent_guard.read_declaration(path)
        if agents is not None and name in agents:
            if problem is not None:
                raise UsageError(f"The model roles declared in {path} are invalid: {problem}")
            return agents[name]
    return None


def declared_agent(name: str, host: str) -> tuple[dict, Path | None, str]:
    """Return the declared entry, its Claude definition file (None for Codex), and its instructions."""
    if host == "claude":
        found = declared_claude_agent(name)
        if found is None:
            raise UsageError(f"Unknown agent {name} for host {host}: use a registry agent or a role an installed plugin declares")
        entry, install = found
        definition = install / "agents" / f"{name.split(':', 1)[1]}.md"
        return entry, definition, definition_body(definition)
    entry = declared_codex_role(name)
    if entry is None:
        raise UsageError(f"Unknown agent {name} for host {host}: use a registry agent or a role an installed plugin declares")
    return entry, None, codex_body(name, registry=False)


def allowed_efforts(entry: dict, model: str) -> list[str]:
    """Return the levels from the entry's effort up to its max_effort in registry order, limited by the model's effort rule."""
    levels = REGISTRY["efforts"]
    lowest = entry["effort"]
    highest = entry.get("max_effort") or lowest
    rule = REGISTRY["effort_rules"].get(model)
    return [level for level in levels[levels.index(lowest) : levels.index(highest) + 1] if rule is None or level in rule]


def requested_efforts(model: str) -> list[str]:
    """Return every registry level the model's effort rule allows, with no entry range, for an effort the user named."""
    rule = REGISTRY["effort_rules"].get(model)
    return [level for level in REGISTRY["efforts"] if rule is None or level in rule]


def chosen_effort(requested: str | None, entry: dict, model: str, user_requested: bool = False) -> str:
    """Return the requested effort when the entry's range allows it, else the entry's own effort; refuse a level outside it.

    A user request replaces the range with the model's own effort rule, and refuses with the model and level named."""
    if user_requested:
        allowed = requested_efforts(model)
        effort = requested or entry["effort"]
        if effort not in allowed:
            raise UsageError(f"{effort} is not an effort {model} allows ({', '.join(allowed)}); no fallback ran")
        return effort
    if requested is None:
        return entry["effort"]
    allowed = allowed_efforts(entry, model)
    if requested not in allowed:
        raise UsageError(f"--effort {requested} is not allowed for {model}: use {' or '.join(allowed)}")
    return requested


def agent_run(args: argparse.Namespace, host: str) -> Run:
    """Resolve an agent on its host: its declaration, instructions, access, and cross-family fallback."""
    name = args.name
    table = REGISTRY["claude_agents"] if host == "claude" else REGISTRY["codex_agents"]
    if name in table:
        entry = table[name]
        definition = ROOT / "agents" / f"{name.rsplit(':', 1)[-1]}.md"
        body = definition_body(definition) if host == "claude" else codex_body(name, registry=True)
    else:
        entry, definition, body = declared_agent(name, host)
    fallback = entry.get("fallback")
    problem = agent_guard.entry_problem(entry) if isinstance(fallback, dict) else "has no fallback"
    if problem is None:
        problem = agent_guard.entry_problem(fallback)
    if problem is not None:
        raise UsageError(f"{name}: {problem}")
    if runner_for(fallback["model"]) == runner_for(entry["model"]):
        raise UsageError(f"{name}: the fallback {fallback['model']} must be the other model family")
    access = entry.get("access", "read")
    if access not in ("read", "write"):
        raise UsageError(f"{name}: access must be read or write")
    if access == "write" and not args.add_dirs:
        raise UsageError(f"{name} writes, so it needs --add-dir for each directory it may write")
    model = args.model or fallback["model"]
    return Run(
        target=AGENT_TARGET, role=None, capability=None, fallback=True, runner=runner_for(model),
        model=model, effort=chosen_effort(args.effort, fallback, model, args.user_requested), writing=access == "write",
        add_dirs=tuple(args.add_dirs),
        resume=args.resume, instructions=None, agent=name, body=body, web_tools=web_tools_in(definition), mcp=args.mcp,
    )
