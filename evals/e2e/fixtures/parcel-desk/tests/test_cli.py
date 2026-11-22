import io

from parcel.cli import main


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_quote_prints_the_label_and_the_amounts():
    code, out, _ = run("quote", "--weight", "1200", "--zone", "b", "--declared", "20000")
    assert code == 0
    assert out.splitlines()[0] == "Zone B"
    assert out.splitlines()[-1] == "Total: 16.58"


def test_a_user_error_exits_with_two():
    code, out, err = run("quote", "--weight", "1200", "--zone", "z")
    assert (code, out) == (2, "")
    assert "unknown zone: Z" in err
