"""Per-run metrics.json: outcome, tokens, cost, tool use, retries, handoff, and plugin checks."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .config import INLINE_PLUGIN_SOURCE, INSTALLED_PLUGIN_KEY, MOD_MARKER, PLUGIN_NAME, STATUS_TIMED_OUT, STATUS_USAGE_LIMITED
from .transcript import init_event, mod_marker_present, result_event
from .usage import agent_models


def stream_facts(events: list[dict[str, Any]]) -> dict[str, Any]:
    init, result = init_event(events) or {}, result_event(events) or {}
    return {
        "session_id": init.get("session_id") or result.get("session_id"),
        "permission_mode": init.get("permissionMode"),
        "model": init.get("model"),
        "plugins": init.get("plugins") if isinstance(init.get("plugins"), list) else [],
        "has_result": bool(result),
        "is_error": bool(result.get("is_error")),
        "subtype": result.get("subtype"),
        "total_cost_usd": result.get("total_cost_usd"),
        "duration_api_ms": result.get("duration_api_ms"),
        "num_turns": result.get("num_turns"),
    }


def plugin_checks(
    facts: dict[str, Any], expected_path: str, transcript_events: list[dict[str, Any]], subagents: list[dict[str, Any]],
) -> dict[str, Any]:
    plugins = facts.get("plugins") or []
    inline = [p for p in plugins if p.get("name") == PLUGIN_NAME and p.get("source") == INLINE_PLUGIN_SOURCE]
    return {
        "loaded_from_export": any(str(p.get("path")) == expected_path for p in inline),
        "installed_absent": not any(p.get("source") == INSTALLED_PLUGIN_KEY for p in plugins),
        "mod_marker_present": mod_marker_present(transcript_events, MOD_MARKER),
        "subagent_models": agent_models(subagents),
        "permission_mode": facts.get("permission_mode"),
    }


def tool_counts(view: dict[str, Any]) -> dict[str, dict[str, int]]:
    main: Counter[str] = Counter()
    sub: Counter[str] = Counter()
    for call in view["tool_calls"]:
        (main if call["source"] == "main" else sub)[call["name"]] += 1
    return {"main": dict(main), "subagent": dict(sub), "total": dict(main + sub)}


def _failed(call: dict[str, Any]) -> bool:
    return bool(call["is_error"]) or call["result_text"].startswith("Exit code ")


def count_retries(view: dict[str, Any]) -> dict[str, int]:
    """Repeated failing Bash commands, Agent relaunches after an error, and role_runner reruns after a non-zero exit."""
    calls = view["tool_calls"]
    bash = agent = 0
    failed_commands: set[tuple[str, str]] = set()
    errored_agents: set[str] = set()
    for call in calls:
        if call["name"] == "Bash":
            command = str(call["input"].get("command", ""))
            key = (call["source"], command)
            if "role_runner.py" in command:
                continue
            if key in failed_commands:
                bash += 1
            if _failed(call):
                failed_commands.add(key)
        elif call["name"] in ("Agent", "Task"):
            agent_type = str(call["input"].get("subagent_type", ""))
            if agent_type in errored_agents:
                agent += 1
            if call["is_error"]:
                errored_agents.add(agent_type)
    runner = _role_runner_retries(view["delegations"])
    return {"bash": bash, "agent": agent, "role_runner": runner, "total": bash + agent + runner}


def _role_runner_retries(delegations: list[dict[str, Any]]) -> int:
    failed: set[str] = set()
    reruns = 0
    for item in delegations:
        if item["kind"] != "role_runner":
            continue
        if item["type"] in failed:
            reruns += 1
        if item["exit"]:
            failed.add(item["type"])
    return reruns


def runner_calls(view: dict[str, Any]) -> dict[str, dict[str, int]]:
    table: dict[str, Counter[str]] = {}
    for item in view["delegations"]:
        if item["kind"] == "role_runner":
            table.setdefault(item["type"], Counter())[str(item["exit"])] += 1
    return {role: dict(counts) for role, counts in table.items()}


def launches_by_type(view: dict[str, Any]) -> dict[str, int]:
    return dict(Counter(item["type"] for item in view["delegations"] if item["kind"] == "agent"))


def handoff(grade: dict[str, Any] | None) -> dict[str, Any]:
    constraints = (grade or {}).get("constraints") or []
    missing = sum(len(item.get("missing_in", [])) for item in constraints)
    traced = sorted({check for item in constraints for check in item.get("traced_failures", [])})
    return {"constraints": len(constraints), "missing": missing, "traced_failures": traced}


def rubric_summary(task: dict[str, Any], rubric: dict[str, Any] | None) -> dict[str, Any] | None:
    if not task.get("rubric"):
        return None
    return rubric or {"scores": {}, "mean": None, "passed": False, "error": "rubric not run"}


def merged_success(grade: dict[str, Any] | None, task: dict[str, Any], rubric: dict[str, Any] | None) -> bool:
    if not grade or not grade.get("success"):
        return False
    return True if not task.get("rubric") else bool(rubric and rubric.get("passed"))


def build_metrics(
    *, run: dict[str, Any], task: dict[str, Any], view: dict[str, Any], facts: dict[str, Any],
    claude_report: dict[str, Any], codex_report: dict[str, Any], grade: dict[str, Any] | None,
    rubric: dict[str, Any] | None, checks: dict[str, Any], usage_source: str,
) -> dict[str, Any]:
    grade = grade or {}
    return {
        "run_id": run["run_id"], "task": run["task"], "variant": run["variant"], "rep": run["rep"], "status": run["status"],
        "success": merged_success(grade, task, rubric),
        "correctness": grade.get("correctness"), "test_pass_rate": grade.get("test_pass_rate"),
        "regressions": grade.get("regressions"), "rubric": rubric_summary(task, rubric),
        "tokens": {"claude": claude_report["tokens"], "codex": codex_report["tokens"], "usage_source": usage_source},
        "cost": {
            "claude_total_cost_usd": facts.get("total_cost_usd"),
            "claude_list_cost_usd": claude_report["list_cost_usd"],
            "codex_list_cost_usd_estimate": codex_report["list_cost_usd_estimate"],
            "codex_is_estimate": True,
            "unpriced_models": sorted(set(claude_report["unpriced_models"]) | set(codex_report["unpriced_models"])),
        },
        "wall_seconds": run.get("wall_seconds"), "duration_api_ms": facts.get("duration_api_ms"),
        "num_turns": facts.get("num_turns"),
        "tool_calls_by_tool": tool_counts(view), "subagent_launches_by_type": launches_by_type(view),
        "role_runner_calls": runner_calls(view), "retries": count_retries(view),
        "approval_prompts": len(view["approvals"]), "permission_denials": len(view["permission_denials"]),
        "handoff": handoff(grade), "attempts": run.get("attempts", 1),
        "timed_out": run["status"] == STATUS_TIMED_OUT or bool(run.get("timed_out")),
        "usage_limited": run["status"] == STATUS_USAGE_LIMITED, "plugin": checks,
    }
