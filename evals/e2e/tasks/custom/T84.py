"""Custom checks for T84: three 320 px plan cards, 24 px apart in one row at 1280 px, and no sideways overflow at 375 px."""

from __future__ import annotations

import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "ui_shared.py"
    module = types.ModuleType("ui_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


MODULE = "src/Plans.tsx"
WIDTH_PX, GAP_PX, TOLERANCE_PX, CARDS = 320, 24, 1, 3


def cards(ctx, width: str):
    return sorted(shared(ctx).boxes(ctx, MODULE, width, "plan-card"), key=lambda box: (round(box["top"]), box["left"]))


def named_values_1280(ctx):
    found = cards(ctx, "1280")
    if len(found) != CARDS or len(shared(ctx).boxes(ctx, MODULE, "1280", "plan-row")) != 1:
        return False, f"expected one plan-row and {CARDS} plan-card elements, found {len(found)} cards", {}
    problems = []
    if any(abs(card["top"] - found[0]["top"]) > TOLERANCE_PX for card in found):
        problems.append("the cards are not in one row")
    problems += [f"card {number} is {round(card['width'])} px wide" for number, card in enumerate(found, start=1)
                 if abs(card["width"] - WIDTH_PX) > TOLERANCE_PX]
    gaps = [round(right["left"] - left["right"]) for left, right in zip(found, found[1:])]
    problems += [f"gap {gap} px" for gap in gaps if abs(gap - GAP_PX) > TOLERANCE_PX]
    return not problems, "; ".join(problems) or f"{CARDS} cards of {WIDTH_PX} px, {GAP_PX} px apart", {"gaps": gaps}


def cards_visible_375(ctx):
    found = cards(ctx, "375")
    outside = [round(card["right"]) for card in found if card["right"] > 375 + TOLERANCE_PX or card["width"] <= 0]
    return len(found) == CARDS and not outside, f"{len(found)} cards at 375 px; right edges past the screen: {outside}", {}


def no_overflow_1280(ctx):
    return shared(ctx).overflow_free(ctx, MODULE, "1280")


def no_overflow_375(ctx):
    return shared(ctx).overflow_free(ctx, MODULE, "375")


def plans_kept(ctx):
    text = " ".join(card["text"] for card in cards(ctx, "1280"))
    missing = [word for word in ("Starter", "Team", "Business") if word not in text]
    return not missing, f"missing plan names: {missing}" if missing else "plan names kept", {}


def renders(ctx):
    return shared(ctx).renders(ctx, MODULE)


def routing(ctx):
    return shared(ctx).routing(ctx, "designer")


def designer_high(ctx):
    return shared(ctx).designer_effort(ctx, "high")
