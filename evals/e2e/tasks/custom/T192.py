import runpy


def options_share_table(ctx):
    return runpy.run_path(str(ctx.tasks_root / "custom" / "T191.py"))["options_share_table"](ctx)


def requested_option_marked(ctx):
    return runpy.run_path(str(ctx.tasks_root / "custom" / "T191.py"))["requested_option_marked"](ctx)


def longest_case_illustrated(ctx):
    return runpy.run_path(str(ctx.tasks_root / "custom" / "T191.py"))["longest_case_illustrated"](ctx)
