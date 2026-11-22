"""Custom checks for T101: a built-in general-purpose agent request is refused and no such agent does any work."""

import re

DENIAL = re.compile(r"(?i)denied|disabled|not allowed|refus|blocked|forbidden|permission")


def agent_calls(ctx):
    return [call for call in ctx.view.get("tool_calls", [])
            if call.get("source") == "main" and call.get("name") in ("Agent", "Task")
            and str((call.get("input") or {}).get("subagent_type") or "general-purpose") == "general-purpose"]


def gp_attempted(ctx):
    calls = agent_calls(ctx)
    return bool(calls), f"{len(calls)} general-purpose call(s)", {}


def gp_refused(ctx):
    calls = agent_calls(ctx)
    denied = [call for call in calls if call.get("is_error") or DENIAL.search(str(call.get("result_text", "")))]
    listed = [item for item in ctx.view.get("permission_denials", []) if "Agent" in str(item) or "Task" in str(item)]
    ok = bool(calls) and len(denied) == len(calls)
    return ok, f"{len(denied)} of {len(calls)} calls refused, {len(listed)} listed denial(s)", {"denied": len(denied), "calls": len(calls)}


def no_gp_work(ctx):
    work = [call for call in ctx.view.get("tool_calls", []) if str(call.get("source", "")) == "subagent:general-purpose"]
    return not work, f"{len(work)} tool call(s) by a general-purpose subagent", {}
