## Summary

The catalog API serves prices from an in-process cache, and customers see a stale price after an admin changes one,
while the database still answers one in ten requests.

## Observations

- `catalog/cache.py` keeps each entry for 60 seconds, and the admin tool calls `invalidate(sku)` after every price change.
- Support received 14 tickets last month about prices that stayed wrong for up to one minute after a change.
- At peak the catalog API handles about 900 requests per second, and the database answers 10 percent of them.
- A cache hit ratio is not logged anywhere today.

## Proposal

1. Replace the 60-second time to live with a fixed 15-minute time to live.
2. Remove the `invalidate(sku)` call from the admin tool and delete the endpoint behind it. Entries leave the cache only
   by expiring.
3. Log the cache hit ratio once per minute.

## Acceptance criteria

1. At peak load, the database answers at most 5 percent of catalog API requests.
2. After an admin changes a price, the catalog API returns the new price within 30 seconds.
3. The log shows the cache hit ratio once per minute.
