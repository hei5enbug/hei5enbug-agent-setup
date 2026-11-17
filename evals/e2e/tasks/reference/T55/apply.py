import os
import sys

from patch_tools import replace, write

repo = sys.argv[1]
skipped = {name for name in os.environ.get("T55_SKIP_CHANGES", "").split(",") if name}


def sitemap_change() -> None:
    replace(repo, "dockit/sitemap.py", "    for page in pages:\n        lines.append(f\"  <url><loc>{BASE_URL}/{page.slug}.html</loc></url>\")\n",
            '''    for page in pages:
        if page.draft:
            continue
        lastmod = f"<lastmod>{page.updated}</lastmod>" if page.updated else ""
        lines.append(f"  <url><loc>{BASE_URL}/{page.slug}.html</loc>{lastmod}</url>")
''')
    replace(repo, "docs/sitemap.md", "`sitemap.xml` lists every page.\n",
            "`sitemap.xml` lists every page that is not a draft, with the page's `updated` date as `lastmod` when it has one.\n")
    replace(repo, "docs/ko/docs/sitemap.ko.md", "`sitemap.xml`에는 모든 페이지가 들어갑니다.\n",
            "`sitemap.xml`에는 초안이 아닌 모든 페이지가 들어가고, 페이지에 `updated` 날짜가 있으면 `lastmod`로 함께 들어갑니다.\n")
    write(repo, "tests/test_sitemap_drafts.py", '''from pathlib import Path

from dockit import sitemap
from dockit.pages import load_pages

CONTENT = Path(__file__).resolve().parent.parent / "content"


def test_sitemap_skips_drafts_and_adds_lastmod():
    text = sitemap.render(load_pages(CONTENT))
    assert "roadmap.html" not in text
    assert "<loc>https://docs.example.com/guide.html</loc><lastmod>2026-02-03</lastmod>" in text
    assert "<loc>https://docs.example.com/changelog.html</loc></url>" in text
''')


def search_change() -> None:
    replace(repo, "dockit/search_index.py", "from .pages import Page\n", "from . import markdown\nfrom .pages import Page\n")
    replace(repo, "dockit/search_index.py", "    return [{\"url\": f\"/{page.slug}.html\", \"title\": page.title} for page in pages]\n",
            '''    return [
        {"url": f"/{page.slug}.html", "title": page.title, "headings": markdown.headings(page.body), "updated": page.updated}
        for page in pages if not page.draft
    ]
''')
    replace(repo, "docs/search-index.md", "`search-index.json` lists the URL and title of every page.\n",
            "`search-index.json` lists the URL, title, level-2 headings, and `updated` date of every page that is not a draft.\n")
    replace(repo, "docs/ko/docs/search-index.ko.md", "`search-index.json`에는 모든 페이지의 URL과 제목이 들어갑니다.\n",
            "`search-index.json`에는 초안이 아닌 모든 페이지의 URL, 제목, 2단계 제목, `updated` 날짜가 들어갑니다.\n")
    write(repo, "tests/test_search_index_headings.py", '''import json
from pathlib import Path

from dockit import search_index
from dockit.pages import load_pages

CONTENT = Path(__file__).resolve().parent.parent / "content"


def test_index_skips_drafts_and_adds_headings_and_updated():
    entries = {entry["url"]: entry for entry in json.loads(search_index.render(load_pages(CONTENT)))}
    assert "/roadmap.html" not in entries
    assert entries["/index.html"]["headings"] == ["Start here"]
    assert entries["/guide.html"]["updated"] == "2026-02-03"
''')


if "sitemap" not in skipped:
    sitemap_change()
if "search" not in skipped:
    search_change()
