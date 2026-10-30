from __future__ import annotations

import argparse
from pathlib import Path

from role_runner_agents import accepts_add_dir, runner_for
from role_runner_config import AGENT_TARGET, CAPABILITIES, MAX_BATCH, REVIEW_MODELS, ROLES, UsageError


def validate(args: argparse.Namespace) -> None:
    target = args.role
    is_role = target in ROLES
    is_agent = target == AGENT_TARGET
    if not is_role and not is_agent and target not in CAPABILITIES:
        raise UsageError(
            f"Unknown target: {target}. Roles: {', '.join(ROLES)}. Capabilities: {', '.join(CAPABILITIES)}. Or agent."
        )
    validate_request(args, target)
    if args.add_dirs and not accepts_add_dir(target):
        raise UsageError("--add-dir is allowed only for the worker role, writing capabilities, and agent mode")
    if args.timeout <= 0:
        raise UsageError("--timeout must be a positive number of seconds")
    if is_role and args.fallback:
        raise UsageError("--fallback is allowed only for a capability or agent")
    if is_agent and not args.fallback:
        raise UsageError("agent mode needs --fallback: primaries run in-host as subagents")
    if args.name is not None and not is_agent:
        raise UsageError("--name is allowed only for agent mode")
    if is_agent and not args.name:
        raise UsageError("agent mode needs --name")
    if is_role and args.mcp:
        raise UsageError("--mcp is allowed only for a capability or agent")
    if is_role and args.instructions is not None:
        raise UsageError("--instructions is allowed only for a capability")
    if is_agent and args.instructions is not None:
        raise UsageError("--instructions is not allowed in agent mode: the agent's definition supplies it")
    if not is_role and not is_agent and args.instructions is None:
        raise UsageError("--instructions is required for a capability")
    if args.instructions is not None and not Path(args.instructions).is_file():
        raise UsageError(f"Instructions file not found: {args.instructions}")
    if args.resume is not None and not args.resume:
        raise UsageError("--resume must name a session id")
    validate_pairs(args)


def validate_request(args: argparse.Namespace, target: str) -> None:
    """Check --model and --user-requested: only a user request opens --model to every target and any listed model."""
    if args.user_requested and args.model is None and args.effort is None:
        raise UsageError("--user-requested needs the --model or --effort the user named")
    if args.model is None:
        return
    if target != "reviewer" and not args.user_requested:
        raise UsageError("--model is allowed only for the reviewer role, or with --user-requested for a model the user named")
    if args.model not in REVIEW_MODELS:
        if args.user_requested:
            raise UsageError(
                f"--model {args.model} is not a model this runner can run ({', '.join(REVIEW_MODELS)}); no fallback ran"
            )
        raise UsageError(f"--model must be one of: {', '.join(REVIEW_MODELS)}")
    if target == "researcher" and runner_for(args.model) == "claude":
        raise UsageError(f"--model {args.model} cannot run the researcher role, which needs web search; no fallback ran")


def validate_pairs(args: argparse.Namespace) -> None:
    """Check every assignment and result pair before any child starts."""
    assignments, results = args.assignment, args.result
    if len(assignments) != len(results):
        raise UsageError("--assignment and --result must come in equal numbers")
    if len(assignments) > MAX_BATCH:
        raise UsageError(f"At most {MAX_BATCH} assignment and result pairs are allowed in one call")
    if len(assignments) > 1 and args.resume is not None:
        raise UsageError("--resume is allowed only with one assignment and result pair")
    resolved_results = [Path(result).resolve() for result in results]
    if len(set(resolved_results)) != len(resolved_results):
        raise UsageError("Every --result must name a different file")
    resolved_assignments = {Path(assignment).resolve() for assignment in assignments}
    if resolved_assignments & set(resolved_results):
        raise UsageError("--assignment and --result must name different files")
    for assignment in assignments:
        if not Path(assignment).is_file():
            raise UsageError(f"Assignment file not found: {assignment}")
    for result in results:
        path = Path(result)
        if path.is_dir() or not path.parent.is_dir():
            raise UsageError(f"Result must name a file in an existing directory: {result}")
