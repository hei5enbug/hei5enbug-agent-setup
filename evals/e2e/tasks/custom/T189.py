import runpy


def skill_started_after_consent(ctx):
    return runpy.run_path(str(ctx.tasks_root / "custom" / "T188.py"))["skill_started_after_consent"](ctx)


def timeout_evidence(ctx):
    return runpy.run_path(str(ctx.tasks_root / "custom" / "T188.py"))["timeout_evidence"](ctx)
