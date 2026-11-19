"""Shared by the custom checks of the UI tasks: delegation routing, the render of a screen, and layout facts.

A render needs bun and Chrome; when either is missing ctx.render raises an error that records `grade_error`, so
`regrade` can retry it on a machine that has them.
"""

from __future__ import annotations

OVERFLOW_TOLERANCE_PX = 1
WIDE, NARROW = "1280", "375"


def bare(agent_type: str) -> str:
    return str(agent_type).rsplit(":", 1)[-1].lower()


def routing(ctx, expected: str):
    """expected is "sonnet-worker" or "designer"; the main session's own delegations decide."""
    found = [d for d in ctx.view.get("delegations", []) if d.get("completed", True) and not d.get("is_error")]
    types = [bare(d.get("type", "")) for d in found]
    classes = [d.get("class") for d in found]
    if expected == "sonnet-worker":
        ok = "sonnet-worker" in types and "design" not in classes
    else:
        ok = "design" in classes
    return ok, f"expected {expected}; completed delegations: {types or 'none'}", {"delegations": types}


def render_of(ctx, module: str):
    return ctx.render(module, (1280, 375))


def render_failure(result) -> str | None:
    if result.get("error"):
        return str(result["error"])
    errors = [error for view in result["widths"].values() for error in view.get("errors", [])]
    return f"script errors: {errors[:3]}" if errors else None


def renders(ctx, module: str):
    result = render_of(ctx, module)
    problem = render_failure(result)
    shots = {width: view.get("screenshot") for width, view in result["widths"].items()}
    return problem is None, problem or "rendered at 1280 and 375 px", {"screenshots": shots}


def overflow_free(ctx, module: str, width: str):
    result = render_of(ctx, module)
    view = result["widths"].get(width)
    if view is None:
        return False, f"no render at {width} px: {result.get('error')}", {}
    sideways = view["scrollWidth"] > view["width"] + OVERFLOW_TOLERANCE_PX
    wide = view["overflowingElements"]
    ok = not sideways and wide == 0
    return ok, (f"{width} px: page width {view['scrollWidth']} of {view['width']}, {wide} element(s) past the edge"), {
        "scrollWidth": view["scrollWidth"], "overflowingElements": wide}


def boxes(ctx, module: str, width: str, test_id: str):
    view = render_of(ctx, module)["widths"].get(width)
    return list(view["boxes"].get(test_id, [])) if view else []


def side_by_side(left, right) -> bool:
    shared = min(left["bottom"], right["bottom"]) - max(left["top"], right["top"])
    return right["left"] >= left["right"] - OVERFLOW_TOLERANCE_PX and shared > 0


def stacked(upper, lower) -> bool:
    return lower["top"] >= upper["bottom"] - OVERFLOW_TOLERANCE_PX
