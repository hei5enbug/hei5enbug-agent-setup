# Routing

The delivery mode decides how a session delivers a change.

- `auto`: the session picks the delivery per change and goes on without asking.
- `manual`: the session asks before it delivers a change and waits for the answer.

An unknown value uses `auto`.
