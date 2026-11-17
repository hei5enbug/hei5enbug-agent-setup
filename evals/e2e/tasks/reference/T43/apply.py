import sys

from patch_tools import append, replace

repo = sys.argv[1]
replace(repo, "shop/pricing.py", "from __future__ import annotations\n\nfrom .errors",
        "from __future__ import annotations\n\nfrom decimal import Decimal\n\nfrom .errors")
replace(repo, "shop/pricing.py", "def discount_cents(amount: int, percent: int) -> int:\n"
        '    """The discount a whole-number percentage takes off an amount, rounded down to whole cents."""\n',
        "def discount_cents(amount: int, percent: int | float) -> int:\n"
        '    """The discount a percentage, whole or fractional, takes off an amount, rounded down to whole cents."""\n')
replace(repo, "shop/pricing.py", "    return amount * percent // 100\n", "    return int(amount * Decimal(str(percent)) / 100)\n")
replace(repo, "shop/pricing.py", "def order_total(lines: list[tuple[int, int]], percent: int = 0) -> int:",
        "def order_total(lines: list[tuple[int, int]], percent: int | float = 0) -> int:")
replace(repo, "shop/cart.py", "    def total(self, percent: int = 0) -> int:", "    def total(self, percent: int | float = 0) -> int:")
replace(repo, "shop/cli.py", 'quote.add_argument("--discount", type=int, default=0, metavar="PERCENT", help="whole-number percent off")',
        'quote.add_argument("--discount", type=float, default=0, metavar="PERCENT", help="percent off, such as 12.5")')
replace(repo, "README.md", "- `PERCENT` is a whole number from 0 to 100. The discount is rounded down to whole cents.\n",
        "- `PERCENT` is a number from 0 to 100, such as 12.5. The discount is rounded down to whole cents.\n")
replace(repo, "docs/ko/README.ko.md", "- `PERCENT`는 0부터 100까지의 정수입니다. 할인 금액은 센트 단위로 내림합니다.\n",
        "- `PERCENT`는 0부터 100까지의 수이며 12.5처럼 소수도 됩니다. 할인 금액은 센트 단위로 내림합니다.\n")
append(repo, "tests/test_pricing.py", '''

def test_discount_takes_a_fractional_percent_and_still_rounds_down():
    assert discount_cents(1000, 12.5) == 125
    assert discount_cents(999, 12.5) == 124
''')
