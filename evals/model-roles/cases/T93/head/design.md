# Design: shard the orders table by customer

## Context

1. `orders` is one PostgreSQL table on one primary. A primary sustains about 400 inserts per second, and the peak load
   is 1,200 inserts per second, so order writes queue at peak.
2. The customer `acme-trading` creates 41 percent of all order rows. The next largest customer creates 3 percent.
3. The "list my orders" page reads all orders of one customer in `created_at` order.

## Proposal

1. Split `orders` into 8 shards on 8 primaries. The shard of an order is `hash(customer_id) % 8`.
2. The application routes every read and write by `customer_id`, so the "list my orders" page queries one shard.
3. Each shard receives about one eighth of the writes, roughly 150 inserts per second at peak, which is well below the
   400 a primary sustains.
4. Existing rows move to their shards in a one-time copy during a maintenance window.

## Acceptance criteria

1. At a peak of 1,200 inserts per second, no primary exceeds 400 inserts per second.
2. The "list my orders" page returns a customer's orders in `created_at` order from one shard.
3. After the copy, every order exists on exactly one shard.
