from pathlib import Path

from dockit.pages import load_pages, parse_front_matter

CONTENT = Path(__file__).resolve().parent.parent / "content"


def test_front_matter_is_split_from_the_body():
    meta, body = parse_front_matter("---\ntitle: Hi\ndraft: true\n---\n# Hi\n")
    assert meta == {"title": "Hi", "draft": "true"}
    assert body == "# Hi\n"


def test_text_without_front_matter_is_all_body():
    assert parse_front_matter("# Hi\n") == ({}, "# Hi\n")


def test_pages_load_sorted_with_their_fields():
    pages = load_pages(CONTENT)
    assert [page.slug for page in pages] == ["changelog", "guide", "index", "roadmap"]
    by_slug = {page.slug: page for page in pages}
    assert by_slug["guide"].updated == "2026-02-03"
    assert by_slug["changelog"].updated is None
    assert by_slug["roadmap"].draft and not by_slug["guide"].draft
