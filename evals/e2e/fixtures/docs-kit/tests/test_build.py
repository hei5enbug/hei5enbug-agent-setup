import pytest

from dockit.build import build
from dockit.lockfile import Busy, held
from dockit.pages import load_pages
from tools import check_site
from pathlib import Path

CONTENT = Path(__file__).resolve().parent.parent / "content"


def test_build_writes_every_file_and_the_check_passes(tmp_path):
    out = tmp_path / "out"
    written = build(CONTENT, out)
    assert sorted(written) == ["changelog.html", "guide.html", "index.html", "roadmap.html", "search-index.json", "sitemap.xml"]
    assert check_site.problems(out, CONTENT) == []


def test_build_empties_the_folder_first(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "stale.txt").write_text("old", encoding="utf-8")
    build(CONTENT, out)
    assert not (out / "stale.txt").exists()


def test_a_second_build_into_a_used_folder_is_refused(tmp_path):
    out = tmp_path / "out"
    lock = tmp_path / "out.lock"
    lock.write_text("1", encoding="utf-8")
    with pytest.raises(Busy):
        build(CONTENT, out)
