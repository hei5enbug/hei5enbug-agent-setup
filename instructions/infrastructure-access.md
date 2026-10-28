# Infrastructure access

Reads of infrastructure, cloud, Kubernetes, and database state need no approval. Keep them light and safe so
they never load a shared system.

- Narrow every read: name the context, namespace, resource group, or label, and add `--limit` or `-o name`.
- Bound logs with `--tail` and `--since`. Never follow them with `-f`.
- Avoid cluster-wide or all-namespace queries on production unless the task needs them.
- Open a port-forward or other tunnel only on a free port the tool picks or one with no listener. Before any request,
  confirm the tunnel still runs and owns that port; otherwise send nothing, never retry, and report. Stop it when done.
- For DB queries, prefer tabularis MCP `run_query` with a small `limit` when `list_connections` lists the target;
  otherwise DataGrip MCP, otherwise a CLI through `secret_exec.py`.
- Before a PostgreSQL read on a production connection (a name with `prod` or `운영`, or without a dev, test, QA,
  staging, sandbox, or local marker), run `EXPLAIN (FORMAT JSON)` with the identical read text (never ANALYZE), then
  run that identical text.
  SQL Server production reads have no plan check, so keep them narrow.
- In SQL, select only the needed columns, filter on an indexed `WHERE`, and add `LIMIT`.
- Run `EXPLAIN` before any other query of unknown cost. Never run `EXPLAIN ANALYZE`.
- On a large table, use a table estimate instead of `COUNT(*)`.
- Prefer one batched call over a loop, and reuse results you already have.
- Page MCP and cloud API reads with small pages.
- Stop and report when responses slow, throttle, or time out. Do not retry in a loop.

Writes follow the approval guard. Protected values follow the
[protected-value access rules](protected-values.md).
