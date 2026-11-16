"""CSV rows of quotes for the finance team."""

from pricing.api import quote


def quote_row(order_id: str, lines: list[dict]) -> str:
    result = quote(lines)
    return f"{order_id},{result['currency']},{result['total_cents']}"
