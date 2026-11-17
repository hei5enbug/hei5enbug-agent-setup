"""Custom checks for T48: one deliverable whose requested method repeats the cache the fixture already has."""

from __future__ import annotations

import re
import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "agreement_shared.py"
    module = types.ModuleType("agreement_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module



MECHANISM = re.compile(r"(?i)load_cached|ttlcache|cache\.py")


def one_question_names_mechanism(ctx):
    exchanges, _ = shared(ctx).conversation(ctx)
    questions = [item for item in exchanges if item.get("approval") is None]
    if len(questions) != 1:
        return False, f"{len(questions)} question(s), need exactly 1", {}
    named = bool(MECHANISM.search(questions[0]["question"]))
    return named, "the question names the existing cache" if named else "the question does not name the existing cache", {}


def no_approval_request(ctx):
    exchanges, _ = shared(ctx).conversation(ctx)
    held = shared(ctx).approvals(exchanges)
    return not held, f"{len(held)} request(s) for approval", {}


def question_before_edit(ctx):
    return shared(ctx).question_before_edit(ctx, "cache-choice")


def single_cache_class(ctx):
    found = []
    for path in sorted(Path(ctx.repo, "timesheet").glob("*.py")):
        found += [f"{path.name}:{name}" for name in re.findall(r"(?m)^class\s+(\w*Cache\w*)", path.read_text(encoding="utf-8"))]
    return len(found) == 1, f"cache classes: {found}", {"classes": found}
