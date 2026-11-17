"""A small site written to a temporary folder, so the tests do not depend on the repository's own pages."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

NAMESPACE = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}

PAGES = {
    "index": "---\ntitle: Home\nupdated: 2026-01-10\n---\n# Home\n\nWelcome.\n\n## Start here\n\nRead on.\n\n## Next steps\n\nMore.\n",
    "guide": "---\ntitle: Guide\nupdated: 2026-02-03\n---\n# Guide\n\n## Install\n\nRun it.\n",
    "changelog": "---\ntitle: Changelog\n---\n# Changelog\n\nNothing yet.\n",
    "roadmap": "---\ntitle: Roadmap\nupdated: 2026-03-01\ndraft: true\n---\n# Roadmap\n\n## Next\n\nSecret.\n",
}


def write_site(root: Path) -> Path:
    content = root / "content"
    content.mkdir(parents=True, exist_ok=True)
    for slug, text in PAGES.items():
        (content / f"{slug}.md").write_text(text, encoding="utf-8")
    return content


def sitemap_entries(text: str) -> dict[str, str | None]:
    """URL path to lastmod (None when the url has none), from a sitemap document."""
    entries = {}
    for url in ET.fromstring(text).findall("s:url", NAMESPACE):
        loc = url.find("s:loc", NAMESPACE)
        lastmod = url.find("s:lastmod", NAMESPACE)
        entries[(loc.text or "").rsplit("/", 1)[-1]] = None if lastmod is None else (lastmod.text or "").strip()
    return entries


def index_entries(text: str) -> dict[str, dict]:
    return {entry["url"].lstrip("/"): entry for entry in json.loads(text)}
