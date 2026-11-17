"""The depth of delegation, enforced in code: the main session, an area coordinator, and the workers it starts.

Only the main session may start an area coordinator. A coordinator may start implementation workers only, and a
worker under a coordinator may start nothing. The role runner marks the layer in `HEI5ENBUG_DELEGATION_LAYER` for the
child it starts: `coordinator` for an area coordinator and `worker` for any child a coordinator starts. A Claude Code
subagent of a coordinator shares its session environment, so the hook event's `agent_id` marks it as a worker.
Children that no coordinator started keep the rules they had.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

COORDINATOR_ROLE = "area-coordinator"
LAYER_ENV = "HEI5ENBUG_DELEGATION_LAYER"
MAIN, COORDINATOR, WORKER, CHILD = "main", "coordinator", "worker", "child"
WORKER_AGENT_TYPES = frozenset({
    "worker", "sonnet-worker", "hei5enbug-agent-setup:worker", "hei5enbug-agent-setup:sonnet-worker",
})
WORKER_RUNNER_TARGETS = frozenset({"worker", "implementation"})
ASSIGNED_ROLE_ENV = "HEI5ENBUG_ASSIGNED_ROLE"
PARENT_SESSION_ENV = "HEI5ENBUG_PARENT_SESSION"


def layer(event: Mapping | None = None, environ: Mapping[str, str] = os.environ) -> str:
    """The layer of the process that makes a launch: `main`, `coordinator`, `worker`, or another `child`."""
    marked = environ.get(LAYER_ENV, "")
    subagent = bool(isinstance(event, Mapping) and event.get("agent_id"))
    if marked == WORKER or (marked == COORDINATOR and subagent):
        return WORKER
    if marked == COORDINATOR:
        return COORDINATOR
    if subagent or environ.get(ASSIGNED_ROLE_ENV) or environ.get(PARENT_SESSION_ENV):
        return CHILD
    return MAIN


def child_layer(marker: str, environ: Mapping[str, str] = os.environ) -> str | None:
    """The layer the role runner gives a child it starts as `marker`, or None when the child stays an ordinary child."""
    if marker == COORDINATOR_ROLE:
        return COORDINATOR
    if environ.get(LAYER_ENV) in (COORDINATOR, WORKER):
        return WORKER
    return None


def launch_denial(current: str, kind: str, name: str) -> str | None:
    """Why a launch is not allowed from `current`, else None.

    `kind` is `agent` for an `Agent` or `spawn_agent` launch and `runner` for a `role_runner.py` target, and `name` is the
    agent type or the target."""
    if current == WORKER:
        return (
            "Denied: a worker under an area coordinator starts nothing. Do the assigned task yourself and return the "
            "changed paths, check results, and blockers."
        )
    if name == COORDINATOR_ROLE and current != MAIN:
        return "Denied: only the main session starts an area coordinator, and a coordinator never starts another."
    if current != COORDINATOR:
        return None
    allowed = WORKER_AGENT_TYPES if kind == "agent" else WORKER_RUNNER_TARGETS
    if name in allowed:
        return None
    return (
        f"Denied: an area coordinator starts implementation workers only, not `{name}`. "
        "Start the worker agent or `role_runner.py worker` for each task of the area."
    )
