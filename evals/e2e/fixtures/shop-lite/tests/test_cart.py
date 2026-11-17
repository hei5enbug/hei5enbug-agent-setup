from shop.cart import Cart


def test_adding_a_sku_again_adds_to_its_quantity():
    cart = Cart()
    cart.add("tea", 700, 2)
    cart.add("tea", 700, 1)
    assert cart.lines() == [("tea", 700, 3)]


def test_lines_keep_the_order_their_sku_was_first_added():
    cart = Cart()
    cart.add("tea", 700)
    cart.add("mug", 1500)
    cart.add("tea", 700)
    assert [sku for sku, _, _ in cart.lines()] == ["tea", "mug"]


def test_total_prices_the_lines_with_the_discount():
    cart = Cart()
    cart.add("mug", 2000, 3)
    assert cart.total() == 6000
    assert cart.total(percent=10) == 5400
