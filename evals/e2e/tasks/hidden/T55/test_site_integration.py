"""The built site as a whole: both changes have to be in the merged result."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import index_entries, sitemap_entries, write_site  # noqa: E402

from dockit.build import build  # noqa: E402


def built_site(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCKIT_BUILD_PHASE_SECONDS", "0")
    out = tmp_path / "build"
    build(write_site(tmp_path), out)
    return out


def test_the_build_lists_the_same_pages_in_the_sitemap_and_the_index(tmp_path, monkeypatch):
    out = built_site(tmp_path, monkeypatch)
    in_sitemap = sitemap_entries((out / "sitemap.xml").read_text(encoding="utf-8"))
    in_index = index_entries((out / "search-index.json").read_text(encoding="utf-8"))
    assert sorted(in_sitemap) == sorted(in_index) == ["changelog.html", "guide.html", "index.html"]


def test_the_dates_in_the_sitemap_and_the_index_agree(tmp_path, monkeypatch):
    out = built_site(tmp_path, monkeypatch)
    in_sitemap = sitemap_entries((out / "sitemap.xml").read_text(encoding="utf-8"))
    in_index = index_entries((out / "search-index.json").read_text(encoding="utf-8"))
    assert {name: entry["updated"] for name, entry in in_index.items()} == in_sitemap
    assert in_sitemap["guide.html"] == "2026-02-03"


def test_every_listed_page_was_built_and_a_draft_is_still_built(tmp_path, monkeypatch):
    out = built_site(tmp_path, monkeypatch)
    in_sitemap = sitemap_entries((out / "sitemap.xml").read_text(encoding="utf-8"))
    assert all((out / name).is_file() for name in in_sitemap)
    assert (out / "roadmap.html").is_file()
    assert index_entries((out / "search-index.json").read_text(encoding="utf-8"))["index.html"]["headings"] == [
        "Start here", "Next steps"]


def test_the_repository_site_check_passes_on_the_merged_build(tmp_path, monkeypatch):
    from tools import check_site

    out = built_site(tmp_path, monkeypatch)
    assert check_site.problems(out, tmp_path / "content") == []
