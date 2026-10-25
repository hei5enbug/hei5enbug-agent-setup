"""Composition root: wires the storage, the services, and the configuration together."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .clock import Clock, utcnow
from .config import Config
from .items import CatalogService
from .models import Database
from .orders import OrderService
from .pricing import PriceCalculator
from .stock import StockLedger
from .storage import JsonStore
from .warehouses import WarehouseService


@dataclass
class App:
    config: Config
    store: JsonStore
    db: Database
    catalog: CatalogService
    warehouses: WarehouseService
    stock: StockLedger
    orders: OrderService

    def save(self) -> None:
        self.store.save(self.db)


def create_app(
    data_file: str | Path | None = None,
    config: Config | None = None,
    clock: Clock = utcnow,
) -> App:
    """Load the database from `data_file` (default: the configured file) and build the services on it."""
    config = config or Config.from_env()
    store = JsonStore(data_file if data_file is not None else config.data_file)
    db = store.load()
    catalog = CatalogService(db)
    ledger = StockLedger(db, clock)
    orders = OrderService(db, catalog, ledger, PriceCalculator(config.tax_rate), clock)
    return App(config, store, db, catalog, WarehouseService(db), ledger, orders)
