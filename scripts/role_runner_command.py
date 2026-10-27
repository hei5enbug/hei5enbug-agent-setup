from __future__ import annotations

import json
from pathlib import Path

from role_runner_config import (
    CLAUDE_SKILLS_OFF, CODEX_NETWORK_ON, CODEX_SKILLS_OFF, MCP_TOOL_RULE, READ_SHELL_RULES, Run,
)


def sandbox_for(run: Run) -> str:
    return "workspace-write" if run.writing else "read-only"


def scoped_codex_config(run: Run, mcp_off: list[str]) -> list[str]:
    """A run without --mcp turns every listed MCP server off, and a writing run with --mcp also allows network."""
    if not run.mcp:
        return mcp_off
    return ["-c", CODEX_NETWORK_ON] if run.writing else []


def codex_command(run: Run, cwd: str, result: str, mcp_off: list[str]) -> list[str]:
    command = ["codex"]
    if run.role == "researcher" or run.web_tools:
        command.append("--search")
    sandbox = sandbox_for(run)
    scoped = scoped_codex_config(run, mcp_off) + ([] if run.writing else list(CODEX_SKILLS_OFF))
    if run.resume is not None:
        command += [
            "exec", "resume", run.resume, "-m", run.model,
            "-c", f'model_reasoning_effort="{run.effort}"', "-c", f'sandbox_mode="{sandbox}"', *scoped,
        ]
        if run.writing and run.add_dirs:
            roots = [str(Path(directory).resolve()) for directory in run.add_dirs]
            command += ["-c", f"sandbox_workspace_write.writable_roots={json.dumps(roots)}"]
        command += ["--json", "-o", result, "-"]
        return command
    command += [
        "exec", "-m", run.model, "-c", f'model_reasoning_effort="{run.effort}"', "-s", sandbox, "-C", cwd, *scoped,
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


def claude_command(run: Run) -> list[str]:
    if run.agent is not None or run.capability is not None:
        allowed = claude_rules(run)
        tools = claude_tools(allowed)
        mode = "dontAsk"
    else:
        allowed = ["Read", "Grep", "Glob", *(["Bash"] if run.writing else []), *(edit_rules(run.add_dirs) if run.writing else [])]
        tools = claude_tools(allowed)
        mode = "dontAsk"
    command = ["claude", "-p"]
    if run.resume is not None:
        command += ["--resume", run.resume]
    command += ["--model", run.model, "--effort", run.effort, "--output-format", "json"]
    if not run.writing:
        command += [CLAUDE_SKILLS_OFF]
    command += ["--tools", *tools]
    if not run.mcp:
        command += ["--strict-mcp-config"]
    command += ["--permission-mode", mode, "--allowedTools", *allowed]
    for directory in run.add_dirs:
        command += ["--add-dir", directory]
    return command
