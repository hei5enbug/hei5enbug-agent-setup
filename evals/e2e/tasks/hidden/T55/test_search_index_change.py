import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import index_entries, write_site  # noqa: E402

from dockit import search_index  # noqa: E402
from dockit.pages import load_pages  # noqa: E402


def test_index_skips_draft_pages(tmp_path):
    text = search_index.render(load_pages(write_site(tmp_path)))
    assert sorted(index_entries(text)) == ["changelog.html", "guide.html", "index.html"]


def test_index_entries_carry_headings_and_updated(tmp_path):
    entries = index_entries(search_index.render(load_pages(write_site(tmp_path))))
    assert entries["index.html"] == {
        "url": "/index.html", "title": "Home", "headings": ["Start here", "Next steps"], "updated": "2026-01-10"}
    assert entries["guide.html"]["headings"] == ["Install"]
    assert entries["changelog.html"]["headings"] == []
    assert entries["changelog.html"]["updated"] is None


def test_index_is_json_with_sorted_keys(tmp_path):
    text = search_index.render(load_pages(write_site(tmp_path)))
    assert text.endswith("\n")
    assert list(json.loads(text)[0]) == sorted(json.loads(text)[0])
