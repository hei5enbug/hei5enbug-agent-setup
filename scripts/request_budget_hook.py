"""Hook that counts agent launches per user request and denies one past a cap or past the parallel limit.

`UserPromptSubmit` starts a new request and reports the parallel limit, and so does `Stop`, because a turn that ends is
followed by an automatic continuation, such as a goal or a Stop hook, that no prompt precedes. `PreToolUse` on the agent tool admits or denies
a launch, `PostToolUse` and `PostToolUseFailure` record how it ended, and `SubagentStop` stops counting a background
launch. Role runner runs are admitted by the role runner itself, through the same count. The hook fails open: a
session the state store cannot key is never denied.
"""

from __future__ import annotations

import json
import sys
import uuid

import hook_runtime
import parallel_limit
import plugin_toggles
import request_budget

AGENT_TOOLS = frozenset({"Agent", "Task", "spawn_agent"})
LIMIT_LINE = "Parallel agent limit: {limit} runs at once on this machine; the plugin denies a launch past it."


def deny(reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}


def agent_kind(tool_input: object) -> str:
    fields = tool_input if isinstance(tool_input, dict) else {}
    return str(fields.get("subagent_type") or fields.get("agent_type") or "default")


def response_failed(response: object) -> bool:
    """Whether a tool response says the launch failed: an error flag or key, or a JSON text with an error key."""
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except ValueError:
            return False
    return isinstance(response, dict) and bool(response.get("is_error") or response.get("error"))


def on_prompt(event: dict, who: tuple[str, str]) -> dict | None:
    if event.get("agent_id") or request_budget.approval_state.parent_session() is not None:
        return None
    request_budget.reset(who)
    line = LIMIT_LINE.format(limit=parallel_limit.current_limit(who[0], event.get("cwd") or "."))
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": line}}


def on_stop(event: dict, who: tuple[str, str]) -> None:
    """A turn of the main session ended: whatever continues the session next is a new request."""
    if event.get("agent_id") or request_budget.approval_state.parent_session() is not None:
        return None
    request_budget.reset(who)


def on_launch(event: dict, who: tuple[str, str]) -> dict | None:
    tool_input = event.get("tool_input")
    background = isinstance(tool_input, dict) and tool_input.get("run_in_background") is True
    run_id = str(event.get("tool_use_id") or uuid.uuid4())
    reason = request_budget.admit(
        who, agent_kind(tool_input), run_id, background=background, pid=parallel_limit.host_pid(),
    )
    return deny(reason) if reason else None


def on_end(event: dict, who: tuple[str, str], failed: bool) -> None:
    tool_input = event.get("tool_input")
    background = isinstance(tool_input, dict) and tool_input.get("run_in_background") is True
    request_budget.finish(
        who, agent_kind(tool_input), str(event.get("tool_use_id") or ""), ok=not failed, background=background,
    )


def handle(event: dict) -> dict | None:
    name = event.get("hook_event_name")
    who = request_budget.identity(event.get("session_id"))
    if who is None:
        return None
    if name == "UserPromptSubmit":
        return on_prompt(event, who)
    if name == "Stop":
        return on_stop(event, who)
    if name == "SubagentStop":
        request_budget.end_background(who, event.get("agent_type") if isinstance(event.get("agent_type"), str) else None)
        return None
    if event.get("tool_name") not in AGENT_TOOLS:
        return None
    if name == "PreToolUse":
        return on_launch(event, who)
    if name in ("PostToolUse", "PostToolUseFailure"):
        on_end(event, who, name == "PostToolUseFailure" or response_failed(event.get("tool_response")))
    return None


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (OSError, ValueError):
        return 0
    if not isinstance(event, dict) or plugin_toggles.detect_host() not in request_budget.HOSTS:
        return 0
    output = handle(event)
    if output:
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(hook_runtime.run("request_budget_hook.py", main))
