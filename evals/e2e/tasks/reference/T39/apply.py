import sys

from patch_tools import append, replace

repo = sys.argv[1]
replace(repo, "orders/service.py", '        """Set the quantity of a line, or add the line when it is new and a unit price is given."""\n        self.get_order(order_id)\n',
        '        """Set the quantity of a line, or add the line when it is new and a unit price is given."""\n'
        '        if self.get_order(order_id)["status"] != "placed":\n            raise OrderRejected(f"{order_id} is not a placed order")\n')
append(repo, "tests/test_service.py", '''

def test_the_lines_of_a_shipped_order_cannot_be_changed_or_added(service):
    order_id = service.place_order("c-1", [("tea", 450, 1)])
    service.ship_order(order_id)
    with pytest.raises(OrderRejected):
        service.set_line(order_id, "tea", 5)
    with pytest.raises(OrderRejected):
        service.set_line(order_id, "mug", 1, unit_price_cents=1200)
    assert service.lines_of(order_id) == [("tea", 450, 1)]
''')
