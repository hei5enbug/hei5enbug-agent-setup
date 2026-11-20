"""Informational hook facts of one run: how long the plugin's hooks take and which tool calls they denied.

Neither host's records time a hook: the Claude Code stream lists hook starts and responses without a clock, and the Codex
rollout and `exec` stream list no hook run. So the time is a replay: each recorded tool call is sent again to the
PreToolUse and PostToolUse hooks of the run's exported plugin that match its tool, with the environment of a measurement
run, and the wall time of each hook process is measured. Denials come from the Claude Code stream's hook responses and,
on both hosts, from the replay's own decisions. The numbers describe the hooks alone and are not a part of any verdict."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

HOOK_FILES = {"claude": ("hooks.json", "claude-hooks.json"), "codex": ("hooks.json", "codex-hooks.json")}
TIMED_EVENTS = ("PreToolUse", "PostToolUse")
TOOL_ALIASES = {"spawn_agent": "Agent"}
HOOK_TIMEOUT_SECONDS = 30.0
REASON_LIMIT = 200
ABSOLUTE_PATH = re.compile(r"(?<![\w.:/-])(?:/[\w.@+-]+){2,}")
MEASUREMENT_ENV = {"CLAUDE_PLUGIN_OPTION_APPROVAL_GUARD": "false", "HEI5ENBUG_APPROVAL_GUARD": "false"}


def scrub(text: str) -> str:
    return ABSOLUTE_PATH.sub("<path>", " ".join(str(text).split()))[:REASON_LIMIT]


def plugin_hooks(plugin_dir: Path, host: str) -> list[dict[str, str | None]]:
    """The PreToolUse and PostToolUse hooks the plugin lists for a host: event, tool matcher, and command."""
    found = []
    for name in HOOK_FILES[host]:
        path = plugin_dir / "hooks" / name
        if not path.is_file():
            continue
        for event, entries in (json.loads(path.read_text(encoding="utf-8")).get("hooks") or {}).items():
            if event not in TIMED_EVENTS:
                continue
            for entry in entries:
                for hook in entry.get("hooks", []):
                    if hook.get("type") == "command":
                        found.append({"event": event, "matcher": entry.get("matcher"), "command": hook["command"]})
    return found


def matches(hook: Mapping[str, Any], tool: str) -> bool:
    return hook["matcher"] is None or re.search(hook["matcher"], tool) is not None


def decision_reason(output: str) -> str | None:
    """The reason of a deny or block decision that a hook printed, else None."""
    try:
        body = json.loads(output)
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    inner = body.get("hookSpecificOutput") if isinstance(body.get("hookSpecificOutput"), dict) else {}
    if inner.get("permissionDecision") == "deny":
        return scrub(inner.get("permissionDecisionReason") or "deny")
    if body.get("decision") == "block":
        return scrub(body.get("reason") or "block")
    return None


def replay(plugin_dir: Path, host: str, calls: Sequence[Mapping[str, Any]], cwd: Path, extra_env: Mapping[str, str] | None = None
           ) -> dict[str, Any]:
    """Send each recorded call to the matching hooks and return the hook count, total and slowest seconds, and denials."""
    env = {**os.environ, **MEASUREMENT_ENV, "CLAUDE_PLUGIN_ROOT": str(plugin_dir), **(extra_env or {})}
    hooks = plugin_hooks(plugin_dir, host)
    runs, denials = [], []
    for call in calls:
        tool = TOOL_ALIASES.get(str(call.get("name")), str(call.get("name")))
        for hook in (h for h in hooks if matches(h, tool)):
            payload = {"hook_event_name": hook["event"], "tool_name": tool, "tool_input": call.get("input") or {},
                       "tool_use_id": str(call.get("id") or ""), "cwd": str(cwd), "session_id": "replay"}
            started = time.perf_counter()
            try:
                done = subprocess.run(["sh", "-c", str(hook["command"])], input=json.dumps(payload), capture_output=True, text=True,
                                      env=env, cwd=cwd, timeout=HOOK_TIMEOUT_SECONDS, check=False)
                output = done.stdout
            except (OSError, subprocess.TimeoutExpired):
                output = ""
            seconds = time.perf_counter() - started
            script = str(hook["command"]).rsplit(" ", 1)[-1]
            runs.append((seconds, f"{hook['event']}:{tool}:{script}"))
            reason = decision_reason(output)
            if reason:
                denials.append({"hook": f"{hook['event']}:{script}", "tool": tool, "reason": reason})
    slowest = max(runs, default=(0.0, None))
    return {"replayed_hooks": len(runs), "replay_total_seconds": round(sum(s for s, _ in runs), 3),
            "replay_slowest_seconds": round(slowest[0], 3), "replay_slowest": slowest[1], "replay_denials": denials}


def stream_hook_facts(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Hook counts and denials from the Claude Code stream, whose hook events hold no time."""
    responses = [e for e in events if e.get("type") == "system" and e.get("subtype") == "hook_response"]
    failed = [e for e in responses if e.get("outcome") not in (None, "success")]
    denials = []
    for event in responses:
        reason = decision_reason(str(event.get("output") or event.get("stdout") or ""))
        if reason:
            denials.append({"hook": str(event.get("hook_name")), "reason": reason})
    return {"stream_hook_responses": len(responses), "stream_hook_failures": len(failed), "stream_denials": denials}


def run_facts(result_dir: Path, host: str, plugin_dir: Path, repo: Path) -> dict[str, Any]:
    view = json.loads((result_dir / "view.json").read_text(encoding="utf-8"))
    facts = replay(plugin_dir, host, view.get("tool_calls", []), repo, {"CODEX_HOME": str(result_dir / "codex-home")})
    stream = result_dir / "stream.jsonl"
    if host == "claude" and stream.is_file():
        events = [json.loads(line) for line in stream.read_text(encoding="utf-8").splitlines() if line.strip().startswith("{")]
        facts.update(stream_hook_facts(events))
    return facts
