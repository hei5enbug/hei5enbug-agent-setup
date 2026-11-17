import sys

from patch_tools import replace, write

repo = sys.argv[1]
replace(repo, "shop/errors.py", "class InvalidItem(",
        'class QuantityLimitError(ShopError, ValueError):\n    """A line quantity is above the limit."""\n\n\nclass InvalidItem(')
replace(repo, "shop/pricing.py", "from .errors import InvalidQuantity\n", "from .errors import InvalidQuantity, QuantityLimitError\n")
replace(repo, "shop/pricing.py", "FREE_SHIPPING_FROM = 5000\n", "FREE_SHIPPING_FROM = 5000\nMAX_QUANTITY = 99\n")
replace(repo, "shop/pricing.py", "    return unit_price * quantity\n",
        "    if quantity > MAX_QUANTITY:\n"
        '        raise QuantityLimitError(f"quantity {quantity} is above the limit of {MAX_QUANTITY}")\n'
        "    return unit_price * quantity\n")
write(repo, "tests/test_quantity_limit.py", '''import pytest

from shop.errors import InvalidQuantity, QuantityLimitError
from shop.pricing import line_total


def test_the_limit_itself_is_accepted():
    assert line_total(10, 99) == 990


def test_one_above_the_limit_raises_the_limit_error():
    with pytest.raises(QuantityLimitError):
        line_total(10, 100)


def test_the_limit_error_names_the_quantity_and_the_limit():
    with pytest.raises(QuantityLimitError) as raised:
        line_total(10, 120)
    assert "120" in str(raised.value) and "99" in str(raised.value)


def test_a_quantity_below_one_is_still_an_invalid_quantity():
    with pytest.raises(InvalidQuantity):
        line_total(10, 0)
''')
