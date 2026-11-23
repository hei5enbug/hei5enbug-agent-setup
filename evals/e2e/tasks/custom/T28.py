"""Custom check for T28: the thread message names the model, as the request asked."""

from __future__ import annotations

import re
from pathlib import Path

OUT = "out/chat-message.txt"
MODEL = re.compile(r"demo-model-x", re.IGNORECASE)


def model_named(ctx):
    path = Path(ctx.repo) / OUT
    if not path.is_file():
        return False, f"{OUT} is missing", {}
    hit = MODEL.search(path.read_text(encoding="utf-8", errors="replace"))
    return bool(hit), "the message names the model" if hit else "the message does not name the model", {}
