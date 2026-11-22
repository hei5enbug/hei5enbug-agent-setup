import pytest

from shop.customers import lookup_customer
from shop.errors import UnknownCustomer


def test_lookup_finds_a_stored_customer(data_file):
    assert lookup_customer(data_file, 3)


def test_lookup_of_an_unknown_customer_fails(data_file):
    with pytest.raises(UnknownCustomer):
        lookup_customer(data_file, 7)
