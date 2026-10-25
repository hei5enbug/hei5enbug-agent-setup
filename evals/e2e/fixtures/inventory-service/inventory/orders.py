"""Orders: stock is allocated when an order is placed and released when it is cancelled."""

from __future__ import annotations

from typing import Sequence

from . import pricing
from .clock import Clock, utcnow
from .errors import InvalidOrderState, UnknownOrder, ValidationError
from .items import CatalogService
from .models import ORDER_CANCELLED, ORDER_PLACED, ORDER_SHIPPED, Allocation, Database, Order, OrderLine
from .pricing import PriceCalculator
from .stock import StockLedger
from .validators import validate_quantity, validate_sku

OrderRequest = tuple[str, int]


def order_reference(order_id: int, action: str) -> str:
    return f"order-{order_id}:{action}"


class OrderService:
    def __init__(
        self,
        db: Database,
        catalog: CatalogService,
        ledger: StockLedger,
        calculator: PriceCalculator,
        clock: Clock = utcnow,
    ) -> None:
        self.db = db
        self.catalog = catalog
        self.ledger = ledger
        self.calculator = calculator
        self.clock = clock

    def create_order(self, customer: str, requests: Sequence[OrderRequest]) -> Order:
        """Place an order. Stock is taken from the warehouses immediately; a failure leaves stock untouched."""
        customer = customer.strip()
        if not customer:
            raise ValidationError("customer must not be empty")
        merged = self._merge_requests(requests)
        order_id = self.db.next_order_id
        reference = order_reference(order_id, "place")
        lines: list[OrderLine] = []
        try:
            for sku, quantity in merged.items():
                lines.append(self._allocate_line(sku, quantity, reference))
        except Exception:
            for line in lines:
                self.ledger.release(line.sku, line.allocations, order_reference(order_id, "rollback"))
            raise
        totals = self.calculator.totals([line.line_total for line in lines])
        order = Order(
            id=order_id,
            customer=customer,
            status=ORDER_PLACED,
            lines=lines,
            created_at=self.clock(),
            subtotal=totals.subtotal,
            tax=totals.tax,
            total=totals.total,
        )
        self.db.orders[order_id] = order
        self.db.next_order_id = order_id + 1
        return order

    def get_order(self, order_id: int) -> Order:
        try:
            return self.db.orders[order_id]
        except KeyError:
            raise UnknownOrder(order_id) from None

    def list_orders(self, status: str | None = None) -> list[Order]:
        orders = sorted(self.db.orders.values(), key=lambda order: order.id)
        return [order for order in orders if status is None or order.status == status]

    def ship_order(self, order_id: int) -> Order:
        order = self.get_order(order_id)
        if order.status != ORDER_PLACED:
            raise InvalidOrderState(order_id, order.status, "shipped")
        order.status = ORDER_SHIPPED
        order.shipped_at = self.clock()
        return order

    def cancel_order(self, order_id: int) -> Order:
        """Cancel a placed order and give every line's stock back to the warehouses it came from."""
        order = self.get_order(order_id)
        if order.status != ORDER_PLACED:
            raise InvalidOrderState(order_id, order.status, "cancelled")
        reference = order_reference(order_id, "cancel")
        for line in order.lines:
            self._release_line(line, reference)
        order.status = ORDER_CANCELLED
        order.cancelled_at = self.clock()
        return order

    def _merge_requests(self, requests: Sequence[OrderRequest]) -> dict[str, int]:
        if not requests:
            raise ValidationError("an order needs at least one line")
        merged: dict[str, int] = {}
        for sku, quantity in requests:
            key = validate_sku(sku)
            merged[key] = merged.get(key, 0) + validate_quantity(quantity)
        return merged

    def _allocate_line(self, sku: str, quantity: int, reference: str) -> OrderLine:
        item = self.catalog.get_item(sku)
        if not item.active:
            raise ValidationError(f"item is not available for sale: {sku}")
        allocations = self.ledger.allocate(sku, quantity, reference)
        return OrderLine(
            sku=sku,
            quantity=quantity,
            unit_price=item.unit_price,
            line_total=pricing.line_total(item.unit_price, quantity),
            allocations=allocations,
        )

    def _release_line(self, line: OrderLine, reference: str) -> None:
        allocated = sum(allocation.quantity for allocation in line.allocations)
        if allocated != line.quantity:
            raise ValidationError(f"order line {line.sku} has {allocated} allocated of {line.quantity}")
        self.ledger.release(line.sku, list(line.allocations), reference)
