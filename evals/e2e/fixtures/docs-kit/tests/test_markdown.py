from dockit.markdown import headings, to_html


def test_headings_returns_the_requested_level():
    body = "# Title\n\n## One\ntext\n## Two\n### Deep\n"
    assert headings(body) == ["One", "Two"]
    assert headings(body, level=3) == ["Deep"]


def test_html_has_headings_and_paragraphs():
    assert to_html("# A\n\nline one\nline two\n") == "<h1>A</h1>\n<p>line one line two</p>\n"


def test_html_escapes_markup():
    assert to_html("a < b\n") == "<p>a &lt; b</p>\n"
