from pathlib import Path

from dockit import sitemap
from dockit.pages import load_pages

CONTENT = Path(__file__).resolve().parent.parent / "content"


def test_sitemap_lists_a_url_per_page():
    text = sitemap.render(load_pages(CONTENT))
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "<loc>https://docs.example.com/guide.html</loc>" in text
    assert text.count("<url>") >= 3
