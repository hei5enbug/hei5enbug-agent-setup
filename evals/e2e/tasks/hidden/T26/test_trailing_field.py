from parser import split_fields


def test_a_trailing_empty_field_is_kept():
    assert split_fields("a,b,") == ["a", "b", ""]


def test_a_trailing_empty_field_is_kept_before_the_line_break():
    assert split_fields("a,b,\n") == ["a", "b", ""]


def test_every_trailing_empty_field_is_kept():
    assert split_fields("a,,") == ["a", "", ""]
