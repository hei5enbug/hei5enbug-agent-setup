import pytest

from shop.catalog import price_cents
from shop.errors import UnknownSku


def test_a_listed_sku_has_its_price():
    assert price_cents("CD-200") == 799


def test_an_unlisted_sku_is_rejected():
    with pytest.raises(UnknownSku):
        price_cents("ZZ-999")
