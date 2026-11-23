import io

from tally.cli import main


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_a_wednesday_belongs_to_the_week_that_began_on_sunday():
    code, out, _ = run("weekly", "2026-11-18")
    assert code == 0
    assert out.splitlines() == ["alpha 6.0", "beta 10.0", "gamma 4.5"]


def test_a_saturday_belongs_to_the_week_that_began_on_the_sunday_before():
    code, out, _ = run("weekly", "2026-11-14")
    assert code == 0
    assert out.splitlines() == ["alpha 9.5", "beta 5.0", "gamma 0.0"]


def test_a_sunday_starts_a_new_week():
    assert run("weekly", "2026-11-15") == run("weekly", "2026-11-18")
