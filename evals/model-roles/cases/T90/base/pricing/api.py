"""Price quotes for the public quote endpoint."""

CURRENCY = "USD"


def quote(lines: list[dict]) -> dict:
    """Return the quote for order lines such as {"sku": "A-1", "quantity": 2, "unit_cents": 250}.

    The response shape is the public contract in docs/API.md.
    """
    total_cents = sum(line["quantity"] * line["unit_cents"] for line in lines)
    return {"currency": CURRENCY, "total_cents": total_cents}
