import sys

from patch_tools import replace

repo = sys.argv[1]

replace(repo, "shop/settings.py", '    "tax_percent": 8,\n', '    "tax_percent": 8,\n    "discount_limit_cents": 10000,\n')
replace(repo, "shop/discounts.py", "def tier_discount_cents(tier: str, subtotal_cents: int) -> int:\n    return subtotal_cents * TIER_PERCENT.get(tier, 0) // 100\n",
        "def tier_discount_cents(tier: str, subtotal_cents: int, already_granted_cents: int = 0, limit_cents: int | None = None) -> int:\n"
        "    \"\"\"The tier discount, cut to what is left of the customer's limit.\"\"\"\n"
        "    discount = subtotal_cents * TIER_PERCENT.get(tier, 0) // 100\n"
        "    if limit_cents is None:\n        return discount\n"
        "    return max(0, min(discount, limit_cents - already_granted_cents))\n")
replace(repo, "shop/orders.py", "from . import catalog, customers, store\n", "from . import catalog, customers, settings, store\n")
replace(repo, "shop/orders.py", "    discount = tier_discount_cents(customer[\"tier\"], subtotal)\n    data = store.load(path)\n",
        "    data = store.load(path)\n    granted = sum(order[\"discount_cents\"] for order in data[\"orders\"] if order[\"customer_id\"] == customer_id)\n"
        "    discount = tier_discount_cents(customer[\"tier\"], subtotal, granted, settings.get(\"discount_limit_cents\"))\n")
with open(f"{repo}/tests/test_discounts.py", "a", encoding="utf-8") as handle:
    handle.write('''

def test_the_discount_is_cut_to_the_remaining_limit():
    assert tier_discount_cents("gold", 10000, already_granted_cents=900, limit_cents=1000) == 100
    assert tier_discount_cents("gold", 10000, already_granted_cents=1000, limit_cents=1000) == 0
''')
replace(repo, "README.md", "- `lookup CUSTOMER_ID` prints", "- A customer's discounts add up to at most `discount_limit_cents` (default 10000) over all stored orders.\n- `lookup CUSTOMER_ID` prints")
replace(repo, "docs/ko/README.ko.md", "- `lookup CUSTOMER_ID`는", "- 고객의 할인은 저장된 모든 주문에서 합쳐 `discount_limit_cents`(기본 10000)를 넘지 않습니다.\n- `lookup CUSTOMER_ID`는")
