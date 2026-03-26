# Deep Plan

Performs exhaustive code review and produces a structured implementation/improvement plan as a set of atomic task documents governed by a single master execution document.

## Scope

**Inputs:**
- User-provided analysis target (feature area, module, directory, or full codebase)
- User-provided plan name (always ask — never auto-generate)

**Outputs:**
- `.sisyphus/plans/{plan-slug}/MASTER.md` — master execution document (lean, reference-only)
- `.sisyphus/plans/{plan-slug}/tasks/NNN-{slug}.md` — individual task documents (self-contained)

**Core constraints:**
- This skill produces plan documents only — never modify source code
- Every file within the analysis scope must be read — no file may be skipped
- Important architectural or design decisions require explicit user confirmation before proceeding
- Task documents must be independently executable without reading other task documents
- The master document contains only references, status, and execution instructions — no implementation details

## Step 1: Scope & Plan Name

1. Parse the user's request to identify the analysis target: specific files, directories, modules, or the full codebase.
2. If the scope is ambiguous, ask the user to clarify exact boundaries before continuing.
3. Ask the user to name the plan. Derive a kebab-case slug from their answer (e.g., "Auth System Overhaul" -> `auth-system-overhaul`).
4. Confirm the scope and plan name with the user before proceeding.

## Step 2: Deep Code Review

Perform exhaustive analysis of all code within the defined scope.

### 2a. File Inventory

1. List every file within scope using `glob`.
2. Classify files by role: source, test, config, documentation, generated.
3. Report the file count to the user so they know the review size.

### 2b. Architecture Mapping

1. Identify module boundaries, entry points, and public interfaces.
2. Trace dependency relationships (imports, calls, data flow).
3. Map the layering: data layer, business logic, presentation, infrastructure.

### 2c. Pattern Inventory

1. Catalog recurring conventions: naming, file structure, error handling, state management.
2. Note design patterns in use (factory, observer, middleware, etc.).
3. Identify shared abstractions and utilities.

### 2d. Issue & Opportunity Identification

For each file, evaluate:
- **Correctness** — bugs, logic errors, edge cases, missing validation
- **Performance** — unnecessary computation, N+1 patterns, missing memoization, bundle size
- **Security** — injection risks, authentication gaps, secrets exposure, unsafe defaults
- **Maintainability** — code smells, duplication, unclear naming, overly complex functions
- **Test coverage** — missing tests, untested edge cases, brittle test patterns
- **DX friction** — confusing APIs, missing types, poor error messages

**Thoroughness rule:** Use all tools in parallel for maximum coverage:
- `explore` agents for cross-module pattern discovery
- `grep` / `ast-grep` for structural pattern matching
- `lsp_diagnostics` for type errors and warnings
- `lsp_symbols` for module structure overview
- Direct file reads for line-by-line review

Do not skip files based on assumptions. Every file in scope gets reviewed.

## Step 3: Decision Points

Before generating the plan, surface all decisions that require user input.

1. Collect every decision point found during review:
   - Architectural choices (e.g., "replace X pattern with Y?")
   - Breaking changes (e.g., "rename this public API?")
   - Scope boundaries (e.g., "include the test rewrite or defer?")
   - Trade-offs (e.g., "optimize for speed vs. readability?")

2. Present each decision to the user using the question tool:
   - **Context**: Why this decision matters and what it affects
   - **Options**: 2-3 concrete alternatives with pros and cons
   - **Recommendation**: Your suggested choice with reasoning

3. **Do not proceed until all decisions are resolved.** Wait for user input on every decision.

4. Record all decisions and resolutions — these go into the master document's Decision Log.

## Step 4: Task Decomposition

Break the entire plan into atomic, independently executable tasks.

### Decomposition rules:
- **One concern per task.** Never mix refactoring with feature work, or bug fixes with improvements.
- **Independently executable.** Each task is completable in a single focused agent session.
- **5-file soft limit.** If a task touches more than 5 files, consider splitting.
- **10-step soft limit.** If a task has more than 10 implementation steps, consider splitting.
- **Every task includes verification.** No task is complete without a way to confirm success.

### Process:
1. Group related findings from Step 2 into logical units of work.
2. Define dependency order: which tasks must complete before others can start.
3. Verify there are no circular dependencies.
4. Assign priority to each task: `critical`, `high`, `medium`, `low`.
5. Number tasks sequentially: `001`, `002`, `003`, etc.

