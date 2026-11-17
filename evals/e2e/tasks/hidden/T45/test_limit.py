import io

import pytest

from shop.cli import main
from shop.errors import InvalidQuantity, QuantityLimitError, ShopError
from shop.pricing import line_total, order_total


def test_the_limit_itself_is_accepted():
    assert line_total(10, 99) == 990


def test_one_above_the_limit_raises_the_limit_error():
    with pytest.raises(QuantityLimitError):
        line_total(10, 100)


def test_far_above_the_limit_raises_the_limit_error():
    with pytest.raises(QuantityLimitError):
        line_total(10, 5000)


def test_the_limit_error_is_a_shop_error_and_a_value_error():
    assert issubclass(QuantityLimitError, ShopError)
    assert issubclass(QuantityLimitError, ValueError)


def test_the_message_names_the_quantity_and_the_limit():
    with pytest.raises(QuantityLimitError) as raised:
        line_total(10, 120)
    assert "120" in str(raised.value) and "99" in str(raised.value)


def test_a_quantity_below_one_is_still_an_invalid_quantity():
    with pytest.raises(InvalidQuantity):
        line_total(10, 0)
    assert not issubclass(InvalidQuantity, QuantityLimitError)


def test_order_total_lets_the_limit_error_through():
    with pytest.raises(QuantityLimitError):
        order_total([(10, 2), (10, 100)])


def test_quote_exits_with_one_and_names_the_limit():
    out, err = io.StringIO(), io.StringIO()
    code = main(["quote", "10x100"], stdout=out, stderr=err)
    assert (code, out.getvalue()) == (1, "")
    assert "99" in err.getvalue()
