"""Custom checks for T154: the grading of a run that misses exactly one of three expectations."""

import types
from pathlib import Path

QUOTE = "No upgrade steps."


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "skill_review_shared.py"
    module = types.ModuleType("skill_review_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def expectations(ctx):
    data = shared(ctx).read_json(ctx, shared(ctx).GRADING)
    found = data.get("expectations") if isinstance(data, dict) else None
    ok = isinstance(found, list) and len(found) == 3 and all(
        isinstance(item, dict) and isinstance(item.get("passed"), bool) and isinstance(item.get("evidence"), str)
        and isinstance(item.get("text"), str) for item in found)
    return found if ok else None


def grading_saved(ctx):
    found = expectations(ctx)
    return found is not None, "three expectations with text, passed, and evidence" if found else "no usable grading.json", {}


def marks_missed_expectation(ctx):
    found = expectations(ctx)
    flags = [item["passed"] for item in found] if found else None
    return flags == [True, True, False], f"passed flags {flags}", {"flags": flags}


def evidence_quotes_output(ctx):
    found = expectations(ctx)
    evidence = found[2]["evidence"] if found else ""
    return QUOTE in evidence, "evidence quotes the output" if QUOTE in evidence else "evidence does not quote the output", {}
