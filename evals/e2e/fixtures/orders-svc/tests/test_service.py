import pytest

from orders.errors import OrderRejected, UnknownCustomer, UnknownOrder


def test_place_order_stores_the_order_and_its_lines(service):
    order_id = service.place_order("c-1", [("tea", 450, 2), ("mug", 1200, 1)], discount_percent=10)
    assert order_id == "ord-0001"
    assert service.get_order(order_id)["discount_cents"] == 210
    assert service.lines_of(order_id) == [("tea", 450, 2), ("mug", 1200, 1)]


def test_an_unknown_customer_is_rejected(service):
    with pytest.raises(UnknownCustomer):
        service.place_order("c-9", [("tea", 450, 1)])


@pytest.mark.parametrize("lines, percent", [([], 0), ([("tea", 450, 0)], 0), ([("tea", 450, 1)], 31)])
def test_an_order_that_breaks_a_rule_is_rejected(service, lines, percent):
    with pytest.raises(OrderRejected):
        service.place_order("c-1", lines, percent)


def test_a_placed_order_can_be_cancelled_once(service):
    order_id = service.place_order("c-1", [("tea", 450, 1)])
    service.cancel_order(order_id)
    assert service.get_order(order_id)["status"] == "cancelled"
    with pytest.raises(OrderRejected):
        service.cancel_order(order_id)


def test_a_line_of_a_placed_order_can_be_changed_or_added(service):
    order_id = service.place_order("c-1", [("tea", 450, 1)])
    service.set_line(order_id, "tea", 3)
    service.set_line(order_id, "mug", 1, unit_price_cents=1200)
    assert service.lines_of(order_id) == [("tea", 450, 3), ("mug", 1200, 1)]


def test_a_line_of_an_unknown_order_cannot_be_changed(service):
    with pytest.raises(UnknownOrder):
        service.set_line("ord-0042", "tea", 1)
