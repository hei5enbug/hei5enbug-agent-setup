# Context format

## Single context

Most repositories use one root `CONTEXT.md`:

```markdown
# Context name

One or two sentences explaining the context.

## Language

**Order**: A short definition of the domain term. _Avoid_: Purchase, transaction
```

Choose one preferred word for each concept and list confusing alternatives under `_Avoid_`. Keep
definitions to one or two sentences. Include only terms specific to the project's domain.

## Multiple contexts

When a root `CONTEXT-MAP.md` exists, it points to one glossary per context:

```markdown
# Context Map

## Contexts

- [Ordering](./src/ordering/CONTEXT.md) — receives and tracks orders
- [Billing](./src/billing/CONTEXT.md) — creates invoices and receives payments

## Relationships

- **Ordering → Billing**: Ordering provides fulfilled orders for invoicing.
```

Infer the relevant context from the ticket. Ask when a decision crosses unclear boundaries.
