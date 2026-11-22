import sys

from patch_tools import append, replace

repo = sys.argv[1]

replace(repo, "shop/catalog.py", "def price_cents(sku: str) -> int:\n    try:\n        return PRICES[sku]\n",
        "def normalize_sku(sku: str) -> str:\n    return sku.strip().upper()\n\n\ndef price_cents(sku: str) -> int:\n    try:\n        return PRICES[normalize_sku(sku)]\n")
append(repo, "tests/test_catalog.py", '''

def test_a_sku_matches_ignoring_case_and_surrounding_spaces():
    assert price_cents(" cd-200 ") == 799
''')
