from demo_parser.pairs import parse_lines, parse_pair


def test_parse_pair_splits_on_the_first_equals_sign():
    assert parse_pair("mode = a=b") == ("mode", "a=b")


def test_parse_lines_returns_one_entry_per_line():
    assert parse_lines(["a=1", "b = 2"]) == {"a": "1", "b": "2"}
