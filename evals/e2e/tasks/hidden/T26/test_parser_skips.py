from demo_parser.pairs import parse_lines


def test_parse_lines_skips_blank_and_comment_lines():
    assert parse_lines(["a=1", "", "# note", "b = 2"]) == {"a": "1", "b": "2"}


def test_parse_lines_keeps_a_value_that_contains_a_hash():
    assert parse_lines(["color=#fff"]) == {"color": "#fff"}
