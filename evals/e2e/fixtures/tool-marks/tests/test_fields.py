from parser import split_fields


def test_fields_are_split_on_commas():
    assert split_fields("a,b,c") == ["a", "b", "c"]


def test_fields_are_trimmed():
    assert split_fields(" a , b ") == ["a", "b"]


def test_the_line_break_is_not_part_of_the_last_field():
    assert split_fields("a,b\n") == ["a", "b"]
