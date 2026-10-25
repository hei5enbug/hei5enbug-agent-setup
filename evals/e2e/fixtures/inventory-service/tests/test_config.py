from decimal import Decimal

import pytest

from inventory.config import Config
from inventory.errors import ConfigError


def test_defaults_apply_without_environment():
    config = Config.from_env({})
    assert config.data_file == "inventory.json"
    assert config.currency == "USD"
    assert config.tax_rate == Decimal("0.08")


def test_environment_overrides_defaults():
    config = Config.from_env(
        {"INVENTORY_DATA_FILE": "/tmp/stock.json", "INVENTORY_CURRENCY": "eur", "INVENTORY_TAX_RATE": "0.2"}
    )
    assert config.data_file == "/tmp/stock.json"
    assert config.currency == "EUR"
    assert config.tax_rate == Decimal("0.2")


@pytest.mark.parametrize("rate", ["abc", "-0.1", "1", "NaN"])
def test_invalid_tax_rate_is_rejected(rate):
    with pytest.raises(ConfigError):
        Config.from_env({"INVENTORY_TAX_RATE": rate})


def test_invalid_currency_is_rejected():
    with pytest.raises(ConfigError):
        Config.from_env({"INVENTORY_CURRENCY": "dollars"})
