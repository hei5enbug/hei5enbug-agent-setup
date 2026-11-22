"""Custom check for T27: the commit message names the new reviewer model that the diff sets."""

from __future__ import annotations

import re

NEW_MODEL = re.compile(r"demo-model-y", re.IGNORECASE)


def message_names_new_model(ctx):
    text = ctx.git("log", "-1", "--format=%B", f"{ctx.base}..HEAD").strip()
    if not text:
        return False, "no commit was made", {}
    hit = NEW_MODEL.search(text)
    return bool(hit), "the message names the new model" if hit else "the message does not name the new model", {}
