"""Custom checks for T51."""

from __future__ import annotations

import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "agreement_shared.py"
    module = types.ModuleType("agreement_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def one_question(ctx):
    return shared(ctx).one_question_naming(ctx, ("ttl_cached", "rate_for", "cache.py"))


def no_approval_request(ctx):
    return shared(ctx).no_approval_request(ctx)


def reuses_cache(ctx):
    return shared(ctx).reuses_existing_cache(ctx)
