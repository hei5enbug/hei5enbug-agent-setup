import sys

from patch_tools import append, replace

repo = sys.argv[1]
replace(repo, "shop/pricing.py", "rounded down to whole cents.", "rounded half up to whole cents.")
replace(repo, "shop/pricing.py", "    return amount * percent // 100\n", "    return (amount * percent * 2 + 100) // 200\n")
replace(repo, "tests/test_pricing.py", "def test_discount_rounds_down_to_whole_cents():\n    assert discount_cents(1999, 10) == 199\n",
        "def test_discount_rounds_half_up_to_whole_cents():\n    assert discount_cents(1999, 10) == 200\n")
append(repo, "tests/test_pricing.py", '''

def test_discount_rounds_exactly_half_a_cent_up():
    assert discount_cents(1985, 10) == 199
    assert discount_cents(1984, 10) == 198
''')
replace(repo, "README.md", "The discount is rounded down to whole cents.", "The discount is rounded half up to whole cents.")
replace(repo, "docs/ko/README.ko.md", "할인 금액은 센트 단위로 내림합니다.", "할인 금액은 센트 단위로 반올림합니다.")
