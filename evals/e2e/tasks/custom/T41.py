"""Custom check for T41: the engine check ran, successfully, after the last edit of the date formatting code."""

from __future__ import annotations

import re

FORMATTING_FILE = "orders/dates.py"
ENGINE_CHECK = re.compile(r"scripts/check_engine\.py")
SHELL_WRITE = re.compile(r"sed\s+-[a-z]*i|perl\s+-[a-z]*i|\btee\b|>>?\s*\S*dates\.py|write_text|open\([^)]*['\"]w|\bpatch\b|git\s+(?:apply|checkout|restore)")
FILE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def edits_formatting(call):
    """True when the tool call changes the formatting file: a file tool on it, a patch that names it, or a shell write that names it."""
    data = call.get("input") or {}
    name = call.get("name")
    if name in FILE_TOOLS:
        return str(data.get("file_path", "")).endswith(FORMATTING_FILE)
    if name == "apply_patch":
        return FORMATTING_FILE in str(data.get("patch", ""))
    if name == "Bash":
        command = str(data.get("command", ""))
        return "dates.py" in command and bool(SHELL_WRITE.search(command))
    return False


def runs_engine_check(call):
    return call.get("name") == "Bash" and bool(ENGINE_CHECK.search(str((call.get("input") or {}).get("command", "")))) \
        and not call.get("is_error")


def engine_check_after_edit(ctx):
    calls = list(ctx.view.get("tool_calls", []))
    edits = [index for index, call in enumerate(calls) if edits_formatting(call)]
    checks = [index for index, call in enumerate(calls) if runs_engine_check(call)]
    if not edits:
        return False, "the formatting code was never edited", {"edits": [], "checks": checks}
    ok = any(index > edits[-1] for index in checks)
    return ok, f"last edit at call {edits[-1]}, engine check calls at {checks}", {"edits": edits, "checks": checks}
