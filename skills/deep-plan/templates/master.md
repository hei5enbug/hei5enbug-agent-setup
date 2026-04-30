# {Plan Name}

## Overview
One paragraph: what this plan covers, what it achieves, and the key decisions made.

## Decision Log

| # | Decision | Resolution | Source |
|---|----------|------------|--------|
| 1 | {question} | {chosen option and reasoning} | auto |
| 2 | {question} | {chosen option and reasoning} | user |

## Tasks

| # | Task | Priority | Size | Wave | Deps | Status |
|---|------|----------|------|------|------|--------|
| 001 | [{Title}](./tasks/001-{slug}.md) | critical | medium | W0 | — | pending |
| 002 | [{Title}](./tasks/002-{slug}.md) | high | medium | W0 | — | pending |
| 003 | [{Title}](./tasks/003-{slug}.md) | medium | large | W0 | — | pending |
| 004 | [{Title}](./tasks/004-{slug}.md) | high | small | W1 | 001, 002 | pending |
| 005 | [{Title}](./tasks/005-{slug}.md) | medium | medium | W2 | 004 | pending |

**State transitions:**
- `pending` → `in_progress` → `done` (normal flow)
- `pending` → `cancelled` | `deferred` (scope change)

## Execution Instructions

### Parallel Execution Model

This plan uses **dependency-based parallel execution**. Tasks in the same wave run simultaneously. Start the next task the moment its dependencies are satisfied.

### Execution Procedure

1. Read this master document for overall context.
2. Identify ALL tasks where **every dependency is `done`** and status is `pending`.
3. Execute all identified tasks **in parallel simultaneously**:
   - Read ONLY the linked task document — do not load other task documents.
   - Execute the implementation steps in the task document.
   - Run the verification steps in the task document.
4. On task start, update status: `pending` → `in_progress`.
5. On task completion, update status: `in_progress` → `done`.
6. After each status update, check for newly unblocked tasks and **start them immediately**. Do not wait for the current wave to finish.
7. Repeat until all tasks are `done`.

### Incremental Plan Updates

| Situation | Action |
|-----------|--------|
| New issue discovered | Add a new task. Number = max existing + 1. Set dependencies and wave. |
| Task scope too large | Set original to `cancelled`. Add split tasks with new numbers. |
| Task unnecessary | Set to `cancelled`. Re-evaluate dependencies of dependent tasks. |
| Dependency change | Update dependency graph and recalculate waves. |

Record all plan modifications in the Decision Log immediately.

### Rules

- **Parallel by default.** Tasks with no dependencies launch simultaneously.
- **Eager start.** Start a task the moment its dependencies are all `done` — do not wait for the entire wave.
- **Immediate status update.** Mark tasks `done` in this master document immediately on completion.
- Do not read task documents other than the one currently executing — minimize context usage.
- If a task's instructions are unclear, re-read only that task document.
- **Plan modifications allowed.** Update this master document when new findings emerge. Record all changes in Decision Log.
- **No improvisation.** Follow Incremental Plan Updates or report to the user.
- **State transition compliance.** `pending` → `in_progress` → `done` is the only execution flow.
- **Cancel/defer propagation.** When a dependency is `cancelled` or `deferred`, re-evaluate affected tasks.
- **Plan precision principle.** No failure recovery procedures. Tasks start only when preconditions are verified and decomposition is precise enough for atomic completion.
