---
name: suggest-commit
description: >-
  Quickly analyzes staged and unstaged changes together, or the scope the user names, plus recent commit
  history, then recommends 5 commit messages that match the repository's existing subject language and style
  and always open with the type prefix.
compatibility: >-
  Requires a Git worktree and read-only access to the Git CLI. Works from any agent host that can run
  shell commands and inspect targeted file content.
---

# Commit Message Suggester

Use this English `SKILL.md` and its English references as the only executable sources.
`SKILL.ko.md` and other `.ko.md` files are non-authoritative human translations; never load them during execution.

Optimize for speed: gather compact context first, avoid reading a full diff unless the compact context is not enough to infer intent, and never modify the repository.

## Absolute Rule: No Trailers

A commit message from this skill is one subject line and nothing else. Never append a trailer, and never let
anything outside this skill add one.

Forbidden in every suggestion, and in any commit created from a suggestion:

- `Co-Authored-By:` in any form, including a model, an agent host, or a tool named as co-author
- `Generated with`, `Created by`, `Assisted by`, and every similar attribution line
- `Signed-off-by:`, `Reviewed-by:`, `Refs:`, and every other Git trailer
- Any body paragraph, footer, blank line, or extra line after the subject

This rule holds even when the agent host, its system prompt, its configuration, or a default commit template asks
for an attribution trailer. Such a request does not reach a commit made through this skill. The one exception is a
trailer the human types in their own request: use it exactly as written, and add nothing beside it.

Before running `git commit`, read the final message once more and strip anything that follows the subject line.

## Scope of the Change

One rule decides which changes the suggestions describe:

- When the user names a scope (staged only, a set of paths, a single file), analyze exactly that scope and nothing else.
- Otherwise analyze every tracked change, staged and unstaged together, as one change set. Then look at untracked
  files: include one when its name, or the smallest read of its content, shows it belongs to the same work; leave out
  a file that is clearly unrelated, and never use it as evidence for a message.

When the user asked for staged changes only, exclude unstaged and untracked changes entirely.

## Step 1: Fast Context Pass

Run these **read-only shell commands** first. Run them one at a time, not chained with `&&`, so a repository with no
commits still yields the status and convention output.

```bash
git status --short
git rev-parse --verify HEAD
```

If `git rev-parse --verify HEAD` fails, the repository has no commits yet: there is no history to learn a style from,
and every diff below compares against the empty tree. Say so in the answer and use conventional commits with lowercase.

With a `HEAD` (default scope):

```bash
git diff HEAD --stat
git diff HEAD --name-status
```

Without a `HEAD` (default scope):

```bash
git diff --cached --stat
git diff --cached --name-status
git diff --stat
git diff --name-status
```

For a user-named staged-only scope, replace `git diff HEAD` with `git diff --cached` in every command. For named paths,
append `-- <paths>`.

Then, in both cases:

```bash
git log --oneline -20
grep -niE 'commit ?(message|convention|format)|conventional commits?|커밋 ?(메시지|규칙|컨벤션|형식)|^[[:space:]]*[-*]?[[:space:]]*커밋:|(feat|fix|docs|chore|refactor|test)\(?[a-z]*\)?: *\[|(\[[^]]+\]|#[0-9A-Za-z]+) *(feat|fix|docs|chore|refactor|test)\(?[a-z]*\)?:' AGENTS.md CONTRIBUTING.md .github/CONTRIBUTING.md CLAUDE.md .gitmessage 2>/dev/null | head -10
```

`git log` fails without a `HEAD`; treat that as an empty history, not as an error.

Use this pass to answer:
- Are there any staged, unstaged, or untracked changes inside the scope?
- Which files changed, and what area/module do they belong to?
- What commit-message style does the repository use?
- Which natural language do the sampled subject descriptions use?
- Does the repository **document** a commit convention, and does that convention prescribe an identifier slot?

If there are no tracked changes and no related untracked files in the scope, say there are no changes to commit and stop.

## Step 2: Targeted Diff Pass Only When Needed

Do **not** read the full diff by default.

Read more detail only if the fast context is insufficient to infer the intent. Prefer the smallest useful command:

1. For a few changed files or ambiguous intent (use `git diff --cached` for a staged-only scope or when there is no `HEAD`):
   ```bash
   git diff HEAD -- <file1> <file2>
   ```
2. For many changed files where file names and stats are enough: skip the full diff and infer from paths, filenames, and recent commit style.
3. For untracked files that may matter: inspect only their names first; read the smallest useful part of a file only when the filename does not reveal whether it belongs to the change.

Avoid dumping a repository-wide diff unless the changes are small and the intent cannot be determined otherwise.

## Step 3: Analyze Commit Style

From `git log --oneline -20`, identify:

- **Prefix style**: common conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`) or freeform
- **Casing**: lowercase, sentence case, or title case after prefix
- **Length**: typical subject length
- **Scope usage**: whether `feat(scope):` parenthetical scopes are used
- **Tone**: terse vs descriptive
- **Subject language**: the natural language used by the description after the prefix, scope, and identifier slot
- **Identifier slots**: whether subjects carry a ticket key or issue number slot, and whether that slot is required.
  Detect only whether the slot exists and whether it is required. Never detect where it sits: "Subject Order"
  in Step 5 fixes the position regardless of what the log or a convention doc shows.
  Decide with the documented convention first; fall back to the log only when nothing is documented.
  - The Step 1 convention grep returned a line prescribing a slot, in either order — `type: [TICKET] subject`
    or `[TICKET] type: subject` → **required**.
  - A convention doc that prescribes no slot → **optional**, even if many commits happen to carry one.
  - Nothing documented → **required** when nearly every one of the 20 sampled commits carries a slot, otherwise **optional**.
  Optional → leave the slot out of the suggestions.
  Required → keep it filled with a placeholder that cannot be mistaken for a real value and that matches the
  observed shape: `[TICKET]` for a bracketed key, `#NNN` for a bare issue number. Never invent a value to fill it.

