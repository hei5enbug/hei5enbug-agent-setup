# Notification Retry Map

## Destination
Choose retry behavior for failed webhook deliveries without duplicating customer-visible actions.

## Notes
Preserve current delivery ordering. See ticket bodies only when the selected decision requires them.

## Decisions so far
- [Delivery identity](tickets/01-decision-001.md) — closed decisions use stable event IDs.

## Not yet specified
Whether retry delays vary by endpoint response class.

## Out of scope
- Replacing the provider is outside this effort.
