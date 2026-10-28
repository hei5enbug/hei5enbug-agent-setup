#!/usr/bin/env python3
"""Approval guard for covered CLI, MCP, and DataGrip writes, shared by Claude Code and Codex.

Reads run without approval, writes and sensitive reads ask once per session, and always calls ask every time.
Requests bundle session keys, secrets and forbidden state edits are denied, and pass leaves the host in charge.
Every verb and CLI table lives in the guard_* modules this entry point imports. DataGrip queries are classified
by datagrip_guard, which makes its own PreToolUse decision; this entry point records and consumes their approvals.
Production database reads (tabularis and DataGrip) follow db_read_policy, and this entry point records plan estimates.
The guard always exits 0; covered calls fail closed when their classification fails.
"""

import json
import shlex  # noqa: F401
import subprocess  # noqa: F401
import sys
from pathlib import Path

sys.dont_write_bytecode = sys.pycache_prefix is None
sys.path.insert(0, str(Path(__file__).resolve().parent))
from plugin_toggles import detect_host, enabled  # noqa: E402
import approval_state  # noqa: E402
from approval_state import Outcome  # noqa: E402
from guard_shell import (  # noqa: E402
    LOOKUP_TIMEOUT_SECONDS, WRAPPER, _datagrip, _digest, _lookup, _merge, read_only_command, tokenize, tool_words,
    unwrap_wrapper, wrap_command,
)
from guard_expand import _expand_raw_word  # noqa: E402
from guard_reads import _environment_filter  # noqa: E402
from guard_git import _git_probe  # noqa: E402
from guard_self import MAX_DEPTH, _request_args, _request_outcome, _runs_guard  # noqa: E402
from guard_proof import SELF_APPROVAL_REASON, _self_approval, _self_approval_reason  # noqa: E402
from guard_scripts import DISCARD_LABEL, _aggregate  # noqa: E402
import guard_dispatch  # noqa: E402
from guard_dispatch import TEMP_WRITE_EXE, _classify_argv, classify_text  # noqa: E402
import guard_tools  # noqa: E402
from guard_tools import (  # noqa: E402
    FAILURE_REASON, TABULARIS_TOOL, _classify_safely, _report_error, classify_file_tool, classify_mcp,
    classify_tabularis, mcp_tool_part, tabularis_connection,
)
from guard_permissions import (  # noqa: E402
    DATAGRIP_TOOL, EDIT_TOOLS, READ_REASON, _capture_plan, _claude_permission, _cwd, _deny_secret,
    _limits_command_outcome, _native_covers, _native_pre, _read_decision, _record_risk, codex_permission,
    native_ready,
)

# Calls fall into three tiers. A write asks once per session (WRITE_KEY) and a sensitive read asks once per session
# (SENSITIVE_KEY). The actions that ask every time are the always outcomes, which all set Outcome.every_time: calls that
# affect remote or production systems or destroy local data that cannot be recovered. They are destructive git push
# (except a lease-protected push to a feature branch, which is a session write),
# git clean and stash drop, git reset --hard and forced checkout or restore over uncommitted tracked changes, recursive
# removal of a protected or external path, destructive gh and database statements, remote infrastructure deletion,
# docker or podman removal against a remote engine, package publishing, destructive curl methods and MCP tools, Codex
# runs without sandbox protection, unclassifiable calls whose text names a destructive action, and guard classification
# failures. Disposable or recoverable local actions do not ask every time: docker removal on the local engine and a hard
# reset on a clean tracked tree are session writes, and removal or writes inside a temporary root pass. Everything else
# is a read, a pass, a write, or a denial.

POST_EVENTS = ("PostToolUse", "PostToolUseFailure")
EVENTS = ("PreToolUse", "PermissionRequest", *POST_EVENTS)
FILE_TOOLS = EDIT_TOOLS | {"Read", "apply_patch"}


def _decide(name, host, session, outcome, tool_use_id=None, tool_input=None, tool_name=None, cwd=None, event=None,
            wrapped=False):
    if name in POST_EVENTS:
        approval_state.after_call(host, session, outcome, tool_use_id, tool_name, tool_input)
        return None
    if outcome.kind == "forbidden":
        return approval_state.pre_output("deny", "; ".join(outcome.descriptions)) if name == "PreToolUse" else None
    if outcome.kind == "secret":
        return _deny_secret() if name == "PreToolUse" else None
    if name == "PreToolUse":
        if outcome.kind == "read":
            return _read_decision(host, outcome, tool_input)
        if outcome.kind in ("write", "always", "sensitive", "request"):
            if host == "codex" and _native_covers(tool_name, outcome) \
                    and approval_state.session_key(session) is not None and native_ready(event):
                return _native_pre(session, outcome, tool_input, wrapped) if tool_name == "Bash" else None
            return approval_state.pre_decision(host, session, outcome, tool_use_id)
        return None
    if name == "PermissionRequest":
        if host == "claude":
            return _claude_permission(session, outcome, tool_input, tool_name, cwd, event)
        return codex_permission(session, outcome, tool_use_id, tool_input, tool_name, event)
    return None


