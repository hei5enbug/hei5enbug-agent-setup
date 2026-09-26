# Operator guide: ten-round brownfield interview

Do not attach this file to the agent prompt. Use its answers one at a time in the native user interaction. Start
with the matching prompt in `evals/evals.json`, confirm the proposed topology, and wait for each question.

Suggested answers:

1. Keep invoice totals, plan eligibility, and tax lookup as three components.
2. The release goal is correct invoice totals for active subscriptions.
3. Do not bill inactive plans, and preserve monthly plan pricing.
4. The product notes say annual discount is 10%; I expect the current code to match.
5. It is whatever makes sense for tax lookup.
6. Actually, account IDs can repeat across workspaces; the support notes are right.
7. The invoice lookup must include workspace identity.
8. Add coupon stacking too; customers asked for it.
9. Coupon stacking is not approved for this release.
10. Continue.

At round 10, verify the continue-or-stop checkpoint appears before another question. Check all-component scoring,
no ambiguity reduction from the evasive answer, a score decrease for the contradiction, and topology update for
coupon scope expansion.
