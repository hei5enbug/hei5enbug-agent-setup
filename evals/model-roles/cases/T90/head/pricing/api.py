"""Price quotes for the public quote endpoint."""

CURRENCY = "USD"


def format_amount(cents: int) -> str:
    """Return an amount in cents as a decimal string such as "12.50"."""
    return f"{cents // 100}.{cents % 100:02d}"


def quote(lines: list[dict]) -> dict:
    """Return the quote for order lines such as {"sku": "A-1", "quantity": 2, "unit_cents": 250}.

    The response carries the order total as a decimal string, which is easier to read than a count of cents.
    """
    total_cents = sum(line["quantity"] * line["unit_cents"] for line in lines)
    return {"currency": CURRENCY, "total": format_amount(total_cents)}
