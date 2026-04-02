---
name: suggest-commit
description: Analyzes staged/unstaged changes and recent commit history, then recommends 10 commit messages that match the repository's existing style.
---

# Commit Message Suggester

## Step 1: Gather Context

Run these commands in parallel:

1. `git diff HEAD --stat` — file-level change summary
2. `git diff HEAD` — full diff for semantic understanding
3. `git log --oneline -20` — recent commit messages for style reference
4. `git status` — check for untracked files that may be part of the change

## Step 2: Analyze Commit Style

From the git log, identify the repository's conventions:

- **Prefix style**: conventional commits (`feat:`, `fix:`, `refactor:`, `chore:`, `docs:`, `test:`, `ci:`, `perf:`, `build:`) or freeform
- **Casing**: lowercase, sentence case, or title case after prefix
- **Length**: typical character count
- **Scope usage**: whether `feat(scope):` parenthetical scopes are used
- **Tone**: terse vs descriptive

If fewer than 3 commits exist, default to conventional commits with lowercase.

## Step 3: Analyze Changes

Classify the diff:

- **What changed**: files added/removed/modified/renamed, lines added/removed
- **Why it changed**: new feature, bug fix, refactor, config change, docs, tests, cleanup
- **Scope**: which module/component/area is affected

Focus on the **intent** behind the changes, not a mechanical description of what lines moved.

## Step 4: Suggest 10 Messages

Present exactly 10 commit messages in a numbered table:

```
| # | Commit Message |
|---|----------------|
| 1 | ... |
```

Rules:
- All 10 must follow the style detected in Step 2.
- Vary the phrasing — different verbs, different emphasis, different granularity.
- Order from most descriptive to most concise.
- Each message should be a single line (no multi-line bodies).
- If the change spans multiple concerns, some messages may emphasize one aspect over another — this is intentional variety.
- Do NOT include a message body or footer — subject line only.

## Constraints

- **Read-only.** Never stage, commit, or push. Only suggest.
- Do not ask follow-up questions. Deliver all 10 suggestions in one response.
- If there are no changes to commit (`git diff HEAD` is empty and no untracked files), say so and stop.
