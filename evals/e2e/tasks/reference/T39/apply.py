import sys

from patch_tools import replace

repo = sys.argv[1]

replace(repo, "parcel/rounding.py", "from decimal import ROUND_DOWN, Decimal", "from decimal import ROUND_HALF_UP, Decimal")
replace(repo, "parcel/rounding.py", '"""Return `value` as whole cents. The fraction is dropped."""', '"""Return `value` as whole cents, rounding half up."""')
replace(repo, "parcel/rounding.py", "rounding=ROUND_DOWN", "rounding=ROUND_HALF_UP")
replace(repo, "tests/test_rounding.py", "def test_a_large_fraction_is_dropped_too():\n    assert round_cents(Decimal(\"10.7\")) == 10",
        "def test_a_large_fraction_rounds_up():\n    assert round_cents(Decimal(\"10.7\")) == 11")
