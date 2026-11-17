from shop.pricing import discount_cents, order_total


def test_a_whole_percent_still_rounds_down_to_whole_cents():
    assert discount_cents(1999, 10) == 199
    assert discount_cents(1000, 15) == 150
    assert discount_cents(1, 50) == 0


def test_shipping_is_still_decided_after_the_discount():
    assert order_total([(6000, 1)], percent=20) == 4800 + 500