def handle(event, host):
    if not isinstance(event, dict):
        return None
    name = event.get("hook_event_name")
    session = event.get("session_id")
    approval_state.heartbeat(host, session, name)
    tool = event.get("tool_name")
    tool_use_id = event.get("tool_use_id")
    if name == "UserPromptSubmit":
        approval_state.reset_request_counts(host, session)
        output = approval_state.approve_prompt(host, session, event.get("prompt"))
        warning = approval_state.hooks_warning(host, session)
        if warning:
            if output is None:
                return {"hookSpecificOutput": {"hookEventName": name, "additionalContext": warning}}
            context = output["hookSpecificOutput"]["additionalContext"]
            output["hookSpecificOutput"]["additionalContext"] = warning + "\n" + context
        return output
    if name not in EVENTS or not isinstance(tool, str):
        return None
    if name == "PostToolUse" and tool in (DATAGRIP_TOOL, TABULARIS_TOOL):
        _capture_plan(host, session, tool, event)
    if tool == DATAGRIP_TOOL:
        if name in POST_EVENTS:
            outcome = _classify_safely(lambda: _datagrip().classify_query(event.get("tool_input")), tool)
            approval_state.after_call(host, session, outcome, tool_use_id, tool, event.get("tool_input"))
        elif name == "PreToolUse" and host == "claude" and enabled("datagrip_guard"):
            outcome = _classify_safely(lambda: _datagrip().classify_query(event.get("tool_input")), tool)
            _record_risk(host, session, tool_use_id, tool, outcome)
            if outcome.kind == "always":
                return approval_state.pre_decision(host, session, outcome, tool_use_id)
        return None
    tool_input = event.get("tool_input")
    wrapped = None
    if tool == "Bash":
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if not isinstance(command, str):
            return None
        wrapped = unwrap_wrapper(command)
        if wrapped is not None:
            command = wrapped
        outcome = _request_outcome(command, _cwd(event))
        reason = _self_approval_reason(command, _cwd(event)) if name == "PreToolUse" and outcome is None else None
        if reason:
            return approval_state.pre_output("deny", reason)
        outcome = outcome or _classify_safely(lambda: guard_dispatch.classify_text(command, _cwd(event)), command)
        limits = _limits_command_outcome(command, _cwd(event))
        if limits is not None and outcome.kind not in ("forbidden", "secret"):
            outcome = _merge("always", [outcome, limits]) if outcome.kind == "always" else limits
    elif tool.startswith("mcp__"):
        outcome = _classify_safely(lambda: guard_tools.classify_mcp(tool, tool_input, _cwd(event), host, session), tool)
    elif tool in FILE_TOOLS:
        outcome = _classify_safely(lambda: classify_file_tool(tool, tool_input, _cwd(event)), tool)
    else:
        return None
    if name == "PreToolUse":
        _record_risk(host, session, tool_use_id, tool, outcome)
    return _decide(name, host, session, outcome, tool_use_id, tool_input, tool, _cwd(event), event,
                   wrapped is not None)


def main() -> int:
    if len(sys.argv) > 1:
        try:
            if sys.argv[1] != "request" or approval_state.parent_session():
                raise ValueError("Only a main-session approval request is supported")
            outcome = _request_args(sys.argv[2:])
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 2
        print("Recorded session approval keys: " + "; ".join(outcome.keys))
        return 0
    try:
        event = json.loads(sys.stdin.buffer.read())
        host = detect_host()
        if isinstance(event, dict):
            approval_state.heartbeat(host, event.get("session_id"), event.get("hook_event_name"))
        if not enabled("approval_guard"):
            return 0
        output = handle(event, host)
    except Exception as error:
        if not isinstance(locals().get("event"), dict):
            return 0
        _report_error(error)
        if event.get("hook_event_name") != "PreToolUse":
            return 0
        outcome = Outcome("always", ["guard:unclassified:" + _digest(json.dumps(event, sort_keys=True))], [FAILURE_REASON],
                          every_time=True, critical=True)
        _record_risk(host, event.get("session_id"), event.get("tool_use_id"), event.get("tool_name"), outcome)
        output = approval_state.pre_decision(host, event.get("session_id"), outcome, event.get("tool_use_id"))
    if output is not None:
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
