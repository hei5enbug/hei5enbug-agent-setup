def test_annual_plan_uses_ten_percent_discount():
    plan = Plan(term="annual", active=True, monthly_price=100, months=12)
    assert annual_discount_rate(plan) == 0.10


def test_inactive_plan_has_no_invoice():
    plan = Plan(term="monthly", active=False, monthly_price=100, months=1)
    assert invoice_total("acct-1", plan, tax_adapter) == 0
