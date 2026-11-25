"""Grade the ordinary writing cases' scope and seeded behavior."""

import runpy


def shared(ctx):
    return runpy.run_path(str(ctx.tasks_root / "custom" / "T182.py"))


def research_rules_not_read(ctx):
    common = shared(ctx)
    ok = not common["instruction_read"](ctx, common["RULE"])
    return common["result"](ok, "research rules were not read", "research rules were read for ordinary writing")


def implementation_reported(ctx):
    common = shared(ctx)
    text = common["read"](ctx, "out/pr.txt") if ctx.task["id"] == "T184" else common["answer"](ctx)
    return common["result"]("demo-banner" in text, "the seeded change is reported", "the seeded change is missing")
