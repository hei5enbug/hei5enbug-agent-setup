"""Run-time limits and failure messages shared by every hook script.

Each hook gets half of the timeout its registration declares, counted from when its launcher started. A hook that
runs out of time stops and answers on its own: a hook whose output can deny a call denies it with a message that
says the machine is busy; every other hook ends with status 0 and no output so the agent's work continues. The
declared timeouts live here once, and a test compares them with every hooks file.
"""

from __future__ import annotations

import io
import json
import math
import os
import signal
import struct
import sys
import time

PLUGIN = "hei5enbug-agent-setup"
STARTED_AT = "HEI5ENBUG_HOOK_STARTED_AT"
MAX_AGE_SECONDS = 120
SLACK_SECONDS = 0.5
PROJECT_HOOK = "project_public_boundary_hook"

# The declared host timeout in seconds of each hook script on each event it is registered for.
DECLARED_TIMEOUTS = {
    ("session_context.py", "SessionStart"): 10,
    ("session_context.py", "SubagentStart"): 10,
    ("session_context.py", "UserPromptSubmit"): 5,
    ("approval_guard.py", "PreToolUse"): 10,
    ("approval_guard.py", "PermissionRequest"): 10,
    ("approval_guard.py", "PostToolUse"): 10,
    ("approval_guard.py", "PostToolUseFailure"): 10,
    ("approval_guard.py", "UserPromptSubmit"): 5,
    ("datagrip_guard.py", "PreToolUse"): 10,
    ("datagrip_guard.py", "PermissionRequest"): 10,
    ("public_boundary_hook.py", "PreToolUse"): 30,
    ("required_checks_hook.py", "PreToolUse"): 5,
    ("orca_placement_hook.py", "PreToolUse"): 5,
    ("orca_status_hook.py", "PostToolUse"): 10,
    ("orca_status_hook.py", "UserPromptSubmit"): 10,
    ("orca_status_hook.py", "Stop"): 10,
    ("language_guard.py", "Stop"): 5,
    ("language_guard.py", "PostToolUse"): 5,
    ("final_report_hook.py", "Stop"): 5,
    ("agent_guard.py", "PreToolUse"): 5,
    (PROJECT_HOOK, "PreToolUse"): 30,
}
# The hook scripts whose output can deny a call or a permission request, with the style of the denial: a JSON
# decision on the event's output, or exit status 2 with the reason on stderr.
DENY_STYLES = {
    "approval_guard.py": "json",
    "datagrip_guard.py": "json",
    "orca_placement_hook.py": "json",
    "agent_guard.py": "json",
    "public_boundary_hook.py": "exit",
    PROJECT_HOOK: "exit",
}
DENY_EVENTS = frozenset({"PreToolUse", "PermissionRequest"})
TITLES = {
    "approval_guard.py": "approval guard",
    "datagrip_guard.py": "DataGrip guard",
    "orca_placement_hook.py": "Orca placement hook",
    "agent_guard.py": "agent guard",
    "public_boundary_hook.py": "public boundary hook",
    PROJECT_HOOK: "public boundary project hook",
    "required_checks_hook.py": "required checks hook",
    "orca_status_hook.py": "Orca status hook",
    "language_guard.py": "language guard",
    "final_report_hook.py": "final report hook",
    "session_context.py": "session context hook",
}
SKIPPED = {
    "approval_guard.py": "could not finish its check of this call",
    "datagrip_guard.py": "skipped the query check",
    "orca_placement_hook.py": "skipped the Orca placement check",
    "agent_guard.py": "skipped the subagent check",
    "public_boundary_hook.py": "skipped the public boundary check",
    PROJECT_HOOK: "skipped the public boundary check",
    "required_checks_hook.py": "skipped the reminder about required checks",
    "orca_status_hook.py": "skipped the Orca status update",
    "language_guard.py": "skipped the language check",
    "final_report_hook.py": "skipped the final report check",
    "session_context.py": "loaded no instructions",
}

