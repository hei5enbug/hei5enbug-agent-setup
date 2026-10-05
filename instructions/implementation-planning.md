# Implementation planning

Use this English file as the canonical executable source. `implementation-planning.ko.md` is a
non-authoritative Korean translation for human readers; never read it during execution.

Apply this file only when the user explicitly requests an implementation plan. An implementation plan lets
an executor make the requested change without adding design decisions. It freezes intent and scope,
identifies concrete change surfaces and dependencies, divides execution without needless fragmentation, and
states proportionate verification.

Run all six stages in order. Keep reasoning and final decisions in the main session. The independent
reviewer checks the completed draft but does not own decisions or edit files.

## 1. Intent and scope freeze

Freeze the following from the request and authoritative evidence before choosing implementation details:

- Goal and observable outcome
- In-scope behavior and artifacts
- Non-goals
- Constraints and invariants
- Files, interfaces, data, or behavior that must not change
- Acceptance criteria

Separate required acceptance criteria from optional follow-ups and state stop conditions under
[work efficiency](work-efficiency.md#scope-and-completion). Do not invent a completion gate from optional work.

Resolve any missing decision that permits materially different implementations. Do not widen scope to
repair adjacent issues unless the user includes them or the requested result cannot work without them.

## 2. Implementation planning

Choose the smallest implementation strategy that satisfies the frozen scope. Name the concrete modules,
files, interfaces, schemas, configuration, migrations, and tests that must change when evidence identifies
them. State behavior and contract changes before listing file edits. Record dependencies and prerequisite
decisions instead of hiding them inside execution steps.

Do not add speculative extension points, new abstractions without a present requirement, unrelated
refactors, or dependencies whose benefit is not required by the acceptance criteria.

## 3. Execution slicing

Create the fewest execution slices that give an executor clear ownership and verification boundaries.
For each slice, state its result, affected surfaces, prerequisites, and completion evidence. Mark slices
parallel only when they share no files, mutable state, generated output, or build contention. Order every
other dependency explicitly.

Check each prerequisite against the outputs of earlier steps. Perform a state change before validating its
result; separate pre-change checks from post-change checks instead of making the latter a prerequisite for
the change. Resolve dependency cycles before finalizing the plan.

Do not split a cohesive change into bookkeeping steps. A slice should produce a reviewable behavior,
contract, migration, or verification result rather than merely open, rename, or inspect a file.

Give each slice one main or worker owner under the session delegation rule, and record the assignment fields from
[implementation execution](implementation-execution.md) once in the plan. State the worker model and effort
for delegated slices as that file's host policy, which the host's agent rules pin, instead of copying a model ID.
Main-owned slices retain the main session's current model and effort.

## 4. Verification planning

Map every acceptance criterion and material risk to evidence. Give each execution slice the narrowest
check that proves its result, then define integrated checks for cross-slice behavior. Include compatibility,
failure, migration, rollback, security, or performance checks only when the frozen scope or risk requires
them. Never use a narrow unit check to claim repository-wide or runtime behavior.
Identify reusable evidence and its invalidation conditions under the
[check-evidence rules](work-efficiency.md#check-evidence) instead of scheduling duplicate checks by owner.

## 5. Plan validation

Apply [independent model validation](independent-model-validation.md) to the completed draft. That reference
owns the user confirmation gate, the reviewer input, model selection, review checks, execution boundary,
failure handling, and result reporting. Do not send the draft to a reviewer before that gate passes.

## 6. Plan finalization

When validation ran, check every reviewer finding against the frozen scope and authoritative evidence. Apply
supported corrections in the main session. Reject unsupported scope expansion and record a material
unresolved finding when evidence cannot settle it. Do not restore overdesign that the review removed. When
validation did not run, finalize from the frozen scope and authoritative evidence alone.

Do not finalize while a missing decision still permits materially different implementations. Ask the user
to resolve that decision. Otherwise, finalize the smallest plan that an executor can run without adding a
design decision, and report the result under the shared validation contract.

## Output template

Adapt headings to an established repository template when it preserves the same contract. Omit an optional
section rather than filling it with placeholders.

```markdown
# <Outcome-oriented title>

## Intent and scope

- Goal:
- In scope:
- Non-goals:
- Constraints:
- Protected surfaces:
- Acceptance criteria:
- Optional follow-ups:
- Stop conditions:

## Implementation strategy

<Selected behavior and contract changes, affected surfaces, dependencies, and rationale>

## Execution slices

Worker model and effort: <host policy from the implementation execution rules, pinned by the host's agent rules>

| Slice | Result and changes | Allowed and protected paths | Depends on | Shared resources and parallel condition | Verification and completion evidence |
|---|---|---|---|---|---|

## Integrated verification

<Acceptance-criterion and risk coverage across slices>

```

## Completion checks

- Scope, non-goals, constraints, protected surfaces, and acceptance criteria are explicit where applicable.
- Every step is executable and has proportionate completion evidence.
- Dependencies and order are correct; parallel claims have no shared mutation or build contention.
- Every slice has one main or worker owner and the shared assignment fields.
- No speculative extension, unrelated refactor, excessive dependency, or needless slice remains.
- The shared independent validation contract is satisfied.
- No unresolved decision requires the executor to add design.
