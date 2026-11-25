import runpy


def rewrite_reference_read(ctx):
    return runpy.run_path(str(ctx.tasks_root / "custom" / "T186.py"))["rewrite_reference_read"](ctx)


def wording_and_scope_preserved(ctx):
    return runpy.run_path(str(ctx.tasks_root / "custom" / "T186.py"))["wording_and_scope_preserved"](ctx)


def unresolved_reference_reported(ctx):
    return runpy.run_path(str(ctx.tasks_root / "custom" / "T186.py"))["unresolved_reference_reported"](ctx)


def heading_changed(ctx):
    return runpy.run_path(str(ctx.tasks_root / "custom" / "T186.py"))["heading_changed"](ctx)
