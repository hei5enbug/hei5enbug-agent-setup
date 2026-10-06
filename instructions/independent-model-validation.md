# Independent model validation

Use this English file as the single canonical source for independent validation of implementation plans,
technical design documents, RFCs, and completed implementation changes. `independent-model-validation.ko.md`
is a non-authoritative Korean translation for human readers; never read it during execution.

## Confirmation gate

Independent validation runs only when the user approves it for the current deliverable. For a requested plan,
design, or RFC, offer review after the draft is complete. For implementation, recommend it once after the
change and its checks are ready when behavior, public contracts, security, concurrency, migrations, or several
components materially change. Skip routine small edits unless the user requests review.

Ask for every deliverable that lacks existing approval: name the reviewer model and reasoning effort below
in one short question and wait for the answer. Reuse explicit approval for this result; agreement to the
general workflow is not approval to invoke a reviewer. Finish all work independent of that answer first.
If the required reviewer is already known to be unavailable, report the limitation and finish without a call.

When the user declines, or the session cannot obtain an answer, skip the review and finish. Keep the
deliverable exactly as drafted, write nothing about the skipped review inside it, and say in the reply that
independent validation did not run. Do not ask again for the same draft.

## Reviewer selection

After the user approves the gate above, send the completed draft to exactly one reviewer from the other
model family in a read-only session. Give the reviewer the frozen intent, relevant authoritative evidence,
and the complete draft. The reviewer returns findings only; the authoring session keeps every final
decision.

Use this model mapping:

Select the actual authoring model family, not the execution host. GPT authoring in Claude Code follows the
GPT row. If both families materially contribute, record their contribution and use the final authoring
family for the one approved reviewer. Do not claim independence from every contributor or add review calls.

| Authoring model family | Review model | Reasoning effort |
|---|---|---|
| GPT | `claude-fable-5-1` | `xhigh` |
| Claude | `gpt-6.1-sol` | `xhigh` |

Use the pinned model ID exactly and record it. Do not look up a newer release, follow a provider alias, or
substitute the authoring family, another model tier, or lower reasoning effort. The reviewer must not edit
the draft, repository, or external state.

Keep the main session's model and effort unchanged. Pass the reviewer's model and effort explicitly to a
separate host runner, enforce read-only tools or sandbox, and verify the actual model and effort from host
records before counting the review as complete. A silent fallback or effort cap is not a completed review.
Do not enable extra billing or change authentication to make the review available.

For an implementation review, provide the accepted scope, complete change diff, relevant source paths,
acceptance criteria, and check results instead of the conversation history. Include necessary untracked
files; a tracked-only diff can omit the implementation. Return concise findings with severity and evidence.

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

For completed implementation, also check:

- Correctness, regressions, permission boundaries, and failure handling
- Missing acceptance checks or unsupported claims of successful verification
- Integration conflicts, unsafe concurrency, and incomplete main-session fallback

For a technical design document or RFC, also check:

- Current-state discussion that does not support a target decision
- Missing or imprecise contracts, constraints, alternatives, or material trade-offs
- Unrequested implementation steps, low-level detail, or extension points

## Execution boundary

This is one validation pass, not a debate. Do not ask the reviewer to revise its answer, invoke another
reviewer, or repeat validation after finalization. A failed or unavailable reviewer does not authorize a
second model call. A declined gate authorizes no substitute independent review. Routine author inspection
and required tests still run; never label them independent validation.

If the required model, effort, read-only execution, or model runner is unavailable, do not substitute
another configuration or present author inspection as independent review. Finish work that does not depend on
the reviewer and report that independent validation was not performed and why.

## Finalization

The authoring session checks every finding against the frozen scope and authoritative evidence, applies
supported corrections once, and rejects unsupported scope expansion. Do not run another model review after
the corrections.

Report the resolved reviewer model, reasoning effort, that one read-only pass ran, and any unresolved
finding. When validation could not run, report the unavailable requirement and reason instead. When the user
declined the gate, report only that independent validation did not run. Every one of these results belongs
in the reply, never in the deliverable.
