"""Load the Markdown pages of the site."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Page:
    slug: str
    title: str
    updated: str | None
    draft: bool
    body: str


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    meta: dict[str, str] = {}
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return meta, "\n".join(lines[index + 1:]) + "\n"
        key, _, value = line.partition(":")
        if key.strip():
            meta[key.strip()] = value.strip()
    return {}, text


def load_pages(content_dir: Path) -> list[Page]:
    pages = []
    for path in sorted(content_dir.glob("*.md")):
        meta, body = parse_front_matter(path.read_text(encoding="utf-8"))
        pages.append(Page(
            slug=path.stem, title=meta.get("title") or path.stem, updated=meta.get("updated") or None,
            draft=meta.get("draft", "").lower() == "true", body=body,
        ))
    return pages
