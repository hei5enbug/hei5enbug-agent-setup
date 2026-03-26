---
name: deep-plan
description: Perform exhaustive code review and produce a structured implementation plan as atomic task documents with dependency-aware parallel execution. Use when asked to "plan improvements", "analyze the codebase", "create a refactoring plan", or when a systematic code review with actionable task output is needed.
---

# Deep Plan

## Scope

**Inputs:**
- User-provided analysis target (feature area, module, directory, or full codebase)
- Auto-generated plan name (derived from analysis target; never ask the user)

**Outputs:**
- `.sisyphus/plans/{plan-slug}/MASTER.md` — master execution document (lean, reference-only)
- `.sisyphus/plans/{plan-slug}/tasks/NNN-{slug}.md` — individual task documents (self-contained)

## Output Language

Write all plan documents (MASTER.md and task documents) in **Korean** with these exceptions that remain in English:
- Status tokens: `pending`, `done`
- Priority tokens: `critical`, `high`, `medium`, `low`
- Wave labels: `W0`, `W1`, `W2`, etc.
- Code snippets, file paths, function/variable names

The execution agent (Sisyphus) natively reads Korean documents and formulates English execution prompts — no explicit translation step is needed.

### Section Header Mapping

Use these Korean equivalents for all section headers in output documents:

| Template (English) | Output (Korean) |
|--------------------|-----------------|
| Task NNN: {Title} | 태스크 NNN: {제목} |
| Priority | 우선순위 |
| Problem | 문제 |
| Solution | 해결 방안 |
| Affected Files | 영향 파일 |
| Implementation Steps | 구현 단계 |
| Verification | 검증 |
| Dependencies | 의존성 |
| {Plan Name} | {플랜 이름} |
| Overview | 개요 |
| Decision Log | 결정 로그 |
| Tasks | 태스크 |
| Execution Instructions | 실행 지침 |
| Parallel Execution Model | 병렬 실행 모델 |
| Execution Procedure | 실행 절차 |
| Rules | 규칙 |

## Step 1: Scope & Plan Name

1. Parse the user's request to identify the analysis target: specific files, directories, modules, or the full codebase.
2. If the scope is genuinely ambiguous (multiple valid interpretations with significantly different effort), ask the user to clarify exact boundaries. Otherwise, proceed with the reasonable interpretation.
3. Auto-generate the plan name in Korean from the analysis target. Derive an English kebab-case slug for the directory name (e.g., analysis of `src/auth/` → "인증 모듈 개선" → `auth-module-improvement`). Do not ask the user for the name.

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

Use all tools in parallel for maximum coverage:
- `explore` agents for cross-module pattern discovery
- `grep` / `ast-grep` for structural pattern matching
- `lsp_diagnostics` for type errors and warnings
- `lsp_symbols` for module structure overview
- Direct file reads for line-by-line review

## Step 3: Decision Points

1. Collect every decision point found during review:
   - Architectural choices (e.g., "replace X pattern with Y?")
   - Breaking changes (e.g., "rename this public API?")
   - Scope boundaries (e.g., "include the test rewrite or defer?")
   - Trade-offs (e.g., "optimize for speed vs. readability?")

2. **Auto-resolve** decisions that meet ANY of these criteria:
   - A single option is clearly superior based on codebase conventions
   - The decision is easily reversible
   - Industry best practices provide a clear answer
   - The impact is localized (affects few files, no public API changes)

3. **Escalate to the user** (via the question tool) ONLY when ALL of these are true:
   - The decision is irreversible or very costly to undo (e.g., public API rename, data migration)
   - Multiple options are genuinely viable with no clear winner
   - The impact is broad (cross-module, user-facing, or affects external consumers)

   When escalating, provide:
   - **Context**: Why this decision matters and what it affects
   - **Options**: 2-3 concrete alternatives with pros and cons
   - **Recommendation**: Your suggested choice with reasoning

4. Record all decisions (both auto-resolved and user-resolved) in the master document's Decision Log. Mark each as `auto` or `user-resolved`.

## Step 4: Task Decomposition

Break the entire plan into atomic, independently executable tasks.

### Decomposition Rules

- **One concern per task.** Never mix refactoring with feature work, or bug fixes with improvements.
- **Self-contained.** Each task is completable in a single focused agent session without reading other task documents.
- **5-file soft limit.** If a task touches more than 5 files, consider splitting.
- **10-step soft limit.** If a task has more than 10 implementation steps, consider splitting.
- **Every task includes verification.** No task is complete without a way to confirm success.
- **Maximize parallelism.** Minimize unnecessary dependencies. If two tasks don't truly need ordering, they should be independent. Prefer splitting a large task into parallel subtasks over keeping it monolithic.
- **No file overlap in parallel tasks.** Tasks that may run simultaneously should not modify the same file. If a file must be changed by multiple tasks, add a dependency to serialize them.

### Process

1. Group related findings from Step 2 into logical units of work.
2. Define dependency order: which tasks must complete before others can start.
3. Verify there are no circular dependencies.
4. Assign priority to each task: `critical`, `high`, `medium`, `low`.
5. Number tasks sequentially: `001`, `002`, `003`, etc.

