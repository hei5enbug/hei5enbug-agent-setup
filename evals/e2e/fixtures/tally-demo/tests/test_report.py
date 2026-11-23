from tally.report import top_notes


def test_top_notes_returns_the_longest_first():
    assert top_notes(["aa", "b", "cccc"], 2) == ("cccc", "aa")
