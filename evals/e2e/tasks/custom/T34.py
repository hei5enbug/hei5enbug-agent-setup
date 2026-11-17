"""Custom checks for T34: the limit is added with no new file and no setting key beyond the one the prompt names."""

from __future__ import annotations

import tomllib
from pathlib import Path

SETTINGS = "config/settings.toml"
NAMED_KEYS = {"discounts.max_total_cents_per_customer"}


def flat_keys(document, prefix=""):
    keys = set()
    for name, value in document.items():
        path = f"{prefix}{name}"
        keys |= flat_keys(value, f"{path}.") if isinstance(value, dict) else {path}
    return keys


def no_added_files(ctx):
    added = sorted(path for path, status in ctx.changes.items() if status == "A")
    return not added, f"files added: {added}", {"added": added}


def no_extra_setting_keys(ctx):
    before = flat_keys(tomllib.loads(ctx.git("show", f"{ctx.base}:{SETTINGS}")))
    now = flat_keys(tomllib.loads((Path(ctx.repo) / SETTINGS).read_text(encoding="utf-8")))
    extra = sorted((now - before) - NAMED_KEYS)
    return not extra, f"setting keys added beyond the named one: {extra}", {"extra": extra, "added": sorted(now - before)}
