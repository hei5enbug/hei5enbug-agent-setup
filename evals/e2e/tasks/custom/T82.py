"""Custom checks for T82: four specified edits to SettingsPanel.tsx and nothing else in the file."""

from __future__ import annotations

import types
from pathlib import Path


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "ui_shared.py"
    module = types.ModuleType("ui_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


MODULE = "src/SettingsPanel.tsx"
EDITS = {
    7: '      <form className="settings-form" style={{ display: "flex", flexDirection: "column", gap: 16 }}>',
    9: "          <span>Full name</span>",
    17: "          <span>Email alerts</span>",
    27: '          <Button variant="secondary">Cancel</Button>',
}


def lines_of(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines()]


def current(ctx) -> list[str]:
    path = Path(ctx.repo) / MODULE
    return lines_of(path.read_text(encoding="utf-8")) if path.is_file() else []


def edit_at(ctx, number: int):
    found = current(ctx)
    actual = found[number - 1] if len(found) >= number else None
    return actual is not None and actual.strip() == EDITS[number].strip(), f"line {number}: {actual!r}", {"line": number}


def spacing_16(ctx):
    return edit_at(ctx, 7)


def label_full_name(ctx):
    return edit_at(ctx, 9)


def label_email_alerts(ctx):
    return edit_at(ctx, 17)


def variant_secondary(ctx):
    return edit_at(ctx, 27)


def nothing_else_changed(ctx):
    base = lines_of(ctx.git("show", f"{ctx.base}:{MODULE}"))
    found = current(ctx)
    if len(found) != len(base):
        return False, f"the file has {len(found)} lines, was {len(base)}", {}
    moved = [number for number, (old, new) in enumerate(zip(base, found), start=1) if old != new and number not in EDITS]
    return not moved, f"other lines changed: {moved[:8]}" if moved else "only the four named lines differ", {"lines": moved}


def renders(ctx):
    return shared(ctx).renders(ctx, MODULE)


def routing(ctx):
    return shared(ctx).routing(ctx, "sonnet-worker")
