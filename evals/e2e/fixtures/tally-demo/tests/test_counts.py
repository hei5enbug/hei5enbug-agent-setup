from tally.counts import note_total


def test_note_total_skips_blank_notes():
    assert note_total(["a", "  ", "b", ""]) == 2