_deadline: float | None = None


class HookTimeout(BaseException):
    """Raised by the timer when a hook used up its time; it is not an Exception so no handler swallows it."""


def title_of(script: str) -> str:
    return TITLES.get(script, script)


def declared_timeout(script: str, event: object) -> float | None:
    """The declared timeout of a hook on an event; the smallest of its timeouts when the event is unknown."""
    found = DECLARED_TIMEOUTS.get((script, event))
    if found is not None:
        return found
    every = [value for (name, _), value in DECLARED_TIMEOUTS.items() if name == script]
    return min(every) if every else None


def seconds_text(value: float) -> str:
    return f"{value:g}"


def busy_message(script: str, event: object, budget: float) -> str:
    limit = seconds_text(budget)
    if event == "PermissionRequest":
        outcome, subject = "the request was denied", "permission request"
    else:
        outcome, subject = "the call did not run", "tool call"
    return (
        f"{PLUGIN} {title_of(script)} could not finish checking this {subject} within {limit} seconds because the "
        f"machine is busy, so {outcome}. Retry after the load drops, or check which sessions are using the machine."
    )


def error_message(script: str, error: BaseException | str) -> str:
    name = error if isinstance(error, str) else type(error).__name__
    skipped = SKIPPED.get(script, "skipped its check")
    return (
        f"{PLUGIN} {title_of(script)} hit an internal error ({name}), so it {skipped}. Run the step again; "
        f"if it repeats, report the error name and the hook."
    )


def report_error(script: str, error: BaseException | str) -> None:
    """Tell the user a hook failed inside, in one line without a traceback."""
    print(error_message(script, error), file=sys.stderr)


def timeout_result(script: str, event: object, budget: float) -> tuple[str, str, int]:
    """The stdout text, stderr text, and exit status of a hook that ran out of time."""
    if event not in DENY_EVENTS or script not in DENY_STYLES:
        return "", "", 0
    message = busy_message(script, event, budget)
    if DENY_STYLES[script] == "exit":
        return "", message + "\n", 2
    if event == "PermissionRequest":
        output = {"hookSpecificOutput": {
            "hookEventName": event, "decision": {"behavior": "deny", "message": message}}}
    else:
        output = {"hookSpecificOutput": {
            "hookEventName": event, "permissionDecision": "deny", "permissionDecisionReason": message}}
    return json.dumps(output, ensure_ascii=False) + "\n", "", 0


def linux_start(stat_text: str, uptime_text: str, now: float, ticks_per_second: float) -> float | None:
    """The epoch start of a process from its /proc stat text and the machine uptime text read at `now`."""
    try:
        fields = stat_text[stat_text.rindex(")") + 2 :].split()
        started = int(fields[19]) / ticks_per_second
        return now - float(uptime_text.split()[0]) + started
    except (ValueError, IndexError):
        return None


def process_start(now: float) -> float | None:
    """When this process started, read without starting a process; None when the platform does not say."""
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/self/stat", encoding="utf-8") as stat, open("/proc/uptime", encoding="utf-8") as uptime:
                return linux_start(stat.read(), uptime.read(), now, os.sysconf("SC_CLK_TCK"))
        if sys.platform == "darwin":
            import ctypes

            buffer = ctypes.create_string_buffer(136)
            size = ctypes.CDLL("/usr/lib/libproc.dylib").proc_pidinfo(os.getpid(), 3, 0, buffer, 136)
            if size == 136:
                seconds, microseconds = struct.unpack_from("<QQ", buffer, 120)
                return seconds + microseconds / 1e6
    except (OSError, ValueError, AttributeError, struct.error):
        return None
    return None


def started_at(now: float) -> float:
    """When the hook's launcher started: the variable the launcher sets, else this process's own start, else now."""
    candidates = []
    try:
        candidates.append(float(os.environ.get(STARTED_AT, "")))
    except ValueError:
        pass
    if not candidates:
        found = process_start(now)
        if found is not None:
            candidates.append(found)
    for value in candidates:
        if math.isfinite(value) and -1 <= now - value <= MAX_AGE_SECONDS:
            return min(value, now)
    return now


