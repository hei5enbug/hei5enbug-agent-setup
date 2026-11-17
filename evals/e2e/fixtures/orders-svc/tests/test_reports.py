from orders import reports


def test_the_invoice_shows_the_amounts_with_tax(service, conn):
    order_id = service.place_order("c-1", [("tea", 1000, 10)])
    text = reports.invoice_text(conn, order_id)
    assert "Subtotal: $100.00" in text
    assert "Tax: $7.25" in text
    assert text.splitlines()[-1] == "Total: $107.25"


def test_the_tax_is_taken_on_the_discounted_amount_and_rounds_half_up(service, conn):
    order_id = service.place_order("c-1", [("tea", 1000, 2)], discount_percent=10)
    assert reports.tax_cents(1800) == 131
    assert "Tax: $1.31" in reports.invoice_text(conn, order_id)
