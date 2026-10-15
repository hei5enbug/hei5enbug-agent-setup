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

This preparation is not a requested implementation plan. It runs no planning or design skill, no six-stage
planning workflow, and no independent validation.

Prepare the fewest tasks that give clear ownership. One cohesive task uses one owner. Six workers are an
upper bound, not a target; never split work or batch unrelated reads merely to fill slots.

At any point, ask the user before assigning a change to a tracked file outside the request or the accepted plan,
such as a shared file that no task may edit. Wait for the answer, and make no such change without approval.

## Assignment fields

Each assignment states:

- Task ID and the concrete result
- Allowed edit paths and protected paths
- Prerequisites and shared-resource exclusions
- Verification and completion evidence
- The selected model ID and effort

For main-owned work, keep these fields compact and retain the main session's current model and effort.
Worker model checks and readiness calls apply only when delegating; do not perform them for direct work.

## Acceptance

Use the [check-evidence rules](work-efficiency.md#check-evidence) when accepting results and choosing integration
checks. The main session checks scope, correctness, regressions, and test evidence for all work, including its own.
A check that mutates tracked files is implementation work and needs an owner. A failed assigned check is a failure
even when the cause lies outside the task.