### Parallel Execution Grouping

After defining dependencies, group tasks into **waves** — sets of tasks that can run simultaneously.

1. **Wave 0**: All tasks with no dependencies. These launch immediately in parallel.
2. **Wave 1**: Tasks whose dependencies are ALL in Wave 0.
3. **Wave N**: Tasks whose dependencies are ALL in Wave 0 through N-1.
4. Within a wave, all tasks run in parallel — no ordering between them.

**Eager scheduling rule:** A task becomes executable the moment ALL its dependencies are `done` — it does not need to wait for its entire wave to complete. Waves are a planning tool for the document; the executor starts tasks as soon as their specific dependencies are satisfied.

Example dependency graph:
```
001 (no deps)  ──┐
002 (no deps)  ──┼── 004 (deps: 001, 002) ──── 006 (deps: 004)
003 (no deps)  ──┘
005 (no deps)  ────────────────────────────── 007 (deps: 005)
```
Waves: `W0=[001,002,003,005]`, `W1=[004,007]`, `W2=[006]`
But 007 does not wait for 004 — it starts as soon as 005 is done.

## Step 5: Write Task Documents

Create `.sisyphus/plans/{plan-slug}/tasks/NNN-{slug}.md` for each task. Apply the Section Header Mapping to all headers and prose.

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
- Wave: {W0 | W1 | W2 | ...} — tasks in the same wave run in parallel.
```

### Writing Rules

- Be specific enough that an agent can execute without re-analyzing the codebase.
- Include code snippets for anything non-trivial.
- Never leave ambiguous instructions — "Improve error handling" is not acceptable; "Wrap the `fetchUser` call on line 42 of `user-service.ts` in a try-catch that returns a `ServiceError` with code `USER_FETCH_FAILED`" is.

## Step 6: Write Master Document

Create `.sisyphus/plans/{plan-slug}/MASTER.md`. Apply the Section Header Mapping to all headers and prose.

```markdown
# {Plan Name}

## Overview
One paragraph: what this plan covers, what it achieves, and the key decisions made.

## Decision Log

| # | Decision | Resolution | Source |
|---|----------|------------|--------|
| 1 | {question} | {chosen option and reasoning} | auto |
| 2 | {question} | {chosen option and reasoning} | user |

## Tasks

| # | Task | Priority | Wave | Deps | Status |
|---|------|----------|------|------|--------|
| 001 | [{Title}](./tasks/001-{slug}.md) | critical | W0 | — | pending |
| 002 | [{Title}](./tasks/002-{slug}.md) | high | W0 | — | pending |
| 003 | [{Title}](./tasks/003-{slug}.md) | medium | W0 | — | pending |
| 004 | [{Title}](./tasks/004-{slug}.md) | high | W1 | 001, 002 | pending |
| 005 | [{Title}](./tasks/005-{slug}.md) | medium | W2 | 004 | pending |

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
4. On task completion, **immediately** update this master document: `pending` → `done`.
5. After each status update, check for newly unblocked tasks and **start them immediately**. Do not wait for the current wave to finish.
6. Repeat until all tasks are `done`.

### Rules

- **Parallel by default.** Tasks with no dependencies launch simultaneously.
- **Eager start.** Start a task the moment its dependencies are all `done` — do not wait for the entire wave.
- **Immediate status update.** Mark tasks `done` in this master document immediately on completion.
- Do not read task documents other than the one currently executing — minimize context usage.
- If a task's instructions are unclear, re-read only that task document.
- If blocked or encountering unexpected issues, report to the user rather than improvising.
- When parallel tasks modify the same file, **beware of conflicts** — task decomposition should minimize file overlap.
```

### Master Document Rules

- **No implementation details.** The master document is a table of contents and execution guide.
- **Minimal context.** An agent reading this document should be able to pick the next task without loading the full analysis.
- **Status tracking.** The status column is the single source of truth for progress.

## Step 7: Verification & Handoff

1. Verify every task document is referenced in the master's task table.
2. Verify the dependency graph has no cycles (task A → B → A).
3. Verify wave assignments are consistent with dependencies (a task's wave must be greater than all its dependencies' waves).
4. Verify no two parallel tasks (same wave) modify the same file — flag conflicts if found.
5. Verify all file paths referenced in task documents actually exist in the codebase.
6. Count: total tasks, per-priority breakdown, wave count, max parallelism (largest wave size).
7. Present the plan summary to the user:
   - Total tasks and priority distribution
   - Wave breakdown (how many waves, tasks per wave)
   - Longest dependency chain (critical path)
   - Maximum parallelism achievable
   - Any risks or caveats discovered during analysis (including file conflict warnings)

## Constraints

- **Read-only.** Plan documents only — never modify source code.
- **Exhaustive review.** Every file in scope gets reviewed. No skipping.
- **Minimal questions.** Auto-resolve by default. Escalate only when critical, irreversible, and genuinely ambiguous.
- **Minimal master.** Reference index only — no inline implementation details.
- **Korean output.** All plan documents in Korean. See Output Language section for mapping and exceptions.
- **No premature action.** Do not write task documents until user-required decisions in Step 3 are resolved.
