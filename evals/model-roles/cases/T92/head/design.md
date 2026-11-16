# Design: retries for the order-event webhook

## Context

1. The sender posts one `order.paid` event to each subscriber URL, with a 5-second timeout. A failed delivery is dropped.
2. Subscribers reported 31 missed events last month, mostly from short outages on their side.
3. A subscriber acts on every request it receives, for example by sending a receipt email, and acknowledges it with
   HTTP 200. The subscriber contract has no field for detecting a repeated event.

## Proposal

1. Store each event and its delivery state in the `webhook_deliveries` table before the first attempt.
2. After a timeout, a connection error, or a 5xx response, retry up to five times, waiting 1, 2, 4, 8, and 16 minutes.
3. Send every retry as a new request with a newly generated `X-Delivery-Id` header, so that a subscriber's access log
   tells the attempts apart.
4. Stop after the last retry, mark the delivery `failed`, and raise an alert that names the subscriber.
5. Add a `replay` command that sends a `failed` delivery again once the subscriber reports that it is ready.

## Acceptance criteria

1. After a 20-minute outage of a subscriber, every event of that period reaches it.
2. A delivery that fails five retries is marked `failed` and raises one alert.
3. The `replay` command delivers a `failed` event exactly as stored.
