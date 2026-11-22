"""Custom checks for T40: the agent's own tests must pass on a reference and fail on each seeded faulty copy."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

FAULTS = "faults/T40"
TARGET = "parcel/pickup.py"
SHIPPED = (TARGET, "parcel/errors.py")


def overlay(ctx, name: str, substitution: dict | None) -> Path:
    """A copy of the agent's repository whose limit code is the reference, or a faulty copy of it."""
    source = Path(ctx.tasks_root) / FAULTS / "reference"
    root = ctx.suite_copy(f"fault-{name}")
    for relative in SHIPPED:
        shutil.copyfile(source / relative, root / relative)
    if substitution:
        path = root / substitution["file"]
        text = path.read_text(encoding="utf-8")
        if text.count(substitution["old"]) != 1:
            raise ValueError(f"fault {name}: expected exactly one match")
        path.write_text(text.replace(substitution["old"], substitution["new"]), encoding="utf-8")
    return root


def run_tests(ctx, name: str, substitution: dict | None) -> str:
    root = overlay(ctx, name, substitution)
    result = ctx.execute_tests([*ctx.test_command, "-rfE", "tests"], root)
    if result["timed_out"]:
        return "timed out"
    if result["returncode"] == 0 and result["passed"] > 0:
        return "passed"
    return "failed" if result["failed"] or result["errors"] else "no verdict"


def own_tests_kill_faults(ctx):
    faults = json.loads((Path(ctx.tasks_root) / FAULTS / "faults.json").read_text(encoding="utf-8"))
    outcome = {"reference": run_tests(ctx, "reference", None)}
    outcome.update({fault["id"]: run_tests(ctx, fault["id"], fault) for fault in faults})
    survived = sorted(name for name, state in outcome.items() if name != "reference" and state != "failed")
    ok = outcome["reference"] == "passed" and not survived
    detail = f"reference {outcome['reference']}; faulty copies not caught: {survived}"
    return ok, detail, {"outcome": outcome, "survived": survived}


def new_tests(ctx):
    changed = sorted(path for path in ctx.changes if path.startswith("tests/") and path.endswith(".py")
                     and not path.startswith("tests/hidden/"))
    covered = []
    for path in changed:
        text = (Path(ctx.repo) / path).read_text(encoding="utf-8", errors="replace")
        before = ctx.git("show", f"{ctx.base}:{path}") if ctx.changes[path] == "M" else ""
        if "PickupLimitError" in text and text.count("PickupLimitError") > before.count("PickupLimitError"):
            covered.append(path)
    return bool(covered), f"test files that use PickupLimitError: {covered}", {"changed": changed, "covered": covered}
