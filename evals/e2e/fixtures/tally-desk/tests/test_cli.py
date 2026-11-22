import io

from tally.cli import main


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_totals_prints_one_row_per_team_sorted_by_name():
    code, out, _ = run("totals")
    assert code == 0
    assert out.splitlines() == ["alpha 17.0", "beta 21.0", "gamma 4.5"]


def test_cost_multiplies_the_hours_by_the_rate():
    assert run("cost", "gamma") == (0, "158\n", "")


def test_an_unknown_team_exits_with_two():
    code, out, err = run("rate", "delta")
    assert (code, out) == (2, "")
    assert "unknown team: delta" in err
