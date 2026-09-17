# Design document workflow

Use this reference only for Create and Improve modes after `SKILL.md` directs you here. It defines the
design-document boundary and output template. The session-level independent model validation reference
defines reviewer selection, model configuration, review checks, and finalization.

## Target design boundary

A design document communicates the selected target design. It emphasizes contracts, constraints, behavior,
alternatives, and trade-offs. Describe defects in the current design only as far as they explain a target
decision. Treat an RFC as a design document unless the user explicitly requests an execution-ready plan.

Do not turn a design document into an implementation plan. Include execution slices or work order only when
the user requests them or when order is necessary to establish feasibility, migration safety, or
compatibility. Do not add unrequested implementation detail, speculative extension points, or unrelated
refactors.

When implementation plan and design document interpretations both remain plausible and the choice would
materially change content, structure, scope, or acceptance criteria, explain the alternatives and ask the
user before drafting. When the user's terms, a repository template, or an established project contract
resolves the type, apply that evidence.

## Workflow

1. Freeze the design goal, scope, non-goals, constraints, protected contracts, audience, acceptance
   criteria, and evidence sources. For an existing document, identify unsupported claims, missing design
   coverage, and rule violations.
2. Build a private coverage matrix from `SKILL.md`. Mark each concern applicable or inapplicable with a
   reason. Finalize second-level headings before drafting: give the document one reader goal, give each
   section one responsibility, remove repeated summaries, order prerequisites before dependent decisions,
   and verify that every applicable concern has one home.
3. Gather source contracts and evidence. Prefer requirements, code, schemas, configuration, measured results,
   and official interfaces over descriptive prose. Draft the opening first, then describe the target design,
   boundaries, behavior, contracts, failure handling, constraints, alternatives, and trade-offs in the target
   language. Apply the precision, structure, table, diagram, and language rules in `SKILL.md`.
4. Plan terminology changes for the entire affected scope. Update references and cited headings together.
   Ask before renaming implementation identifiers or externally visible contract names. When a decision
   reverses an earlier one, update every document that records the earlier decision and explain why its
   original rationale no longer holds.
5. Validate copied contracts, examples, commands, links, calculations, and diagrams with the strongest
   available method. Separate unsupported content under `SKILL.md`, remove drafting notes and unnecessary
   content, record actual removals, and run the completion gate.
6. Apply the independent model validation reference supplied by the session instructions. It owns the user
   confirmation gate, reviewer selection, model configuration, review checks, failure handling,
   finalization, and result reporting. Do not send the document to a reviewer before that gate passes.

## Output template

Adapt headings to an established repository template when it preserves the same contract. Omit an optional
section rather than filling it with placeholders.

```markdown
# <Target design title>

<Decision summary and reader outcome>

## Goals and scope

<Goals, non-goals, constraints, assumptions, and protected contracts>

## Target design

<Boundaries, behavior, data, interfaces, invariants, and failure handling>

## Alternatives and trade-offs

<Decision-relevant alternatives and reasons for the selected design>

## Change and proof

<Migration or compatibility details when applicable, acceptance criteria, and validation>

## Assumptions and open questions

<Only material unsupported claims and unresolved decisions; omit when empty>
```

## Completion checks

- Every section contributes to the target design or a decision needed to approve it.
- Current-state discussion is limited to evidence that motivates a target decision.
- Contracts, constraints, alternatives, and material trade-offs are complete and precise.
- Execution order appears only when requested or needed to establish feasibility, safety, or compatibility.
- No speculative extension, unrelated refactor, or unrequested low-level detail remains.
- The shared independent validation contract is satisfied, including its gate and the user's answer.