## Step 5: Write Task Documents

For each task, create `.sisyphus/plans/{plan-slug}/tasks/NNN-{slug}.md` using this template:

```markdown
# Task NNN: {Title}

## Priority
{critical | high | medium | low}

## Problem
What is wrong or needs to change. Reference specific files and line numbers.
Include code snippets that illustrate the current state.

## Solution
Concrete implementation approach. Specify exactly what to do — not vague directions.
Reference existing codebase patterns to follow where applicable.

## Affected Files
- `path/to/file.ext` — what changes are needed and why

## Implementation Steps
1. Precise, numbered steps with enough detail for direct execution.
2. Include exact function names, variable names, and patterns to follow.
3. Show code snippets for non-trivial changes.
4. Reference existing code by file path and line range when illustrating patterns to match.

## Verification
- Specific checks to confirm the task is complete.
- Tests to run, diagnostics to check, behavior to verify.

## Dependencies
- List task numbers this depends on (e.g., "Requires: Task 001, Task 003").
- Write `none` if the task is independent.
```

### Writing rules:
- Be specific enough that an agent can execute without re-analyzing the codebase.
- Include code snippets for anything non-trivial.
- Never leave ambiguous instructions — "improve error handling" is not acceptable; "wrap the `fetchUser` call on line 42 of `user-service.ts` in a try-catch that returns a `ServiceError` with code `USER_FETCH_FAILED`" is.
- Each task document must be understandable on its own, without reading other task documents.

## Step 6: Write Master Document

Create `.sisyphus/plans/{plan-slug}/MASTER.md`:

```markdown
# {Plan Name}

## Overview
One paragraph: what this plan covers, what it achieves, and the key decisions made.

## Decision Log

| # | Decision | Resolution |
|---|----------|------------|
| 1 | {question} | {chosen option and reasoning} |

## Tasks

| # | Task | Priority | Deps | Status |
|---|------|----------|------|--------|
| 001 | [{Title}](./tasks/001-{slug}.md) | critical | — | pending |
| 002 | [{Title}](./tasks/002-{slug}.md) | high | 001 | pending |
| 003 | [{Title}](./tasks/003-{slug}.md) | medium | — | pending |

## Execution Instructions

1. Read this master document for overall context.
2. Pick the next task where **all dependencies are `done`** and status is `pending`.
3. Read **only** that task's linked document — do not load other task documents.
4. Execute the implementation steps in the task document.
5. Run the verification steps described in the task document.
6. Return here. Update the task's status: `pending` -> `done`.
7. Repeat from step 2 until all tasks are complete.

**Rules:**
- One task at a time. Do not batch.
- Do not read task documents other than the current one — minimize context usage.
- If a task's instructions are unclear, re-read only that task document.
- If blocked or encountering unexpected issues, report to the user rather than improvising.
```

### Master document rules:
- **No implementation details.** The master document is a table of contents and execution guide.
- **Minimal context.** An agent reading this document should be able to pick the next task without loading the full analysis.
- **Status tracking.** The status column is the single source of truth for progress.

## Step 7: Verification & Handoff

1. Verify every task document is referenced in the master's task table.
2. Verify the dependency graph has no cycles (task A -> B -> A).
3. Verify all file paths referenced in task documents actually exist in the codebase.
4. Count: total tasks, per-priority breakdown, estimated dependency chains.
5. Present the plan summary to the user:
   - Total tasks and priority distribution
   - Longest dependency chain (critical path)
   - Any risks or caveats discovered during analysis
6. Ask the user for final approval before considering the plan complete.

## Constraints

- **Read-only.** Never modify source code. This skill produces plan documents only.
- **No file skipped.** Every file within the defined scope must be reviewed during Step 2.
- **User decides.** Architectural and design decisions must be confirmed by the user via the question tool. Never assume.
- **Self-contained tasks.** Each task document must be executable without reading other task documents.
- **Minimal master.** The master document is a reference index — no inline implementation details.
- **Always ask plan name.** Never auto-generate the plan name. The user names every plan.
- **No premature action.** Do not begin writing task documents until all decision points in Step 3 are resolved.
