"""PreToolUse hook for Bash: run the public boundary, required checks, and Orca placement checks in one process.

Each check runs on the same input in that order, within half of the timeout it declares, the budget its own process
has when it runs alone. The first deny ends the run and is returned with the name of the check that denied. A check
that raises, or runs out of its budget, answers as it does alone and the remaining checks still run. A check answers
a deny with exit status 2 or with a `permissionDecision` of `deny` in its output, and a failure of any other kind
never blocks. Output of passing checks, a notice or a reminder, is merged into one answer.
"""

from __future__ import annotations

import importlib
import json
import sys
import time
from dataclasses import dataclass

import hook_runtime

EVENT = "PreToolUse"
BLOCK_EXIT = 2


@dataclass(frozen=True)
class Check:
    script: str
    module: str
    needs: tuple[str, ...] = ()
    limit: float | None = None

    def budget(self) -> float:
        if self.limit is not None:
            return self.limit
        return hook_runtime.DECLARED_TIMEOUTS[(self.script, EVENT)] / 2

    def applies_to(self, text: str) -> bool:
        return not self.needs or any(word in text for word in self.needs)

    def main(self):
        return importlib.import_module(self.module).main()


CHECKS = (
    Check("public_boundary_hook.py", "public_boundary_hook"),
    Check("required_checks_hook.py", "required_checks_hook"),
    Check("orca_placement_hook.py", "orca_placement_hook", needs=("orca", "EnterWorktree")),
)


def named(script: str, reason: str) -> str:
    return f"Denied by {script}: {reason}"


def parsed(text: str) -> dict:
    try:
        value = json.loads(text)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def denial(script: str, result: hook_runtime.CheckResult) -> str | None:
    """The reason a check denied the call, or None when it did not."""
    if result.code == BLOCK_EXIT:
        return result.stderr.strip()
    if result.code != 0:
        return None
    specific = parsed(result.stdout).get("hookSpecificOutput")
    if isinstance(specific, dict) and specific.get("permissionDecision") == "deny":
        return str(specific.get("permissionDecisionReason", ""))
    return None


def merged(results: list[tuple[str, hook_runtime.CheckResult]], reason: str | None) -> dict:
    """One output from the answers of the checks that did not end the run, plus the deny when there is one."""
    messages: list[str] = []
    contexts: list[str] = []
    for script, result in results:
        output = parsed(result.stdout) if result.code == 0 else {}
        if isinstance(output.get("systemMessage"), str):
            messages.append(output["systemMessage"])
        specific = output.get("hookSpecificOutput")
        if isinstance(specific, dict) and isinstance(specific.get("additionalContext"), str):
            contexts.append(specific["additionalContext"])
        if result.code not in (0, BLOCK_EXIT) and result.stderr.strip():
            messages.append(result.stderr.strip())
    specific = {"hookEventName": EVENT}
    if contexts:
        specific["additionalContext"] = "\n".join(contexts)
    if reason is not None:
        specific["permissionDecision"] = "deny"
        specific["permissionDecisionReason"] = reason
    output: dict = {}
    if messages:
        output["systemMessage"] = "\n".join(messages)
    if len(specific) > 1:
        output["hookSpecificOutput"] = specific
    return output


def run_checks(raw: bytes, checks: tuple[Check, ...] = CHECKS, start: float | None = None) -> tuple[str, str, int]:
    """The stdout text, stderr text, and exit status of the checks run in order on `raw`."""
    text = raw.decode("utf-8", "replace")
    results: list[tuple[str, hook_runtime.CheckResult]] = []
    begin = hook_runtime.started_at(time.time()) if start is None else start
    for check in checks:
        if not check.applies_to(text):
            continue
        result = hook_runtime.run_budgeted(check.script, check.main, raw, EVENT, check.budget(), begin)
        reason = denial(check.script, result)
        if reason is not None:
            if result.code == BLOCK_EXIT:
                return "", named(check.script, reason) + "\n", BLOCK_EXIT
            output = merged(results, named(check.script, reason))
            return json.dumps(output, ensure_ascii=False) + "\n", "", 0
        results.append((check.script, result))
        begin = time.time()
    output = merged(results, None)
    return (json.dumps(output, ensure_ascii=False) + "\n" if output else ""), "", 0


def main() -> int:
    raw = sys.stdin.buffer.read()
    try:
        hook_runtime.verify_cache()
        stdout, stderr, code = run_checks(raw)
    except Exception as error:
        hook_runtime.report_error("bash_pretool_checks.py", error)
        return 1
    sys.stdout.write(stdout)
    sys.stderr.write(stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
