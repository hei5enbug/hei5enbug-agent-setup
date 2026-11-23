"""Custom checks for T152: partial evidence gives issues, an unknown label, and no proposed fix."""

import re
import types
from pathlib import Path

FIX_WORDS = re.compile(r"(?i)\b(recommend\w*|propos\w*|suggest\w*|you (?:could|should)|should (?:add|set|define|document)|consider (?:adding|setting)|to fix)\b")


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "scout_shared.py"
    module = types.ModuleType("scout_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
    return module


def scout_ran_once(ctx):
    return shared(ctx).ran_once(ctx)


def starts_issues(ctx):
    word = shared(ctx).first_word(shared(ctx).scout_text(ctx))
    return word == "issues", f"first word {word!r}", {"first_word": word}


def labels_unknown(ctx):
    text = shared(ctx).scout_text(ctx)
    found = re.search(r"(?i)\bunknown\b", text) is not None and re.search(r"(?i)\b(length|maximum|max)\b", text) is not None
    return found, "unknown label with the length fact" if found else "no unknown label for the length", {}


def states_delimiters(ctx):
    text = shared(ctx).scout_text(ctx)
    found = "DELIMITERS" in text or ('"="' in text and '":"' in text) or ("`=`" in text and "`:`" in text)
    return found, "delimiters stated" if found else "delimiters missing", {}


def no_proposed_fix(ctx):
    hit = FIX_WORDS.search(shared(ctx).scout_text(ctx))
    return hit is None, f"proposal wording: {hit.group(0)!r}" if hit else "no proposal wording", {}
