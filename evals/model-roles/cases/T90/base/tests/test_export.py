from reports.export import quote_row


def test_quote_row_lists_the_currency_and_total_cents():
    assert quote_row("O-1", [{"sku": "A-1", "quantity": 2, "unit_cents": 250}]) == "O-1,USD,500"
