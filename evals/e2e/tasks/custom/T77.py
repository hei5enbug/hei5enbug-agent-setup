"""Custom checks for T77: the dialog that asks whether to drop two unused columns of demo.orders."""

from __future__ import annotations

import re
import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "question_shared.py"
    module = types.ModuleType("question_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


COLUMNS = ("legacy_code", "old_status")
DRAWN = re.compile(r"[|│┌┐└┘├┤┬┴┼║╔╗╚╝]|\+[-=]|[-─═]{2,}")


def opened(ctx):
    shown = shared(ctx).dialog(ctx.view)
    return shown is not None, "a dialog was opened" if shown is not None else "no question dialog was opened", {}


def names_both_columns(ctx):
    text = shared(ctx).text_of(shared(ctx).dialog(ctx.view))
    missing = [column for column in COLUMNS if column not in text]
    return not missing, f"columns missing: {missing}" if missing else "both columns named", {"missing": missing}


def options_name_both_columns(ctx):
    found = shared(ctx).options(shared(ctx).dialog(ctx.view))
    short = [str(o.get("label", "")) for o in found if not all(c in str(o.get("description", "")) for c in COLUMNS)]
    ok = len(found) >= 2 and not short
    return ok, f"{len(found)} options; descriptions missing a column: {short}", {"short": short}


def diagram_shows_columns(ctx):
    """A drawn line with a column name sits in the diagram: a preview on Claude Code, the question text below its first line on Codex."""
    lines = [line for place in shared(ctx).diagram_texts(ctx.view) for line in place.splitlines()]
    drawn = [line for line in lines if DRAWN.search(line) and any(column in line for column in COLUMNS)]
    return bool(drawn), f"{len(drawn)} drawn lines with a column name", {"drawn": drawn[:3]}


def no_free_form_option(ctx):
    return shared(ctx).no_free_form_option(ctx.view)
