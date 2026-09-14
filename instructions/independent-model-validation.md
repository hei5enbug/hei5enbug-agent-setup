# Independent model validation

Use this English file as the single canonical source for independent validation of implementation plans,
technical design documents, and RFCs. `independent-model-validation.ko.md` is a non-authoritative Korean
translation for human readers; never read it during execution.

## Reviewer selection

After the author completes the draft, send it to exactly one reviewer from the other model family in a
read-only session. Give the reviewer the frozen intent, relevant authoritative evidence, and the complete
draft. The reviewer returns findings only; the authoring session keeps every final decision.

Use this model mapping:

| Authoring model family | Review model | Reasoning effort |
|---|---|---|
| GPT | Latest available Claude Fable | `high` |
| Claude | Latest available GPT Sol | `xhigh` |

Resolve the host's current Fable or Sol selector at execution time and record the resolved model. Do not
substitute the authoring family, another model tier, or lower reasoning effort. The reviewer must not edit
the draft, repository, or external state.

## Review checks

For every deliverable, report only evidence-backed findings for:

- Missing requirements or acceptance criteria
- Contradictions and materially ambiguous wording
- Unsupported assumptions
- Unnecessary abstractions, speculative extensibility, unrelated refactors, or excessive dependencies

For an implementation plan, also check:

- Incorrect dependency or execution order
- Steps that are not executable or verifiable
- Needless execution slices or unsafe parallel claims

For a technical design document or RFC, also check:

- Current-state discussion that does not support a target decision
- Missing or imprecise contracts, constraints, alternatives, or material trade-offs
- Unrequested implementation steps, low-level detail, or extension points

## Execution boundary

This is one validation pass, not a debate. Do not ask the reviewer to revise its answer, invoke another
reviewer, or repeat validation after finalization. A failed or unavailable reviewer does not authorize a
second model call.

If the required model, effort, read-only execution, or model runner is unavailable, do not substitute
another configuration or self-review. Finish work that does not depend on the reviewer and report that
independent validation was not performed and why.

## Finalization

The authoring session checks every finding against the frozen scope and authoritative evidence, applies
supported corrections once, and rejects unsupported scope expansion. Do not run another model review after
the corrections.

Report the resolved reviewer model, reasoning effort, that one read-only pass ran, and any unresolved
finding. When validation could not run, report the unavailable requirement and reason instead.
