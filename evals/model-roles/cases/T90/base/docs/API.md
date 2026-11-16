# Quote API

`quote(lines)` is the entry point of the public quote endpoint. External clients parse its response, so the
response is a stable contract.

| Field | Type | Meaning |
|---|---|---|
| `currency` | string | ISO 4217 code, always `USD` |
| `total_cents` | integer | Order total in cents |

A change to these fields needs a new major version of the endpoint.
