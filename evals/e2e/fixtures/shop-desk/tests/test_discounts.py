from shop.discounts import tier_discount_cents


def test_each_tier_has_its_percentage():
    assert [tier_discount_cents(tier, 10000) for tier in ("basic", "silver", "gold")] == [0, 500, 1000]


def test_an_unknown_tier_gets_no_discount():
    assert tier_discount_cents("platinum", 10000) == 0
