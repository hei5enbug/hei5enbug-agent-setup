---
name: architecture-docs-guide
description: Methodology for writing lightweight architecture and development design documents focused on intent, constraints, decisions, trade-offs, quality goals, and reader-fit structure.
---

# Architecture Docs Guide

Use this skill to write or review lightweight architecture and development design documents. The guide is methodology-first: preserve reusable writing decisions, not project-specific file names, local paths, issue IDs, tool commands, or platform-specific formatting details.

## When to Use

- Drafting a design document, architecture note, technical proposal, RFC, or ADR.
- Turning scattered implementation context into a reader-oriented design narrative.
- Reviewing whether a design document explains the why behind a technical direction.
- Simplifying an over-detailed document into durable principles, decisions, and trade-offs.

## Core Method

1. **Set the document intent.** Decide whether the reader needs explanation, reference, decision history, or an implementation-ready design. Treat document taxonomies as guides, not mandatory section plans.
2. **Define the reader contract.** Name what the reader should understand, decide, or do after reading.
3. **Filter for architectural significance.** Include only requirements that change structure, constraints, quality goals, dependencies, or decision trade-offs.
4. **Choose the right level of detail.** Travel light by default; increase depth only when the reader cannot make or review the decision without it.
5. **Write around decisions.** For each important choice, state context, decision, alternatives considered, consequences, and open risks.
6. **Use diagrams and tables as thinking tools.** Add only the abstraction levels that clarify relationships or trade-offs better than prose.
7. **Verify reader usefulness.** Check whether a new reader can explain the system boundary, key decisions, trade-offs, and next actions without asking the author.

## Document Shape

Prefer this shape unless the user provides another template:

1. **Context** — problem, scope, reader assumptions, and non-goals.
2. **Forces and constraints** — quality goals, external constraints, and architectural drivers.
3. **Proposed design** — boundaries, responsibilities, interactions, and key abstractions.
4. **Decisions and trade-offs** — accepted choices, rejected alternatives, consequences.
5. **Risks and validation** — unknowns, failure modes, evidence needed, review gates.
6. **Open questions** — decisions that remain unresolved and who should decide them.

## Keep / Remove Rule

Keep content when it answers at least one of these questions:

- Why is this design necessary?
- What constraints shaped the design?
- What decision was made, and what alternatives were rejected?
- What quality attribute does this protect or trade off?
- What must future maintainers preserve when changing the system?

Remove or move content when it is only:

- A local file path, branch, commit, ticket, or environment detail.
- A runbook step or temporary operational instruction.
- A full implementation example where a contract or responsibility summary is enough.
- A platform-specific formatting rule unrelated to the design method.
- A repeated definition that should be expressed once and referenced conceptually.

## Decision Record Minimum

For any meaningful design choice, capture:

- **Context** — what pressure or constraint forced a decision.
- **Decision** — what was chosen.
- **Alternatives** — what else was considered.
- **Consequences** — benefits, costs, risks, and reversibility.
- **Review trigger** — what future signal should reopen the decision.

## Quality Bar

A good design document passes when a reader can answer:

- What is in scope and out of scope?
- What are the architectural drivers?
- What changed because of this design?
- What trade-offs were accepted?
- What risks remain unresolved?
- What evidence would prove the design works?

If the document cannot answer these questions, add methodology-level explanation before adding implementation detail.
