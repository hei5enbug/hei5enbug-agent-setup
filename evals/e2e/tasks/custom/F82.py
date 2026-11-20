"""Custom checks for F82: the checks of T82 plus the forced-delegation checks."""

import types
from pathlib import Path


def load(ctx, name):
    path = Path(ctx.tasks_root) / "custom" / name
    module = types.ModuleType(name)
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def spacing_16(ctx):
    return getattr(load(ctx, "T82.py"), "spacing_16")(ctx)


def label_full_name(ctx):
    return getattr(load(ctx, "T82.py"), "label_full_name")(ctx)


def label_email_alerts(ctx):
    return getattr(load(ctx, "T82.py"), "label_email_alerts")(ctx)


def variant_secondary(ctx):
    return getattr(load(ctx, "T82.py"), "variant_secondary")(ctx)


def nothing_else_changed(ctx):
    return getattr(load(ctx, "T82.py"), "nothing_else_changed")(ctx)


def renders(ctx):
    return getattr(load(ctx, "T82.py"), "renders")(ctx)


def worker_delegated(ctx):
    return getattr(load(ctx, "forcing_shared.py"), "worker_delegated")(ctx)


def worker_route(ctx):
    return getattr(load(ctx, "forcing_shared.py"), "worker_route")(ctx)
