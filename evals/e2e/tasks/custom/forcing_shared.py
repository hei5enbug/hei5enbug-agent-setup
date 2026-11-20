"""Shared checks of the forced-delegation tasks: a worker ran for the implementation, and the route it took."""

from __future__ import annotations

SPAWN_TOOL = "spawn_agent"
RESULT_PREVIEW = 160


def implementation_runs(ctx) -> list[dict]:
    return [d for d in ctx.view.get("delegations", []) if d.get("class") == "implementation"
            and d.get("completed", True) and not d.get("is_error")]


def worker_delegated(ctx):
    found = implementation_runs(ctx)
    kinds = [f"{d.get('kind')}:{d.get('type')}" for d in found]
    return bool(found), f"completed implementation delegations: {kinds or 'none'}", {"delegations": kinds}


def spawn_calls(ctx) -> list[dict]:
    return [call for call in ctx.view.get("tool_calls", []) if call.get("name") == SPAWN_TOOL]


def worker_route(ctx):
    """The spawn calls with the role, model, and effort they asked for and the start of the result, which holds the
    agent guard's reason when it denied the call; the other delegations by kind, type, and exit."""
    spawns = [{"agent_type": call["input"].get("subagent_type"), "model": call["input"].get("model"),
               "effort": call["input"].get("reasoning_effort"), "error": call.get("is_error"),
               "result": str(call.get("result_text") or "")[:RESULT_PREVIEW]} for call in spawn_calls(ctx)]
    others = [{"kind": d.get("kind"), "type": d.get("type"), "class": d.get("class"), "exit": d.get("exit"),
               "completed": d.get("completed")} for d in ctx.view.get("delegations", [])]
    return True, f"{len(spawns)} spawn call(s); delegations: {others or 'none'}", {"spawns": spawns, "delegations": others}
