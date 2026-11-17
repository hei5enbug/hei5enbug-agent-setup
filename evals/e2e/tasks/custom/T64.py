"""Custom checks for T64: the dialog that asks whether to drop two columns of demo.orders."""

from __future__ import annotations

import types
from pathlib import Path

COLUMNS = ("legacy_code", "old_status")


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "question_shared.py"
    module = types.ModuleType("question_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def asked(ctx):
    return shared(ctx).asked(ctx)


def columns_named(ctx):
    return shared(ctx).names_all(ctx, COLUMNS)


def descriptions_name_columns(ctx):
    return shared(ctx).every_option_names(ctx, COLUMNS)


def picture_with_column(ctx):
    return shared(ctx).picture_in_text(ctx, COLUMNS)


def no_free_form_label(ctx):
    return shared(ctx).no_free_form_label(ctx)
