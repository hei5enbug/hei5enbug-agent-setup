# Implementation execution

Implementation means changes to code, tests, configuration, scripts, skills, instructions, and documentation
that implement an agreed change, including integration fixes. The main session is the coordinator: it keeps
requirements, investigation, planning, design, review, decisions, and the final report. Writing a plan or
design document the user requested also stays in the main session. Choose main or worker ownership under the
session delegation rules; main-owned implementation is allowed and uses the same acceptance checks.

The session rules still own high-level reasoning, clarification, and permission decisions. Before delegating
implementation, including UI or design work, to a worker or designer, also read
[implementation delegation](implementation-delegation.md).

## Task preparation

Before the first implementation change, read [implementation rules](implementation-rules.md).

Before the first change of a request that has at least two deliverables that can be verified separately and an
unresolved decision whose options lead to materially different accepted results, or when the user asks for a
requirements agreement or interview by name, read [requirements agreement](requirements-agreement.md).

Before the first implementation change, have an executable task assignment for every change.
For substantial work, apply [work efficiency](work-efficiency.md) to required results, optional follow-ups,
stop conditions, and check-evidence reuse. Keep these fields with the existing assignment.

| Starting condition | Required action |
|---|---|
| Complete existing plan | Verify its scope, prerequisites, and worker assignments against current evidence; reuse unchanged parts. |
| Plan lacks execution detail | Add ownership, dependencies, parallel conditions, model/effort policy, and checks before editing. Preserve its accepted design. |
| No plan | Prepare a compact execution plan in the session's native task facility or the conversation. Create no plan directory unless requested. |
| Material requirement or design decision remains open | Investigate and resolve it in the main session before dispatch under the clarification rules. |
| Existing assigned worker | Follow "Assigned workers" in implementation delegation. Report a missing decision or conflict to the coordinator, and never start another planning workflow. |

When a ticket, an accepted plan, or your own earlier scope summary lists work items for the task, compare the
user's instruction with that list before the first change. An item the instruction does not mention is a
result-changing ambiguity, not a sign that it is out of scope: ask one question with these options in this order,
include now, defer within the same ticket, split into a new ticket, or drop, and change nothing until the user
answers. When the user explicitly narrows the scope, ask nothing and record each excluded item with its destination.

This preparation is not a requested implementation plan. It runs no planning or design skill, no six-stage
planning workflow, and no independent validation.

When a request is clear, make the change it asks for and only these follow-on edits: existing text that the change
made false, and text that a repository rule requires for something the change adds, such as a new command or option.
Add no other design, tests, implementation, documentation, or planning that the request did not ask for.

When a request does not start the agreement and the evidence shows that the requested method cannot reach the stated
goal, or that an existing mechanism of the repository or a supported feature of its tools reaches it with less
change, state that evidence and ask which to use before the first change. When a decision changes requirements,
policy, recurring cost, or compatibility, ask it; decide every other implementation choice and state it with its
basis.

Prepare the fewest tasks that give clear ownership. One cohesive task uses one owner. The limit the plugin
reports is an upper bound, not a target; never split work or batch unrelated reads merely to fill slots.

At any point, ask the user before assigning a change to a tracked file outside the request or the accepted plan,
such as a shared file that no task may edit. Wait for the answer, and make no such change without approval.

## Assignment fields

Each assignment states:

- Task ID and the concrete result
- Allowed edit paths and protected paths
- Prerequisites and shared-resource exclusions
- Verification and completion evidence; a read-only result starts with the status and path coverage that the
  scout definition sets
- The selected model ID and effort
- The skill the worker must load, only when the task names one

For main-owned work, keep these fields compact and retain the main session's current model and effort.
Worker model checks and readiness calls apply only when delegating; do not perform them for direct work.

## Acceptance

Use the [check-evidence rules](work-efficiency.md#check-evidence) when accepting results and choosing integration
checks. The main session checks scope, correctness, regressions, and test evidence for all work, including its own.
A check that mutates tracked files is implementation work and needs an owner. A failed assigned check is a failure
even when the cause lies outside the task.

Before reporting the work finished, and before each commit or push, list every check that the project instructions
or a skill you used or changed require for this change, such as an evaluation, a test run, or a final review, and
show each as done, or as not done with its reason. Never waive one by your own judgment of the change's size or kind.
Do not commit or push while one is not done unless the user agrees after seeing that list.

## Unfinished agreed items

While an agreed item of the task's ticket or plan is not done, open every later report with it: the first sentence
names the item, says it is not done, and gives its decided destination, and the results follow. State it again at
each later milestone of the same ticket, such as a pull request description, a QA or approval report, and a closing
proposal. Before proposing to close a ticket, list each agreed item as done or not done, and do not propose closing
while one is not done unless the user decided where it goes.
