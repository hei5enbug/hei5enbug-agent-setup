from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from inventory.app import App, create_app
from inventory.config import Config


class FakeClock:
    """Returns a fixed time that tests can move forward."""

    def __init__(self) -> None:
        self.now = datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: int) -> None:
        self.now = self.now + timedelta(**kwargs)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def data_file(tmp_path):
    return tmp_path / "inventory.json"


@pytest.fixture
def app(data_file, clock) -> App:
    """An app with two warehouses (MAIN is drawn first), three items, and some stock."""
    app = create_app(data_file, Config(tax_rate=Decimal("0.10")), clock)
    app.warehouses.add_warehouse("MAIN", "Main warehouse", priority=10)
    app.warehouses.add_warehouse("EAST", "East depot", priority=20)
    app.catalog.add_item("WIDGET", "Widget", Decimal("10.00"), "hardware")
    app.catalog.add_item("GADGET", "Gadget", Decimal("25.50"), "hardware")
    app.catalog.add_item("BOLT", "Bolt", Decimal("0.40"), "parts")
    app.stock.receive("MAIN", "WIDGET", 20)
    app.stock.receive("MAIN", "GADGET", 8)
    app.stock.receive("EAST", "WIDGET", 5)
    app.stock.receive("EAST", "BOLT", 100)
    return app
