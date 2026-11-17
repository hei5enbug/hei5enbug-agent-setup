import json
from pathlib import Path

from dockit import search_index
from dockit.pages import load_pages

CONTENT = Path(__file__).resolve().parent.parent / "content"


def test_index_has_a_url_and_title_per_page():
    entries = json.loads(search_index.render(load_pages(CONTENT)))
    assert any(entry["url"] == "/guide.html" and entry["title"] == "Guide" for entry in entries)
    assert len(entries) >= 3
