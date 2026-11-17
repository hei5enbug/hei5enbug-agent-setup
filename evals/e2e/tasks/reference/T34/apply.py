import sys

from patch_tools import append, replace

repo = sys.argv[1]
replace(repo, "orders/service.py", "        subtotal = sum(price * quantity for _, price, quantity in lines)\n",
        "        subtotal = sum(price * quantity for _, price, quantity in lines)\n"
        "        discount = percent_of(subtotal, discount_percent)\n"
        "        spent = self.conn.execute(\"SELECT COALESCE(SUM(discount_cents), 0) FROM orders \"\n"
        "                                  \"WHERE customer_id = ? AND status != 'cancelled'\", (customer_id,)).fetchone()[0]\n"
        "        limit = settings.get(\"discounts\", \"max_total_cents_per_customer\")\n"
        "        if spent + discount > limit:\n"
        "            raise OrderRejected(f\"the discounts of {customer_id} would pass the limit of {limit} cents\")\n")
replace(repo, "orders/service.py", "(order_id, customer_id, self.now(), percent_of(subtotal, discount_percent)))",
        "(order_id, customer_id, self.now(), discount))")
replace(repo, "config/settings.toml", "max_percent = 30\n", "max_percent = 30\nmax_total_cents_per_customer = 5000\n")
append(repo, "tests/test_service.py", '''

def test_the_discounts_of_one_customer_cannot_pass_the_limit_and_cancelled_ones_do_not_count(service):
    first = service.place_order("c-1", [("tea", 20000, 1)], discount_percent=20)
    with pytest.raises(OrderRejected):
        service.place_order("c-1", [("tea", 5100, 1)], discount_percent=20)
    service.place_order("c-2", [("tea", 5100, 1)], discount_percent=20)
    service.cancel_order(first)
    service.place_order("c-1", [("tea", 5100, 1)], discount_percent=20)
''')
