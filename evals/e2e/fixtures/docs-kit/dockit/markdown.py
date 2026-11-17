"""A very small Markdown converter: headings and paragraphs."""

from __future__ import annotations

import html


def headings(body: str, level: int = 2) -> list[str]:
    """The text of every heading of the given level."""
    marker = "#" * level + " "
    return [line[len(marker):].strip() for line in body.splitlines() if line.startswith(marker)]


def to_html(body: str) -> str:
    parts = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            parts.append(f"<p>{html.escape(' '.join(paragraph))}</p>")
            paragraph.clear()

    for line in body.splitlines():
        stripped = line.strip()
        level = len(stripped) - len(stripped.lstrip("#"))
        if stripped and 1 <= level <= 6 and stripped[level:level + 1] == " ":
            flush()
            parts.append(f"<h{level}>{html.escape(stripped[level + 1:])}</h{level}>")
        elif stripped:
            paragraph.append(stripped)
        else:
            flush()
    flush()
    return "\n".join(parts) + "\n"
