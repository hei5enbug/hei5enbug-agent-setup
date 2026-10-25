import sys

from patch_tools import replace

repo = sys.argv[1]
replace(repo, "inventory/orders.py", "    def _merge_requests(", '''    def cancel_item(self, order_id: int, sku: str, quantity: int) -> Order:
        """Cancel part of one line of a placed order and put the units back, last allocation first."""
        order = self.get_order(order_id)
        if order.status != ORDER_PLACED:
            raise InvalidOrderState(order_id, order.status, "partially cancelled")
        key = validate_sku(sku)
        line = next((candidate for candidate in order.lines if candidate.sku == key), None)
        if line is None:
            raise ValidationError(f"order {order_id} has no line for {key}")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= line.quantity:
            raise ValidationError(f"quantity must be between 1 and {line.quantity}: {quantity!r}")
        kept = list(line.allocations)
        released: list[Allocation] = []
        remaining = quantity
        while remaining:
            last = kept.pop()
            taken = min(last.quantity, remaining)
            released.append(Allocation(last.warehouse, taken))
            if taken < last.quantity:
                kept.append(Allocation(last.warehouse, last.quantity - taken))
            remaining -= taken
        self.ledger.release(key, released, order_reference(order_id, "cancel-item"))
        line.quantity -= quantity
        line.allocations = kept
        if line.quantity == 0:
            order.lines.remove(line)
        else:
            line.line_total = pricing.line_total(line.unit_price, line.quantity)
        totals = self.calculator.totals([item.line_total for item in order.lines])
        order.subtotal, order.tax, order.total = totals.subtotal, totals.tax, totals.total
        if not order.lines:
            order.status = ORDER_CANCELLED
            order.cancelled_at = self.clock()
        return order

    def _merge_requests(''')
replace(repo, "README.md", "Only a placed order can be cancelled.\n", "Only a placed order can be cancelled.\n  `OrderService.cancel_item` cancels part of one line and returns those units to the warehouses they came from.\n")
replace(repo, "docs/ko/README.ko.md", "`placed` 주문만 취소할 수 있습니다.\n", "`placed` 주문만 취소할 수 있습니다.\n  `OrderService.cancel_item`으로 한 줄의 일부만 취소하면(부분 취소) 해당 수량이 원래 창고로 돌아갑니다.\n")
