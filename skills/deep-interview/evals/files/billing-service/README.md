# Billing Service Fixture

The service invoices active subscription plans, applies annual discounts, and asks the tax adapter for jurisdiction rates. The work request affects invoice totals, plan eligibility, and tax lookup.

The current code uses account_id as the subscription key. Product notes describe it as globally unique. Support notes say imported accounts can reuse the same account_id in different workspaces. Resolve this conflict before changing lookup behavior.
