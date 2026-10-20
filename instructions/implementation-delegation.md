# Implementation delegation

Read this file before delegating implementation to a worker or designer, after
[implementation execution](implementation-execution.md). The current host's agent rules own its worker tool, pinned
model, and configuration evidence. An assigned worker receives the "Assigned workers" section below in its session
instructions or assignment and does not read this file.

A text- or style-value-only edit that keeps layout and component structure may go to the implementation worker
instead of the designer.

## Worker assignments

Every worker assignment also tells the worker that it is an assigned worker, that other workers may be editing the
workspace, and that it must preserve their changes. A repository execution plan records these fields once.
Each worker prompt carries only its own task and the context that task requires. Point to files and line ranges
instead of pasting their content.

## Scheduling

Track each task as `pending`, `running`, `done`, or `blocked` with the host's existing task facility or the
conversation. Add no persistent task database. A task becomes ready only after its prerequisites pass the
coordinator's acceptance check and its edit paths and resources are free. Acceptance requires the task's
assigned verification to pass. Never put a task and its prerequisite in one assignment. Tasks that only share
files may go to one worker in sequence.

Start at most `min(6 - active implementation workers, host slots remaining, ready independent tasks)`
additional workers. Use the host's actual limit definition and available slots; the limit may count the main
session or other agents. For example, a four-agent limit that includes the main session permits at most
three workers.

Launch independent ready tasks together. Queue any excess task, such as a seventh, and dispatch it when a
slot and its resources are free. Never ask to raise the host limit.

Never overlap conflicting ownership. Shared files, lockfiles, generated outputs, databases, ports, or build
directories make tasks sequential unless the plan supplies independent resources for each task. Disjoint
files alone do not prove independence.

## Review and integration

A worker's valid result does not need a duplicate run merely because ownership changed.

Review each worker's returned changes and evidence before releasing dependent work. Accept delegated work only
when the host record, or the enforcement the host's agent rules name (such as the mod's role pinning or the role
runner's verification), shows the selected model and effort for every turn that edited it. The main session may make
integration fixes when it owns those paths; otherwise wait for the current worker to stop before transferring
ownership. Never run a shared build while workers mutate its inputs or output directories.

## Failure and recovery

On failure, hold dependent tasks and preserve completed work. Diagnose and settle the correction in the main session.
Resume or replace a worker only after the previous owner has stopped, and give the new owner the current diff and
the revised task.

On a delegation failure, apply the session fallback rule. Stop the affected worker before taking ownership,
inspect its partial diff, and continue the remaining authorized work through the host's named fallback route, or
in the main session when there is none. Do not accept an
unverified worker result as complete. Keep completed checks only while their inputs remain unchanged.
Do not repeatedly retry a known quota or capability failure; reconsider only after evidence of a change.
Fallback never bypasses a missing user decision, permission restriction, or failed acceptance check.

## Model and effort

For delegated implementation, use the model ID and effort that the host's agent rules pin. Never look up a
newer release, follow a provider alias, or substitute another worker model at runtime, except through a
fallback route that the host's agent rules name; the repository updates its pins when it changes. If the pinned
model or effort is unavailable, use that named fallback route or else the session fallback instead of selecting
another worker model.

Record the pinned model ID and effort in each worker assignment, and reuse them for that run.

Inspect only relevant non-secret configuration fields. A requested setting alone is not evidence of the
effective setting. The minimum evidence is the explicit invocation or pinned definition, a host record naming
the actual model, and the effective effort under the host's documented configuration precedence. A missing
capability, an unexpected override, or unverified effective settings stops delegation, not authorized main work.

When launch metadata is insufficient, use a readiness-only assignment only if the host can send a follow-up to
the same worker while preserving or explicitly reapplying its verified settings. Verify the host record, then
send the implementation assignment. Without that continuation or reliable configuration evidence, skip this
path and use the session fallback. A worker's unsubstantiated self-report never replaces host evidence.

Recheck after a resume, an override change, a substitution warning, or a host configuration change. A mismatch
stops the affected worker. Reuse verified settings while their inputs remain unchanged; do not repeat readiness
calls before every edit.

## Assigned workers

An assigned worker executes its task directly and never acts as a coordinator.

- Never prepare a plan, start a planning or design workflow, request plan review or independent validation, or
  start another agent.
- Edit only the allowed paths, leave protected paths untouched, and preserve changes made by other workers.
- Never widen scope, choose a new design, or change model or effort. Report a missing decision or a conflicting
  change to the coordinator instead of resolving it.
- Run only the assigned checks, with the isolation flags the assignment gives.
- For a readiness-only assignment, make no edit and report readiness.
- Return the changed paths, check results, and remaining blockers.
