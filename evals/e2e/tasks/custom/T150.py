"""Custom checks for T150: a one-function answer from the scout."""

import re
import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "scout_shared.py"
    module = types.ModuleType("scout_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
    return module


def scout_ran_once(ctx):
    return shared(ctx).ran_once(ctx)


def starts_pass(ctx):
    word = shared(ctx).first_word(shared(ctx).scout_text(ctx))
    return word == "pass", f"first word {word!r}", {"first_word": word}


def quotes_function(ctx):
    text = shared(ctx).scout_text(ctx)
    lines = "parser.py" in text and re.search(r"parser\.py:\d+|\blines?\s*\d+|\bL\d+\b", text, re.IGNORECASE) is not None
    quote = "raise ValueError" in text or "no delimiter in" in text
    return lines and quote, f"path with line numbers: {lines}, quoted source: {quote}", {"lines": lines, "quote": quote}


def labels_direct(ctx):
    found = re.search(r"\bdirect\b", shared(ctx).scout_text(ctx), re.IGNORECASE) is not None
    return found, "direct label found" if found else "no direct label", {}
