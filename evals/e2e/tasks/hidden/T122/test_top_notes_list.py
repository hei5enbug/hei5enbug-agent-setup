from tally.report import top_notes


def test_top_notes_returns_a_list():
    result = top_notes(["aa", "b", "cccc"], 2)
    assert isinstance(result, list)
    assert result == ["cccc", "aa"]


def test_top_notes_keeps_input_order_for_equal_lengths():
    assert top_notes(["ab", "cd", "e"], 2) == ["ab", "cd"]
