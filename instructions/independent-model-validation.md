# Independent model validation

Use this English file as the single canonical source for independent validation of implementation plans,
technical design documents, RFCs, and completed implementation changes.

## When to review

Run independent validation automatically, without a question, exactly once per request: in its final stage, when
no other work remains, over the combined result of every worker and the main session. For a requested plan, design,
or RFC, that is the complete draft. For implementation, it is the final change with its passing checks when
behavior, public contracts, security, concurrency, migrations, or several components materially change. Skip
routine small edits unless the user requests review.

Any earlier review, such as one of a single worker's change or of an intermediate draft, runs only when the user
approves it for that deliverable: name the reviewer model and reasoning effort in one short question and wait for
the answer. Finish all work independent of that answer first. When the user declines, or the session cannot obtain
an answer, skip that review, write nothing about it inside the deliverable, and do not ask again for the same draft.
An assigned worker, and a skill run inside a larger request, never runs its own final review; the coordinating
session runs the one final review. If the required reviewer is already known to be unavailable, report the
limitation and finish without a call.

## Reviewer selection

When the review is due under the rule above, send the completed draft to exactly one reviewer that the mapping
below selects, in a read-only session. Give the reviewer the frozen intent, relevant authoritative evidence,
and the complete draft. The reviewer returns findings only; the authoring session keeps every final
decision.

| Authoring model family | Reviewer | Reasoning effort |
|---|---|---|
| Claude | `gpt-6.1-sol` or `gpt-6-astra` | `high` or `xhigh` |
| GPT | `claude-opus-5-5` or `claude-fable-5-1` | `high` or `xhigh` |

The coordinating session picks one reviewer and effort from the row by scope and risk: the lighter model
(`gpt-6.1-sol`, `claude-opus-5-5`) at `high` for one bounded component, and the stronger model (`gpt-6-astra`,
`claude-fable-5-1`) or `xhigh` for several components, a public contract, security, concurrency, or a hook or guard.

Select the actual authoring model family, not the execution host. Code that a delegated worker wrote belongs to
that worker's model family. GPT authoring in Claude Code follows the GPT row. If both families materially
contribute, record their contribution and use the final authoring family for the one reviewer. Do not claim
independence from every contributor or add review calls.

Use the pinned model ID exactly and record it. Do not look up a newer release, follow a provider alias, or
substitute another model tier or a lower reasoning effort than this selection. The reviewer must not edit
the draft, repository, or external state.

Keep the main session's model and effort unchanged. Pass the reviewer's model and effort explicitly to a
separate host runner, enforce read-only tools or sandbox, and verify the actual model and effort from host
records before counting the review as complete. A silent fallback or effort cap is not a completed review.
Do not enable extra billing or change authentication to make the review available.

For an implementation review, provide the accepted scope, complete change diff, relevant source paths,
acceptance criteria, and check results instead of the conversation history. Include necessary untracked
files; a tracked-only diff can omit the implementation. Return concise findings with severity and evidence, and name
the one fact the change is safe because of and how far it was proven: asserted, cited at `file:line`, argued step by
step, executed by a script or test, or reproduced in the running app.

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
second model call. A declined earlier review authorizes no substitute independent review. Routine author
inspection and required tests still run; never label them independent validation.

If the required model, effort, read-only execution, or model runner is unavailable, do not substitute
another configuration or present author inspection as independent review. A role runner exit code 3 or 4
means the same. Finish work that does not depend on the reviewer and report that independent validation was
not performed and why.

## Finalization

The authoring session checks every finding against the frozen scope and authoritative evidence and sorts it
into fix now, worth considering, note only, or rejected, each with a one-line reason. A finding without a traced
reachable caller or input path is a possibility, never fix now, until traced. Apply supported fix-now corrections
once, and reject unsupported scope expansion. Do not run another model review after the corrections.

Report the resolved reviewer model, reasoning effort, that one read-only pass ran, each finding's category and
reason, the safety fact and its proof level for an implementation review, and any unresolved finding. When validation could not run, report the unavailable requirement and reason instead. When the user
declined an earlier review, report only that independent validation did not run. Every one of these results belongs
in the reply, never in the deliverable.
