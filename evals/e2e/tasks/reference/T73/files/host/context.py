from __future__ import annotations

from pathlib import Path

from .options import option_value

MAX_CONTEXT_BYTES = 1800
SESSION_FILES = ("core.md", "common.md")
DELIVERY = {
    "auto": "Auto (`auto`)",
    "strict": "Strict (`strict`)",
    "manual": "Manual (`manual`)",
}


def delivery_line(environ: dict | None = None) -> str:
    label = DELIVERY.get(option_value("delivery", environ), DELIVERY["auto"])
    return f"Delivery: {label}."


def render_context(root: Path, environ: dict | None = None) -> str:
    folder = Path(root) / "instructions" / "session"
    parts = [(folder / name).read_text(encoding="utf-8").strip() for name in SESSION_FILES]
    text = "\n\n".join(parts) + "\n" + delivery_line(environ) + "\n"
    if len(text.encode("utf-8")) > MAX_CONTEXT_BYTES:
        raise ValueError("session context is over its byte budget")
    return text
