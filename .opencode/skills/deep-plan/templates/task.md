# Task NNN: {Title}

## Priority
{critical | high | medium | low}

## Size
{small | medium | large}

## Problem
What is wrong or needs to change. Reference specific files, line ranges, and function names.
Do not paste source code — the executor reads the actual files.

## Solution
Concrete implementation approach. Specify exactly what to do — not vague directions.
Reference existing codebase patterns by file path and function name.

## Affected Files
- `path/to/file.ext` — what changes are needed and why

## Implementation Steps
1. Precise, numbered steps with enough detail for direct execution.
2. Reference exact file paths, line ranges, function names, and variable names.
3. Describe the intended change in prose — do not include code snippets.
4. When referencing patterns to follow, cite the file path and function name as examples.

## Verification
- Specific checks to confirm the task is complete.
- Tests to run, diagnostics to check, behavior to verify.

## Related Tests
- List existing tests that MUST still pass after this change.
- Format: `path/to/test-file.ext` — brief description of what it covers.
- Write `none` if no existing tests are affected.

## Preconditions
- Codebase state required before starting (beyond task dependencies).
- E.g., "Type `UserRole` must be exported from `types.ts`".
- Write `none` if only task dependencies apply.

## Postconditions
- Invariants that must hold after completion.
- E.g., "All existing API endpoints remain backward-compatible".
- Write `none` if verification section fully covers this.

## Dependencies
- List task numbers this depends on (e.g., "Requires: Task 001, Task 003").
- Write `none` if the task is independent.
- Wave: {W0 | W1 | W2 | ...} — tasks in the same wave run in parallel.
