---
name: suggest-commit
description: Quickly analyzes staged/unstaged changes and recent commit history, then recommends 5 commit messages that match the repository's existing style.
compatibility: >-
  Requires a Git worktree and read-only access to the Git CLI. Works from any agent host that can run
  shell commands and inspect targeted file content.
---

# Commit Message Suggester

Optimize for speed: gather compact context first, avoid reading a full diff unless the compact context is not enough to infer intent, and never modify the repository.

## Step 1: Fast Context Pass

Run this **single read-only shell command** first:

```bash
git status --short && printf '\n---STAT---\n' && git diff HEAD --stat && printf '\n---NAME-STATUS---\n' && git diff HEAD --name-status && printf '\n---RECENT-COMMITS---\n' && git log --oneline -20
```

Use this pass to answer:
- Are there any staged, unstaged, or untracked changes?
- Which files changed, and what area/module do they belong to?
- What commit-message style does the repository use?

If there are no tracked changes and no untracked files, say there are no changes to commit and stop.

## Step 2: Targeted Diff Pass Only When Needed

Do **not** read the full diff by default.

Read more detail only if the fast context is insufficient to infer the intent. Prefer the smallest useful command:

1. For a few changed files or ambiguous intent:
   ```bash
   git diff HEAD -- <file1> <file2>
   ```
2. For many changed files where file names and stats are enough: skip the full diff and infer from paths, filenames, and recent commit style.
3. For untracked files that may matter: inspect only their names first; read file contents only when the filename does not reveal the intent.

Avoid dumping a repository-wide `git diff HEAD` unless the changes are small and the intent cannot be determined otherwise.

## Step 3: Analyze Commit Style

From `git log --oneline -20`, identify:

- **Prefix style**: common conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`) or freeform
- **Casing**: lowercase, sentence case, or title case after prefix
- **Length**: typical subject length
- **Scope usage**: whether `feat(scope):` parenthetical scopes are used
- **Tone**: terse vs descriptive

If fewer than 3 commits exist, default to conventional commits with lowercase.

## Step 4: Analyze Changes

Classify the change by intent, not mechanics:

- **What changed**: files added/removed/modified/renamed, and affected module/component
- **Why it changed**: feature, bug fix, refactor, config update, docs, tests, cleanup, migration
- **Scope**: shortest meaningful area name, usually from the changed path

When context is limited, prefer a slightly broader but accurate message over slow extra inspection.

### Use Evidence-Bound Terminology

Infer the likely change intent, but keep terminology and claimed effects tied to inspected evidence.

- Use specific domain terms and component names only when supported by the diff, file paths, symbols, configuration, tests, or established repository usage.
- Preserve established repository terminology, including its casing and spelling.
- Do not replace a concrete repository identifier with an invented synonym or label.
- Use branch names and recent commits to guide inspection or confirm established terminology, not as sole evidence of current behavior.
- Infer the change category and likely intent, but claim a behavioral or user-visible outcome only when the inspected changes support it.
- When several descriptions are possible, prefer the most concrete wording supported by the evidence.
- When a term remains unclear, inspect the smallest relevant diff, symbol, test, or configuration. If the evidence is still insufficient, use a broader accurate expression.

## Step 5: Choose the Prefix Precisely

If the repository uses conventional commit prefixes, choose the prefix from the change intent, not from habit or recent frequency:

Use only these common prefixes:

- `feat:` — adds a new user-facing capability, command, skill, workflow, option, integration, or documented feature.
- `fix:` — corrects broken, invalid, outdated, unsafe, or inaccurate behavior/configuration/instructions.
- `refactor:` — restructures implementation or wording without changing user-facing behavior.
- `docs:` — changes only documentation/prose that is not an executable skill or agent behavior contract.
- `test:` — adds or changes tests only.
- `chore:` — maintenance-only changes such as metadata, generated files, dependency housekeeping, CI/build/dependency updates, or repo hygiene.

Do not suggest rare prefixes such as `ci:`, `build:`, `perf:`, `style:`, or `revert:` unless the user explicitly asks for them. Map rare cases to the closest common prefix:
- CI/CD, build, packaging, dependency, and release workflow changes → `chore:`.
- Performance-motivated internal rewrites without new behavior → `refactor:`.
- Performance fixes that correct a user-visible slowdown/regression → `fix:`.

Prefix decision rules:
- Use the **dominant user-visible intent** for mixed changes.
- Skill, prompt, or agent-instruction edits that change how an agent behaves are usually `feat:` or `fix:`, not `docs:`.
- Use `fix:` when the change aligns behavior with an intended rule, removes invalid guidance, or corrects a wrong model/config/command path.
- Use `feat:` when the change introduces a new workflow or capability that did not exist before.
- Do not make all five suggestions share `fix:` or `feat:` unless the diff genuinely has only that intent.
- If multiple common prefixes are plausible, vary some suggestions with those common alternatives, but keep #1 as the most accurate prefix.

## Step 6: Suggest 5 Messages

Present exactly 5 commit messages in a numbered table:

```markdown
| # | Commit Message |
|---|----------------|
| 1 | ... |
```

Rules:
- All 5 must follow the detected repository style and the prefix-selection rules above.
- Before presenting the suggestions, verify that every specific noun and claimed outcome is supported by the inspected repository evidence.
- Vary phrasing: different verbs, emphasis, and granularity.
- Order from most recommended to least recommended; `#1` is the best overall choice.
- Each message must be one line only.
- Do not include a body or footer. Never add a `Co-Authored-By` trailer or any other trailer.
- If the change spans multiple concerns, some messages may emphasize one concern over another.

## Constraints

- **Read-only.** Never stage, commit, amend, push, or edit files while using this skill.
- Do not ask follow-up questions. Deliver all 5 suggestions in one response.
- Minimize tool calls: one fast context command is usually enough; run targeted follow-up commands only when needed.
- If these suggestions are later used to create a commit, keep the message to the single subject line: no body, and never a `Co-Authored-By` or other trailer.
