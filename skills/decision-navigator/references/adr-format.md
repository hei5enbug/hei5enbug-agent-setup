# ADR format

Store ADRs under `docs/adr/` using sequential names such as `0001-event-sourced-orders.md`. For a
context-specific decision, use the context's own `docs/adr/` directory when the repository already
follows that layout.

## Minimal template

```markdown
# Short decision title

One to three sentences explaining the context, the decision, and why it was chosen.
```

Add status, rejected options, or consequences only when they help a future reader. Scan existing
ADRs for the highest number and increment it.

Do not create an ADR merely because a decision exists. Use the three tests in
[domain modeling](domain-modeling.md).
