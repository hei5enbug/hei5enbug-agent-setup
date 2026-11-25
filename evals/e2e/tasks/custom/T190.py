import runpy


def skill_not_suggested(ctx):
    return runpy.run_path(str(ctx.tasks_root / "custom" / "T188.py"))["skill_not_suggested"](ctx)
