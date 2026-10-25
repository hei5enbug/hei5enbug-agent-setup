"""Configuration read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping

from .errors import ConfigError

DEFAULT_DATA_FILE = "inventory.json"
DEFAULT_CURRENCY = "USD"
DEFAULT_TAX_RATE = Decimal("0.08")


@dataclass(frozen=True)
class Config:
    data_file: str = DEFAULT_DATA_FILE
    currency: str = DEFAULT_CURRENCY
    tax_rate: Decimal = DEFAULT_TAX_RATE

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Config":
        env = os.environ if environ is None else environ
        return cls(
            data_file=env.get("INVENTORY_DATA_FILE", DEFAULT_DATA_FILE),
            currency=_read_currency(env.get("INVENTORY_CURRENCY", DEFAULT_CURRENCY)),
            tax_rate=_read_rate(env.get("INVENTORY_TAX_RATE"), DEFAULT_TAX_RATE),
        )


def _read_currency(raw: str) -> str:
    code = raw.strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ConfigError(f"INVENTORY_CURRENCY must be a 3-letter code, got {raw!r}")
    return code


def _read_rate(raw: str | None, default: Decimal) -> Decimal:
    if raw is None or not raw.strip():
        return default
    try:
        rate = Decimal(raw.strip())
    except InvalidOperation as exc:
        raise ConfigError(f"INVENTORY_TAX_RATE must be a decimal such as 0.08, got {raw!r}") from exc
    if not rate.is_finite() or rate < 0 or rate >= 1:
        raise ConfigError(f"INVENTORY_TAX_RATE must be at least 0 and below 1, got {raw!r}")
    return rate
