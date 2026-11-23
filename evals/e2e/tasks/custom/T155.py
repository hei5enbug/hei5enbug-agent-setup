"""Custom checks for T155: a comparison where one output breaks a stated format rule."""

import re
import types
from pathlib import Path

RULE = re.compile(r"(?i)(at most (5|five)|more than (5|five)|\b(7|seven)\b[^.]{0,40}(bullets?|changes?|items?)|(5|five)[- ](bullet|change|item)|bullet limit|limit of (5|five))")


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "skill_review_shared.py"
    module = types.ModuleType("skill_review_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def comparison(ctx):
    data = shared(ctx).read_json(ctx, shared(ctx).COMPARISON)
    ok = isinstance(data, dict) and data.get("winner") in ("A", "B", "TIE") and isinstance(data.get("reasoning"), str)
    return data if ok else None


def comparison_saved(ctx):
    found = comparison(ctx)
    return found is not None, "winner and reasoning present" if found else "no usable comparison.json", {}


def prefers_compliant_output(ctx):
    found = comparison(ctx)
    winner = found["winner"] if found else None
    return winner == "B", f"winner {winner!r}", {"winner": winner}


def names_broken_rule(ctx):
    found = comparison(ctx)
    hit = RULE.search(found["reasoning"]) if found else None
    return hit is not None, f"rule wording: {hit.group(0)!r}" if hit else "the reasoning names no bullet limit", {}
