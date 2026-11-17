import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import sitemap_entries, write_site  # noqa: E402

from dockit import sitemap  # noqa: E402
from dockit.pages import load_pages  # noqa: E402


def test_sitemap_skips_draft_pages(tmp_path):
    text = sitemap.render(load_pages(write_site(tmp_path)))
    assert sorted(sitemap_entries(text)) == ["changelog.html", "guide.html", "index.html"]


def test_sitemap_adds_lastmod_from_updated_and_leaves_it_out_without_one(tmp_path):
    entries = sitemap_entries(sitemap.render(load_pages(write_site(tmp_path))))
    assert entries == {"changelog.html": None, "guide.html": "2026-02-03", "index.html": "2026-01-10"}


def test_sitemap_keeps_the_base_url_and_the_slug_order(tmp_path):
    text = sitemap.render(load_pages(write_site(tmp_path)))
    locs = [line.split("<loc>")[1].split("</loc>")[0] for line in text.splitlines() if "<loc>" in line]
    assert locs == [f"https://docs.example.com/{name}.html" for name in ("changelog", "guide", "index")]
