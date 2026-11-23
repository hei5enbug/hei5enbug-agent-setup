from __future__ import annotations

import json
from pathlib import Path

from role_runner_config import (
    CLAUDE_SKILLS_OFF, CODEX_NETWORK_ON, CODEX_SKILLS_OFF, MCP_TOOL_RULE, READ_SHELL_RULES, SCRATCH_PROFILE,
    SKIP_GIT_REPO_CHECK, VALIDATION_PACKAGE_HOSTS, Run,
)


def sandbox_for(run: Run) -> str:
    return "workspace-write" if run.writing else "read-only"


def scoped_codex_config(run: Run, mcp_off: list[str]) -> list[str]:
    """A run without --mcp turns every listed MCP server off, and a writing run with --mcp also allows network."""
    if not run.mcp:
        return mcp_off
    return ["-c", CODEX_NETWORK_ON] if run.writing else []


def service_tier_config(run: Run) -> list[str]:
    """The Codex override for the requested service tier, or nothing when none was requested."""
    return ["-c", f'service_tier="{run.service_tier}"'] if run.service_tier else []


def scratch_profile_config(scratch: Path, network: bool) -> list[str]:
    """Return the Codex overrides that select a permission profile whose only writable path is the scratch folder."""
    table = f'{{extends=":read-only", filesystem={{{json.dumps(scratch.as_posix())}="write"}}'
    table += ", network={enabled=true}}" if network else "}"
    return ["-c", f'default_permissions="{SCRATCH_PROFILE}"', "-c", f"permissions.{SCRATCH_PROFILE}={table}"]


def sandbox_config(run: Run, scratch: Path | None) -> list[str]:
    """A writing run keeps its sandbox mode; a read-only run gets the scratch-folder profile in its place."""
    if run.writing:
        return ["-c", f'sandbox_mode="{sandbox_for(run)}"']
    if scratch is None:
        raise ValueError("A read-only Codex run needs a scratch folder")
    return scratch_profile_config(scratch, run.validation)


def codex_command(run: Run, cwd: str, result: str, mcp_off: list[str], scratch: Path | None = None) -> list[str]:
    command = ["codex"]
    if run.role == "researcher" or run.web_tools:
        command.append("--search")
    scoped = scoped_codex_config(run, mcp_off) + ([] if run.writing else list(CODEX_SKILLS_OFF))
    outside_repo = [] if run.writing else [SKIP_GIT_REPO_CHECK]
    if run.resume is not None:
        command += [
            "exec", "resume", run.resume, "-m", run.model,
            "-c", f'model_reasoning_effort="{run.effort}"', *service_tier_config(run),
            *sandbox_config(run, scratch), *outside_repo, *scoped,
        ]
        if run.writing and run.add_dirs:
            roots = [str(Path(directory).resolve()) for directory in run.add_dirs]
            command += ["-c", f"sandbox_workspace_write.writable_roots={json.dumps(roots)}"]
        command += ["--json", "-o", result, "-"]
        return command
    command += [
        "exec", "-m", run.model, "-c", f'model_reasoning_effort="{run.effort}"', *service_tier_config(run),
        *(["-s", sandbox_for(run)] if run.writing else sandbox_config(run, scratch)), *outside_repo, "-C", cwd, *scoped,
    ]
    for directory in run.add_dirs:
        command += ["--add-dir", directory]
    command += ["--json", "-o", result, "-"]
    return command


def edit_rules(directories: tuple[str, ...]) -> list[str]:
    """Return one Edit rule per approved directory: Claude Code applies Edit rules to Write and reads `//` as the filesystem root."""
    return [f"Edit(/{Path(directory).resolve().as_posix()}/**)" for directory in directories]


def claude_rules(run: Run) -> list[str]:
    """Return an agent or capability run's Claude rules: reads, the read-only shell, listed web tools, approved edits, and --mcp."""
    rules = ["Read", "Grep", "Glob", *READ_SHELL_RULES, *run.web_tools]
    if run.writing:
        rules += edit_rules(run.add_dirs)
    if run.writing or run.mcp:
        rules += ["Bash"]
    if run.mcp:
        rules += [MCP_TOOL_RULE]
    return rules


def claude_tools(rules: list[str]) -> list[str]:
    """Return the built-in tools the rules name, in first-use order, plus Write after Edit, whose rules also grant Write."""
    names: list[str] = []
    for rule in rules:
        name = rule.split("(", 1)[0]
        if name != MCP_TOOL_RULE and name not in names:
            names.append(name)
    if "Edit" in names:
        names.append("Write")
    return names


def claude_sandbox_settings(scratch: Path, network: bool) -> dict:
    """Return the settings that confine a Claude run's shell: the sandbox must start, no command may leave it, and only
    the scratch folder is writable. Network reaches the package index hosts for a validation run and nothing otherwise."""
    return {
        "sandbox": {
            "enabled": True, "failIfUnavailable": True, "allowUnsandboxedCommands": False, "excludedCommands": [],
            "filesystem": {"allowWrite": [scratch.as_posix()]},
            "network": {"allowedDomains": list(VALIDATION_PACKAGE_HOSTS) if network else [], "strictAllowlist": True},
        }
    }


def claude_scratch_rules(run: Run, allowed: list[str]) -> list[str]:
    """A validation run gets the whole shell, which its sandbox confines; any other read-only run keeps its rules."""
    return [*allowed, "Bash"] if run.validation and "Bash" not in allowed else allowed


def claude_command(run: Run, scratch: Path | None = None, session: str | None = None) -> list[str]:
    if run.agent is not None or run.capability is not None:
        allowed = claude_rules(run)
        tools = claude_tools(allowed)
        mode = "dontAsk"
    else:
        allowed = ["Read", "Grep", "Glob", *(["Bash"] if run.writing else []), *(edit_rules(run.add_dirs) if run.writing else [])]
        tools = claude_tools(allowed)
        mode = "dontAsk"
    if not run.writing:
        if scratch is None:
            raise ValueError("A read-only Claude run needs a scratch folder")
        allowed = claude_scratch_rules(run, allowed)
        tools = claude_tools(allowed)
    command = ["claude", "-p"]
    if run.resume is not None:
        command += ["--resume", run.resume]
    elif not run.writing:
        if session is None:
            raise ValueError("A fresh read-only Claude run needs a session id")
        command += ["--session-id", session]
    command += ["--model", run.model, "--effort", run.effort, "--output-format", "json"]
    if not run.writing:
        command += ["--verbose", CLAUDE_SKILLS_OFF]
    command += ["--tools", *tools]
    if not run.mcp:
        command += ["--strict-mcp-config"]
    command += ["--permission-mode", mode, "--allowedTools", *allowed]
    for directory in run.add_dirs:
        command += ["--add-dir", directory]
    if not run.writing:
        command += ["--settings", json.dumps(claude_sandbox_settings(scratch, run.validation), sort_keys=True)]
    return command
