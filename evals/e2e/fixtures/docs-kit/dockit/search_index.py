"""Render search-index.json."""

from __future__ import annotations

import json

from .pages import Page


def entries(pages: list[Page]) -> list[dict]:
    return [{"url": f"/{page.slug}.html", "title": page.title} for page in pages]


def render(pages: list[Page]) -> str:
    return json.dumps(entries(pages), indent=2, sort_keys=True) + "\n"
