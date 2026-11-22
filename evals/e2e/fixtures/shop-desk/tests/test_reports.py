from datetime import date

from shop.orders import place_order
from shop.reports import customers_by_spend, sales_report


def test_the_sales_report_has_one_row_per_customer_with_tax(data_file):
    place_order(data_file, 2, [("AB-100", 4)], placed_on=date(2026, 3, 2))
    place_order(data_file, 2, [("AB-100", 4)], placed_on=date(2026, 3, 3))
    place_order(data_file, 1, [("CD-200", 1)], placed_on=date(2026, 3, 3))
    rows = sales_report(data_file)
    assert [(row["customer_id"], row["orders"], row["net_cents"], row["tax_cents"]) for row in rows] == [
        (1, 1, 720, 57), (2, 2, 10000, 800)]


def test_customers_by_spend_adds_up_each_customers_orders():
    orders = [
        {"customer_id": 2, "subtotal_cents": 3000, "discount_cents": 0},
        {"customer_id": 1, "subtotal_cents": 1000, "discount_cents": 100},
        {"customer_id": 1, "subtotal_cents": 500, "discount_cents": 0},
    ]
    assert customers_by_spend(orders) == [(2, 3000), (1, 1400)]
