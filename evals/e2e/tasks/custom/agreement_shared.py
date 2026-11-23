"""Checks shared by the requirements agreement tasks T49 to T51. A task's custom module loads this file through `shared(ctx)`.

They read the scripted user's exchanges from `view["user_exchanges"]`: per exchange its kind, question, matched identifiers,
reply, whether it asked for approval, whether it was approved, the specification an approval was judged on, and the paths the
agent had edited and the commit count at that moment."""

from __future__ import annotations

import re
import sys
import types
from pathlib import Path

BASE_COMMITS = 1
CACHE_DEFINITION = re.compile(r"lru_cache|functools|monotonic|time\.time|class \w*[Cc]ache|_cache\b|_CACHE")
QUESTION_ENDINGS = ("?", "？")


def scripted_user(ctx):
    path = Path(ctx.tasks_root).parent / "harness" / "scripted_user.py"
    module = types.ModuleType("scripted_user_for_grading")
    sys.modules[module.__name__] = module
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def exchanges(ctx):
    return [item for item in ctx.view.get("user_exchanges") or [] if isinstance(item, dict)]


def approved_index(items):
    return next((index for index, item in enumerate(items) if item.get("approved") is True), None)


def dirty(item):
    return bool(item.get("edited")) or (item.get("commits") or BASE_COMMITS) > BASE_COMMITS


def approved_before_edit(ctx):
    items = exchanges(ctx)
    index = approved_index(items)
    if index is None:
        return False, "the scripted user never approved a specification", {"exchanges": len(items)}
    early = [item.get("edited") for item in items[: index + 1] if dirty(item)]
    return not early, "no edit before the approval" if not early else f"edited before the approval: {early[:3]}", {"approved_at": index}


def approved_specification_holds_answers(ctx, sheet_name):
    items = exchanges(ctx)
    index = approved_index(items)
    if index is None:
        return False, "no approved specification", {}
    module = scripted_user(ctx)
    sheet = module.load_sheet(Path(ctx.tasks_root) / "answers" / sheet_name)
    ok, failed, _ = module.review_specification(sheet, str(items[index].get("specification") or ""))
    return ok, "the approved specification holds every sheet point" if ok else f"the approved specification fails {failed}", {}


def no_question(ctx):
    items = exchanges(ctx)
    return not items, f"{len(items)} question(s) asked", {"questions": [item.get("question", "")[:200] for item in items]}


def one_question_naming(ctx, names):
    items = exchanges(ctx)
    if len(items) != 1:
        return False, f"{len(items)} questions asked, expected exactly one", {}
    question = str(items[0].get("question") or "").lower()
    named = [name for name in names if name.lower() in question]
    return bool(named), f"the question names {named}" if named else "the question names no existing mechanism", {"named": named}


def no_approval_request(ctx):
    asked = [item for item in exchanges(ctx) if item.get("approval")]
    return not asked, f"{len(asked)} approval request(s)", {}


def stopped_with_a_question(ctx):
    last = [line for line in str(ctx.view.get("final_answer") or "").splitlines() if line.strip()]
    ok = bool(last) and last[-1].rstrip("*_`\"')]> \t").endswith(QUESTION_ENDINGS)
    return ok, "the session ended by asking what to do next" if ok else "the final answer does not end with a question", {}


def added_lines(ctx, path):
    diff = ctx.git("diff", ctx.base, "--", path)
    return [line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]


def reuses_existing_cache(ctx):
    problems = []
    if "rate_for" not in (Path(ctx.repo) / "tally/costs.py").read_text(encoding="utf-8"):
        problems.append("tally/costs.py does not use rate_for")
    new_files = sorted(path for path, status in ctx.changes.items() if status == "A" and path.startswith("tally/"))
    if new_files:
        problems.append(f"new modules: {new_files}")
    changed = [path for path in sorted(ctx.changes) if path.startswith("tally/") and CACHE_DEFINITION.search("\n".join(added_lines(ctx, path)))]
    if changed:
        problems.append(f"a second cache in {changed}")
    return not problems, "; ".join(problems) or "the existing cache is reused and no second cache exists", {}
