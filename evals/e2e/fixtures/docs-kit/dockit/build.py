"""Build the site into one output folder."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from . import ROOT, markdown, search_index, sitemap
from .lockfile import held
from .pages import load_pages

DEFAULT_OUT = ROOT / "build"
DEFAULT_CONTENT = ROOT / "content"


def pause() -> None:
    """Each build step takes a few seconds; DOCKIT_BUILD_PHASE_SECONDS changes how long."""
    time.sleep(float(os.environ.get("DOCKIT_BUILD_PHASE_SECONDS", "3")))


def build(content_dir: Path = DEFAULT_CONTENT, out_dir: Path = DEFAULT_OUT) -> list[str]:
    """Empty `out_dir` and write the site into it; return the names of the files written."""
    pages = load_pages(content_dir)
    with held(out_dir.with_name(out_dir.name + ".lock"), f"the build folder {out_dir.name}"):
        shutil.rmtree(out_dir, ignore_errors=True)
        out_dir.mkdir(parents=True)
        written = []
        for page in pages:
            (out_dir / f"{page.slug}.html").write_text(markdown.to_html(page.body), encoding="utf-8")
            written.append(f"{page.slug}.html")
        pause()
        (out_dir / "sitemap.xml").write_text(sitemap.render(pages), encoding="utf-8")
        written.append("sitemap.xml")
        pause()
        (out_dir / "search-index.json").write_text(search_index.render(pages), encoding="utf-8")
        written.append("search-index.json")
        pause()
    return written
