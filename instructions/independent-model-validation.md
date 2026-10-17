# Independent model validation

Use this English file as the single canonical source for independent validation of implementation plans,
technical design documents, RFCs, and completed implementation changes.

## Confirmation gate

For a requested plan, design, or RFC, review once the draft is complete. For implementation, review once after
the change and its checks are ready when behavior, public contracts, security, concurrency, migrations, or
several components materially change. Skip routine small edits unless the user requests review.

When the reviewer below runs on Codex, the review runs without a question while the Codex weekly usage is at
most 70 percent. Read that usage with `python3 <Source directory>/scripts/codex_usage.py`, where
`<Source directory>` is the line in the session context. Its `weekly_used_percent` is a number, or `null` when
the usage is unknown.

Otherwise, with usage above 70 percent or unknown, or with a reviewer that runs on Claude, independent validation
runs only when the user approves it for the current deliverable. Ask for every deliverable that lacks existing
approval: name the reviewer model and reasoning effort below in one short question and wait for the answer.
Reuse explicit approval for this result; agreement to the general workflow is not approval to invoke a
reviewer. Finish all work independent of that answer first. If the required reviewer is already known to be
unavailable, report the limitation and finish without a call.

When the user declines, or the session cannot obtain an answer, skip the review and finish. Keep the
deliverable exactly as drafted, write nothing about the skipped review inside it, and say in the reply that
independent validation did not run. Do not ask again for the same draft, and do not run an automatic review of a
draft the user declined.

## Reviewer selection

Once the gate above passes, by the usage rule or by the user's approval, send the completed draft to
exactly one reviewer that the mapping below selects, in a read-only session. Give the reviewer the frozen intent, relevant authoritative evidence,
and the complete draft. The reviewer returns findings only; the authoring session keeps every final
decision.

Use this model mapping:

| Authoring model family | Review model | Reasoning effort |
|---|---|---|
| GPT | `claude-fable-5-1` | `xhigh` |
| Claude | the `review_model` setting (default `gpt-6-astra`) | `xhigh` |

Select the actual authoring model family, not the execution host. GPT authoring in Claude Code follows the
GPT row. If both families materially contribute, record their contribution and use the final authoring
family for the one reviewer. Do not claim independence from every contributor or add review calls.
When the configured reviewer is in the authoring family, say in the result that the review is not
cross-family.

Use the pinned model ID exactly and record it. Do not look up a newer release, follow a provider alias, or
substitute another model tier or a lower reasoning effort than the mapping selects. The reviewer must not edit
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
another configuration or present author inspection as independent review. A role runner exit code 3 or 4
means the same. Finish work that does not depend on the reviewer and report that independent validation was
not performed and why.

## Finalization

The authoring session checks every finding against the frozen scope and authoritative evidence, applies
supported corrections once, and rejects unsupported scope expansion. Do not run another model review after
the corrections.

Report the resolved reviewer model, reasoning effort, that one read-only pass ran, and any unresolved
finding. When validation could not run, report the unavailable requirement and reason instead. When the user
declined the gate, report only that independent validation did not run. Every one of these results belongs
in the reply, never in the deliverable.