def remaining() -> float | None:
    """Seconds until the active deadline, or None when no deadline is running."""
    return None if _deadline is None else _deadline - time.time()


def call_timeout(default: float) -> float:
    """The timeout for a child process: `default` without a deadline, else just past it so the deadline answers first."""
    left = remaining()
    return default if left is None else max(left, 0) + SLACK_SECONDS


def _event_name(raw: bytes) -> object:
    try:
        event = json.loads(raw)
    except ValueError:
        return None
    name = event.get("hook_event_name") if isinstance(event, dict) else None
    return name if isinstance(name, str) else None


def _on_alarm(signum, frame) -> None:
    raise HookTimeout


def _disarm() -> None:
    try:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, signal.SIG_IGN)
    except (ValueError, OSError):
        pass


def _exit_code(error: SystemExit) -> int:
    code = error.code
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    print(code, file=sys.stderr)
    return 1


def _stream() -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="replace", newline="")


def _flush(buffer: io.TextIOWrapper, real) -> None:
    buffer.flush()
    data = buffer.buffer.getvalue()
    if data:
        real.buffer.write(data)
        real.buffer.flush()


def verify_cache() -> None:
    """Remove the interpreter cache when another user owns it or group or others can write it."""
    state = os.environ.get("XDG_STATE_HOME") or (os.path.join(os.path.expanduser("~"), ".local", "state"))
    if not os.path.isabs(state):
        return
    path = os.path.join(state, PLUGIN, "interpreter", "cache")
    try:
        info = os.lstat(path)
        if info.st_uid != os.getuid() or info.st_mode & 0o022 or os.path.islink(path):
            os.unlink(path)
    except OSError:
        return


def run(script: str, main) -> int:
    """Run a hook's `main` within its time limit and return its exit status.

    The input is read first so the event names the limit, then handed to `main` as its standard input. The output of
    `main` is held until it returns so a timeout never leaves half an answer.
    """
    global _deadline
    raw = sys.stdin.buffer.read()
    event = _event_name(raw)
    verify_cache()
    declared = declared_timeout(script, event)
    real_out, real_err = sys.stdout, sys.stderr
    if declared is None:
        sys.stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8", errors="replace")
        return _finish(script, main)
    budget = declared / 2
    now = time.time()
    _deadline = started_at(now) + budget
    left = _deadline - now
    if left <= 0:
        return _emit(script, event, budget, real_out, real_err)
    sys.stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8", errors="replace")
    out, err = _stream(), _stream()
    sys.stdout, sys.stderr = out, err
    code = 0
    try:
        try:
            signal.signal(signal.SIGALRM, _on_alarm)
            signal.setitimer(signal.ITIMER_REAL, left)
        except (ValueError, OSError):
            raise HookTimeout from None
        try:
            code = main()
        except SystemExit as error:
            code = _exit_code(error)
        except Exception as error:
            report_error(script, error)
            code = 1
        _disarm()
    except HookTimeout:
        _disarm()
        sys.stdout, sys.stderr = real_out, real_err
        return _emit(script, event, budget, real_out, real_err)
    finally:
        sys.stdout, sys.stderr = real_out, real_err
    _flush(out, real_out)
    _flush(err, real_err)
    return code if isinstance(code, int) else 0


def _finish(script: str, main) -> int:
    try:
        code = main()
    except SystemExit as error:
        return _exit_code(error)
    except Exception as error:
        report_error(script, error)
        return 1
    return code if isinstance(code, int) else 0


def _emit(script: str, event: object, budget: float, real_out, real_err) -> int:
    text, error_text, code = timeout_result(script, event, budget)
    if text:
        real_out.write(text)
        real_out.flush()
    if error_text:
        real_err.write(error_text)
        real_err.flush()
    return code
