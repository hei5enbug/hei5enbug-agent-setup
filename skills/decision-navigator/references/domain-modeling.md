# Domain modeling

Apply these rules when a decision changes project language, domain boundaries, or a durable
architectural choice.

## Read existing context first

Before exploring, read the relevant files when they exist:

- root `CONTEXT.md`, or root `CONTEXT-MAP.md` and the context files it points to;
- system-wide ADRs under `docs/adr/`;
- context-specific ADRs near the affected code.

Proceed silently when these files do not exist. Create them only when the first term or qualifying
decision is resolved.

## During the interview

- Challenge a term that conflicts with the existing glossary.
- Replace vague or overloaded language with one precise canonical term.
- Use concrete edge cases to test boundaries and relationships.
- Compare claims with the code and surface contradictions.
- Use glossary terms in map and ticket titles.

## Capture terminology

Update the relevant `CONTEXT.md` as soon as a term is resolved. Keep it a glossary, not a
specification or implementation guide. Follow [the context format](context-format.md).

## Capture durable decisions

Offer an ADR only when all three tests pass:

1. Reversing the decision would be expensive.
2. A future reader would find it surprising without context.
3. The decision resolved a real trade-off.

If any test fails, keep the decision in its decision-navigator ticket. When all pass, follow
[the ADR format](adr-format.md).

If a proposed decision conflicts with an existing ADR, name the conflict and ask whether the old
decision should be reopened. Never overwrite it silently.
