# Infrastructure access

Reads of infrastructure, cloud, Kubernetes, and database state need no approval. Keep them light and safe so
they never load a shared system.

- Narrow every read: name the context, namespace, resource group, or label, and add `--limit` or `-o name`.
- Bound logs with `--tail` and `--since`. Never follow them with `-f`.
- Avoid cluster-wide or all-namespace queries on production unless the task needs them.
- In SQL, select only the needed columns, filter on an indexed `WHERE`, and add `LIMIT`.
- Run `EXPLAIN` before a query of unknown cost. Never run `EXPLAIN ANALYZE`.
- On a large table, use a table estimate instead of `COUNT(*)`.
- Prefer one batched call over a loop, and reuse results you already have.
- Page MCP and cloud API reads with small pages.
- Stop and report when responses slow, throttle, or time out. Do not retry in a loop.

Writes follow the approval guard. Protected values follow the
[protected-value access rules](protected-values.md).
