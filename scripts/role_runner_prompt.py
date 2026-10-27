from __future__ import annotations

import argparse
from pathlib import Path

import session_context
from role_runner_config import (
    MCP_NETWORK_RULE, NO_NETWORK_RULE, READ_SHELL_RULES, ROLE_DEFINITIONS, ROLE_SENTENCES, ROLES, Run, worker_sentence,
)


def without_frontmatter(text: str, label: str) -> str:
    if text.startswith("---"):
        lines = text.splitlines()
        closing = next((index for index in range(1, len(lines)) if lines[index].rstrip() == "---"), None)
        if closing is None:
            raise ValueError(f"{label} has an unterminated frontmatter block")
        text = "\n".join(lines[closing + 1 :])
    return text.strip()


def role_body(role: str, root: Path) -> str:
    name = ROLE_DEFINITIONS.get(role, role)
    text = (root / "agents" / f"{name}.md").read_text(encoding="utf-8")
    return without_frontmatter(text, f"agents/{name}.md")


def network_rule(mcp: bool) -> str:
    """Return the network rule a prompt states: no network, or MCP and network for the external work only."""
    return MCP_NETWORK_RULE if mcp else NO_NETWORK_RULE


def shell_sentence(limited: bool) -> list[str]:
    """Name the read-only shell commands a Claude run without --mcp may use; its permission rules match the command prefix."""
    if not limited:
        return []
    commands = ", ".join(f"`{rule[len('Bash('):-len(':*)')]}`" for rule in READ_SHELL_RULES)
    return [
        f"The shell runs only these read-only commands from the working directory: {commands}. "
        "Do not prefix them with `git -C` or `cd`; use file tools for other reads."
    ]


def capability_sentence(capability: str, mcp: bool = False) -> str:
    return (
        f"You are an assigned worker for the {capability} capability: start no agents, make no commit or push, "
        f"{network_rule(mcp)}, and follow the instructions and assignment below."
    )


def compose_prompt(role: str, assignment_text: str, root: Path) -> str:
    """Build the full prompt: role sentence, role definition body, worker rules for a worker, then the assignment."""
    if role not in ROLES:
        raise ValueError(f"Unsupported role: {role}")
    parts = [ROLE_SENTENCES[role], role_body(role, root)]
    if role == "worker":
        parts.append(session_context.assigned_workers_section(root))
    parts.append("## Assignment\n\n" + assignment_text.strip())
    return "\n\n".join(parts) + "\n"


def compose_capability_prompt(
    capability: str, instructions: str, assignment_text: str, root: Path, mcp: bool = False, limited_shell: bool = False,
) -> str:
    """Build a capability prompt: capability sentence, instructions body, worker rules, then the assignment."""
    parts = [
        capability_sentence(capability, mcp),
        *shell_sentence(limited_shell),
        instructions,
        session_context.assigned_workers_section(root),
        "## Assignment\n\n" + assignment_text.strip(),
    ]
    return "\n\n".join(parts) + "\n"


def compose_agent_prompt(body: str, assignment_text: str, root: Path, mcp: bool = False, limited_shell: bool = False) -> str:
    """Build an agent prompt: the assigned-worker sentence, the agent instructions, worker rules, then the assignment."""
    parts = [
        worker_sentence(network_rule(mcp)),
        *shell_sentence(limited_shell),
        body,
        session_context.assigned_workers_section(root),
        "## Assignment\n\n" + assignment_text.strip(),
    ]
    return "\n\n".join(parts) + "\n"


def compose(run: Run, args: argparse.Namespace, root: Path) -> str:
    assignment_text = Path(args.assignment).read_text(encoding="utf-8")
    limited_shell = run.runner == "claude" and not run.mcp
    if run.agent is not None:
        return compose_agent_prompt(run.body, assignment_text, root, run.mcp, limited_shell)
    if run.capability is None:
        return compose_prompt(run.role, assignment_text, root)
    instructions = run.instructions.read_text(encoding="utf-8")
    body = without_frontmatter(instructions, run.instructions.as_posix())
    return compose_capability_prompt(run.capability, body, assignment_text, root, run.mcp, limited_shell)
