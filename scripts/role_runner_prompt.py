from __future__ import annotations

import argparse
from pathlib import Path

import session_context
from role_runner_config import (
    CLAUDE_SCRATCH_RULE, CLAUDE_VALIDATION_COPY, MCP_NETWORK_RULE, NO_NETWORK_RULE, READ_SHELL_RULES, REVIEWER_BAN, ROLE_DEFINITIONS, ROLE_SENTENCES, ROLES, Run,
    VALIDATION_RULE, VALIDATION_SENTENCE, worker_sentence,
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


def shell_sentence(limited: bool, scratch: bool = False) -> list[str]:
    """Name the read-only shell commands a Claude run without --mcp may use; its permission rules match the command prefix."""
    if not limited:
        return []
    commands = ", ".join(f"`{rule[len('Bash('):-len(':*)')]}`" for rule in READ_SHELL_RULES)
    if scratch:
        return [
            f"The shell runs only these read-only commands: {commands}. It starts in your scratch folder, "
            "so name the repository with `git -C <repository>`; use file tools for other reads."
        ]
    return [
        f"The shell runs only these read-only commands from the working directory: {commands}. "
        "Do not prefix them with `git -C` or `cd`; use file tools for other reads."
    ]


def claude_scratch_sentence(run: Run, repository: str) -> list[str]:
    """Tell a read-only Claude run, which starts in its scratch folder, where the repository is and how to work on a copy."""
    if run.runner != "claude" or run.writing:
        return []
    text = CLAUDE_SCRATCH_RULE.format(repository=repository)
    return [text + (CLAUDE_VALIDATION_COPY.format(repository=repository) if run.validation else "")]


def capability_sentence(capability: str, mcp: bool = False) -> str:
    return (
        f"You are an assigned worker for the {capability} capability: start no agents, make no commit or push, "
        f"{network_rule(mcp)}, and follow the instructions and assignment below."
    )


def validation_body(body: str) -> str:
    """Replace the reviewer definition's ban on edits and on build, test, install, and network commands with the validation rule."""
    replaced, count = REVIEWER_BAN.subn(VALIDATION_RULE, body)
    if count != 1:
        raise ValueError("The reviewer definition no longer holds the edit and command ban that validation mode replaces")
    return replaced


def compose_prompt(role: str, assignment_text: str, root: Path, validation: bool = False, scratch_rule: list[str] = ()) -> str:
    """Build the full prompt: role sentence, role definition body, worker rules for a worker, then the assignment."""
    if role not in ROLES:
        raise ValueError(f"Unsupported role: {role}")
    body = role_body(role, root)
    sentence = VALIDATION_SENTENCE if validation else ROLE_SENTENCES[role]
    parts = [sentence, *scratch_rule, validation_body(body) if validation else body]
    if role == "worker":
        parts.append(session_context.assigned_workers_section(root))
    parts.append("## Assignment\n\n" + assignment_text.strip())
    return "\n\n".join(parts) + "\n"


def compose_capability_prompt(
    capability: str, instructions: str, assignment_text: str, root: Path, mcp: bool = False, limited_shell: bool = False,
    scratch_rule: list[str] = (),
) -> str:
    """Build a capability prompt: capability sentence, instructions body, worker rules, then the assignment."""
    parts = [
        capability_sentence(capability, mcp),
        *scratch_rule,
        *shell_sentence(limited_shell, bool(scratch_rule)),
        instructions,
        session_context.assigned_workers_section(root),
        "## Assignment\n\n" + assignment_text.strip(),
    ]
    return "\n\n".join(parts) + "\n"


def compose_agent_prompt(
    body: str, assignment_text: str, root: Path, mcp: bool = False, limited_shell: bool = False, scratch_rule: list[str] = (),
) -> str:
    """Build an agent prompt: the assigned-worker sentence, the agent instructions, worker rules, then the assignment."""
    parts = [
        worker_sentence(network_rule(mcp)),
        *scratch_rule,
        *shell_sentence(limited_shell, bool(scratch_rule)),
        body,
        session_context.assigned_workers_section(root),
        "## Assignment\n\n" + assignment_text.strip(),
    ]
    return "\n\n".join(parts) + "\n"


def compose(run: Run, args: argparse.Namespace, root: Path, repository: str) -> str:
    assignment_text = Path(args.assignment).read_text(encoding="utf-8")
    scratch_rule = claude_scratch_sentence(run, repository)
    limited_shell = run.runner == "claude" and not run.mcp and not run.validation
    if run.agent is not None:
        return compose_agent_prompt(run.body, assignment_text, root, run.mcp, limited_shell, scratch_rule)
    if run.capability is None:
        return compose_prompt(run.role, assignment_text, root, run.validation, scratch_rule)
    instructions = run.instructions.read_text(encoding="utf-8")
    body = without_frontmatter(instructions, run.instructions.as_posix())
    return compose_capability_prompt(run.capability, body, assignment_text, root, run.mcp, limited_shell, scratch_rule)
