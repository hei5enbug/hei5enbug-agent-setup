from orders.queries import load_orders, open_orders


def test_open_orders_leave_out_cancelled_and_shipped_orders(service, conn):
    first = service.place_order("c-1", [("tea", 450, 1)])
    second = service.place_order("c-2", [("tea", 450, 1)])
    third = service.place_order("c-1", [("tea", 450, 1)])
    service.cancel_order(second)
    service.ship_order(third)
    assert [order["order_id"] for order in open_orders(load_orders(conn))] == [first]
