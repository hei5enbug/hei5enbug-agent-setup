def annual_discount_rate(plan):
    if plan.term == "annual":
        return 0.15
    return 0.0


def invoice_total(account_id, plan, tax_adapter):
    if not plan.active:
        return 0
    subtotal = plan.monthly_price * plan.months
    discounted = subtotal * (1 - annual_discount_rate(plan))
    return discounted * (1 + tax_adapter.rate_for(account_id))