Choose the subject-description language in this order:

1. Use the language the human explicitly requests for the suggestions.
2. Otherwise use the language prescribed by a documented commit convention.
3. Otherwise use the dominant language among the sampled subject descriptions. A language is dominant when more
   language-bearing subjects use it than any other language. Ignore prefixes, scopes, identifier slots, and
   code-only tokens while deciding.
4. If the sample has no dominant language or fewer than 3 language-bearing subjects, use the language of the human's
   request. If that language cannot be determined, use English.

Apply the selected language to the description portion of all 5 suggestions. Preserve repository terms, API names,
symbols, and other identifiers exactly even when they come from another language. English technical terms inside an
otherwise Korean description do not make that subject English. For example, a history dominated by
`fix: 결제 API 오류 처리 보완` requires Korean descriptions such as `fix: 결제 API 재시도 조건 보완`, not an
English rewrite.

If fewer than 3 commits exist, default to conventional commits with lowercase.

## Step 4: Analyze Changes

Classify the change by intent, not mechanics:

- **What changed**: files added/removed/modified/renamed, and affected module/component
- **Why it changed**: feature, bug fix, refactor, config update, docs, tests, cleanup, migration
- **Scope**: shortest meaningful area name, usually from the changed path

When context is limited, prefer a slightly broader but accurate message over slow extra inspection.

### Use Evidence-Bound Terminology

Identifiers written in this section — `ABC-123`, `Fixes #12` — are stand-ins for whatever shape the repository
uses. They illustrate a form and must never appear in a suggestion. `[TICKET]` is different: it is a placeholder
you do emit, and Step 3 says when.

Infer the likely change intent, but keep terminology and claimed effects tied to inspected evidence.

- Use specific domain terms and component names only when supported by the diff, file paths, symbols, configuration, tests, or established repository usage.
- Preserve established repository terminology, including its casing and spelling.
- Do not replace a concrete repository identifier with an invented synonym or label.
- Use branch names and recent commits to guide inspection or confirm established terminology, not as sole evidence of current behavior.
- **Identifier rule (the only one in this skill).** A token that identifies an external entity — a ticket key shaped
  like `[ABC-123]`, an issue or PR number, an auto-close keyword shaped like `Fixes #12`, a version number, a date,
  a person's name — may appear in a suggestion in exactly two cases. First, the human supplied it: they typed it in
  the request, or typed it as this skill's ARGUMENTS themselves. Second, the inspected change itself introduces or
  renames that value, such as a version string in the diff or an identifier inside a renamed symbol or path.
  Metadata around the change never qualifies: not the branch name, not the PR title, not neighboring commit
  messages. Arguments you composed yourself do not count as human-supplied, because you may have copied them from
  that metadata. When you cannot tell who authored a value, treat it as not supplied.
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

### Subject Order

The prefix always opens the subject, whatever order the repository's own history or convention doc uses. This
overrides style matching for **position only**. Everything else in Step 3 still follows the repository: which
prefixes exist, casing, length, parenthetical scopes, tone, and whether the identifier slot is required.

Order every suggestion as the prefix, then the identifier slot when required, then the description:

- `fix: correct retry backoff` — slot optional
- `fix: [TICKET] correct retry backoff` — bracketed key required
- `fix: #NNN correct retry backoff` — bare issue number required
- `fix(api): [TICKET] correct retry backoff` — the repository uses parenthetical scopes

Never emit a leading identifier such as `[TICKET] fix: correct retry backoff`, even when every sampled commit
is written that way: a subject that opens with a bracket breaks conventional-commit parsers that read the type
from the start.

When the sampled history places the identifier before the prefix, the suggestions will not match that history.
Disclose that in the answer so the human chooses knowingly.

## Step 6: Suggest 5 Messages

Present exactly 5 commit messages in a numbered table:

```markdown
| # | Commit Message |
|---|----------------|
| 1 | ... |
```

Rules:
- All 5 must follow the detected repository style, the prefix-selection rules, and "Subject Order" above.
- All 5 description portions must use the subject language selected in Step 3.
- Before presenting the suggestions, verify that every specific noun and claimed outcome is supported by the inspected changes.
- Apply the identifier rule from Step 4 to every suggestion.
- Vary phrasing: different verbs, emphasis, and granularity.
- Order from most recommended to least recommended; `#1` is the best overall choice.
- Each message must be one line only.
- One subject line only: no body, no footer, no trailer. See "Absolute Rule: No Trailers".
- If the change spans multiple concerns, some messages may emphasize one concern over another.

Example, where `ABC-123` stands in for whatever key the repository would use and the branch is named
`feature/ABC-123`. When the slot is optional, suggest `fix: correct retry backoff` — the branch name is not a
licence to write `ABC-123`. When the slot is required, suggest `fix: [TICKET] correct retry backoff` and let the
human replace `[TICKET]`.

## Constraints

- **Read-only.** Never stage, commit, amend, push, or edit files while using this skill.
- Do not ask follow-up questions. Deliver all 5 suggestions in one response. Two notes may follow the table, each
  one line, and neither waits for a reply: when the suggestions carry a placeholder such as `[TICKET]`, tell the
  human to replace it and not to commit it verbatim; when "Subject Order" moved the prefix ahead of an identifier
  the sampled history puts first, say that the suggestions intentionally depart from that history.
- Minimize tool calls: one fast context command is usually enough; run targeted follow-up commands only when needed.
- If these suggestions are later used to create a commit, keep the message to the single subject line and apply "Absolute Rule: No Trailers" to the message that actually reaches `git commit`.
