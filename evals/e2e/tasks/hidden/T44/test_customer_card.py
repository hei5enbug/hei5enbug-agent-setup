import io

import pytest

from shop import store
from shop.cli import main
from shop.customers import lookup_customer
from shop.errors import UnknownCustomer
from shop.models import Customer


def with_email(data_file):
    data = store.load(data_file)
    data["customers"]["1"]["email"] = "ada@example.com"
    store.save(data_file, data)


def test_lookup_returns_a_customer_with_its_email(data_file):
    with_email(data_file)
    assert lookup_customer(data_file, 1) == Customer(id=1, name="Ada Lovelace", tier="gold", email="ada@example.com")


def test_a_customer_without_an_email_has_none(data_file):
    assert lookup_customer(data_file, 2) == Customer(id=2, name="Brian Kernighan", tier="basic", email=None)


def test_an_unknown_customer_still_fails(data_file):
    with pytest.raises(UnknownCustomer):
        lookup_customer(data_file, 9)


def test_the_lookup_command_prints_the_email_only_when_there_is_one(data_file):
    with_email(data_file)
    for customer_id, expected in (("1", "Ada Lovelace (gold)\nemail: ada@example.com\n"), ("2", "Brian Kernighan (basic)\n")):
        out = io.StringIO()
        assert main(["--store", str(data_file), "lookup", customer_id], stdout=out, stderr=io.StringIO()) == 0
        assert out.getvalue() == expected
