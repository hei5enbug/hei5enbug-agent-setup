"""Custom checks for T122: one correction made once, with no investigation, ends with no recording recommendation and no mistake-enforcer run."""

from __future__ import annotations

import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "guidance_shared.py"
    module = types.ModuleType("guidance_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def enforcer_not_run(ctx):
    ran, _, _ = shared(ctx).skill_invoked(ctx)
    return not ran, "mistake-enforcer ran" if ran else "mistake-enforcer did not run", {}
