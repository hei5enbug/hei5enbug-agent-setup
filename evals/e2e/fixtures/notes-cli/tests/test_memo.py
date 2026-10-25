import pytest

from notes_cli.memo import Memo, make_memo, memo_from_dict, memo_to_dict


def test_make_memo_cleans_title_and_tags():
    memo = make_memo(1, "  Buy milk ", " 2 liters ", (" Home", "home", "", "Errand"))
    assert memo.title == "Buy milk"
    assert memo.body == "2 liters"
    assert memo.tags == ("home", "errand")
    assert memo.created_at.endswith("+00:00")


def test_make_memo_requires_a_title():
    with pytest.raises(ValueError):
        make_memo(1, "   ")


def test_matches_ignores_case_in_title_and_body():
    memo = Memo(1, "Weekly Report", "send to the TEAM")
    assert memo.matches("report") and memo.matches("team") and not memo.matches("budget")


def test_dict_round_trip_keeps_every_field():
    memo = make_memo(7, "Call dentist", "after 3pm", ("health",))
    assert memo_from_dict(memo_to_dict(memo)) == memo


def test_has_tag_is_case_insensitive():
    assert Memo(1, "x", "", ("work",)).has_tag("WORK")
