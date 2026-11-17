# Independent model validation

Use this English file as the single canonical source for independent validation of implementation plans,
technical design documents, RFCs, issue bodies, and completed implementation changes.

## When to review

Run independent validation automatically, without a question, exactly once per request: in its final stage, when
no other work remains, over the combined result of every worker and the main session. For a requested plan, design,
or RFC, that is the complete draft. For a request that files or rewrites one or more issues whose proposals change
behavior, a public contract, or several components, it is the bodies of all those issues as one complete draft,
reviewed before the first write to the tracker with the owning files as evidence. For implementation, it is the final
change with its passing checks when behavior, public contracts, security, concurrency, migrations, or several
components materially change. Skip routine small edits unless the user requests review. A change made to fix performance or resource use, or one that
changes how much work a code path does, is never a routine small edit.

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
| GPT | `claude-opus-5-5` or `claude-fable-5-2` | `high` or `xhigh` |

The coordinating session picks one reviewer and effort from the row by scope and risk: the lighter model
(`gpt-6.1-sol`, `claude-opus-5-5`) at `high` for one bounded component, and the stronger model (`gpt-6-astra`,
`claude-fable-5-2`) or `xhigh` for several components, a public contract, security, concurrency, or a hook or guard.

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
acceptance criteria, and check results instead of the conversation history. Also provide the callers and consumers
of each changed function, contract, schema, or setting that the author found, and baseline measurements, such as a
previous run time, when the change can affect them. Include necessary untracked files; a tracked-only diff can omit
the implementation. Return concise findings with severity and evidence, and name
the one fact the change is safe because of and how far it was proven: asserted, cited at `file:line`, argued step by
step, executed by a script or test, or reproduced in the running app.

## Review checks

Zero findings is a valid result. Report only findings you are confident are real, each backed by evidence, for every
deliverable:

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
- Side effects: trace each changed function, contract, schema, or setting to its callers, consumers, stored data,
  and deployment configuration, and report only effects reached on a traced path
- Compute and resource efficiency at a realistic input size: repeated expensive work inside loops, N+1 queries or
  calls, unbounded scans or loads, memory that grows with input, and run time against a given baseline

For a technical design document or RFC, also check:

- Current-state discussion that does not support a target decision
- Missing or imprecise contracts, constraints, alternatives, or material trade-offs
- Unrequested implementation steps, low-level detail, or extension points

## Execution boundary

This is one validation pass, not a debate. Do not ask the reviewer to revise its answer, invoke another
reviewer, or repeat validation after finalization. A repeat the user asks for follows
"Repeated review on request". A failed or unavailable reviewer does not authorize a
second model call. A declined earlier review authorizes no substitute independent review. Routine author
inspection and required tests still run; never label them independent validation.

If the required model, effort, read-only execution, or model runner is unavailable, do not substitute
another configuration or present author inspection as independent review. A role runner exit code 3 or 4
means the same. Finish work that does not depend on the reviewer and report that independent validation was
not performed and why.

## Repeated review on request

Follow this section when the user asks to repeat a review and fix its findings until a round returns no findings,
or answers a review's stop by asking to go on. A round is one review of the reviewed set. Count rounds from the
request or from the user's latest answer to go on.

- Before the first round, tell the user in one line that the loop stops and reports after every three rounds that
  still return findings. Ask nothing then.
- A round that returns no findings ends the loop, and the work goes on at once.
- Keep the first round's reviewers and reviewed set in every round. Change a reviewer, the reviewed set, or the
  severity to fix only after the user chooses it at a stop. A rise or fall in the count never stops the loop by
  itself.
- When the third round still returns findings, apply them under Finalization and the review-fix rule of the session
  instructions, then stop before the next round and write nothing outward. Report so that the user can tell:
  - the findings of each round by severity, and the reviewers and the reviewed set of each round;
  - how many findings an earlier round's fix caused or left behind in another passage, and how many are in text the
    loop never changed;
  - whether any finding is high severity or contradicts a confirmed decision.
- Then ask once, with one recommendation, whether to go on unchanged, to narrow the reviewed set, the reviewers, or
  the severity to fix, or to stop and write now. When the user chooses to write now, the work's report states that
  the last round's fixes were not reviewed.
- Inside such a loop, the stops of "Independent text review" in [shared text](shared-text.md) for a repeated finding
  and for a finding only the user can decide still apply.

Example report for a different case: "Rounds 1 to 3 returned 9, 7, and 8 findings from the same two reviewers, none
high and none against a decision; 6 of round 3's findings were copies that a round-2 fix missed, and I fixed all 8. I
recommend one more pass over the two pages to be published, fixing medium or higher."

## Finalization

The authoring session checks every finding against the frozen scope and authoritative evidence and sorts it
into fix now, worth considering, note only, or rejected, each with a one-line reason. A finding without a traced
reachable caller or input path is a possibility, never fix now, until traced. Apply supported fix-now corrections
once, and reject unsupported scope expansion. Do not run another model review after the corrections, except a repeat
the user asks for under "Repeated review on request".

When the session applies review findings outside the text review, it compares each corrected passage with the
confirmed decisions and the authoritative evidence before the next round or the write, and corrects one that departs
from them.

When a worker applies review findings, its assignment gives the point, the reason, and the evidence of each finding.
It asks the worker to change every passage in its allowed paths that states the same point and to compare each change
with that evidence, and it never limits the worker to a list of sentences.

Report the resolved reviewer model, reasoning effort, that one read-only pass ran, each finding's category and
reason, the safety fact and its proof level for an implementation review, and any unresolved finding. When validation could not run, report the unavailable requirement and reason instead. When the user
declined an earlier review, report only that independent validation did not run. Every one of these results belongs
in the reply, never in the deliverable.
