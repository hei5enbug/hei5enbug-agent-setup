"""Custom checks for F02: the checks of T02 plus the forced-delegation checks."""

import types
from pathlib import Path


def load(ctx, name):
    path = Path(ctx.tasks_root) / "custom" / name
    module = types.ModuleType(name)
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def new_tests(ctx):
    return getattr(load(ctx, "T02.py"), "new_tests")(ctx)


def files_changed(ctx):
    return getattr(load(ctx, "T02.py"), "files_changed")(ctx)


def worker_delegated(ctx):
    return getattr(load(ctx, "forcing_shared.py"), "worker_delegated")(ctx)


def worker_route(ctx):
    return getattr(load(ctx, "forcing_shared.py"), "worker_route")(ctx)
