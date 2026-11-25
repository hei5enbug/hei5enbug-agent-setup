import runpy


def research_rules_not_read(ctx):
    return runpy.run_path(str(ctx.tasks_root / "custom" / "T184.py"))["research_rules_not_read"](ctx)


def implementation_reported(ctx):
    return runpy.run_path(str(ctx.tasks_root / "custom" / "T184.py"))["implementation_reported"](ctx)
