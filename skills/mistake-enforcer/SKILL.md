---
name: mistake-enforcer
description: >-
  Turn mistakes that agents keep repeating in a repository into enforced checks. Groups evidence from
  commits, reverts, review comments, and user corrections into mistake classes, picks the highest
  enforcement level that works, and proves each proposed check fails on a real past instance. Use only
  when the user explicitly asks to turn repeated mistakes into checks or invokes the skill by name. Do not
  start it for a single bug fix, a code review, or a session summary.
compatibility: >-
  Needs Git and filesystem access to the target repository. Reading pull request review comments needs the
  hosting service's command-line tool; without it the skill uses the other sources and says so.
---

# Mistake Enforcer

Use this English `SKILL.md` as the only executable source.

An instruction sentence is the weakest fix for a repeated mistake: it costs context in every session and still
fails silently when an agent skips it. Find the mistakes that recur, and stop each one at the highest level that
works.

## Boundaries

- Stay read-only toward the repository, its history, and any session record until the user accepts proposals in
  step 6.
- Draft checks and run proofs only in the host's session temporary folder, or in a new folder under the operating
  system's temporary folder when the host has none.
- Never create a worktree or branch, check out another commit, or change the index. Export a past tree with
  `git archive` into the temporary folder instead.
- Quote only the few words a finding needs, and never copy a credential, token, or personal data.

## Workflow

### 1. Fix the scope

Settle from the request, stating each default you chose: the repository (default the current working
directory), the period (default the last 30 days), and the sources. Gather from every available source:

- Commits and reverts in the period: reverts, fix commits that undo or redo a recent change, and repeated fixes
  to the same rule or file.
- Review comments on pull requests merged in the period, when the hosting service's tool is installed and
  authenticated. Follow the session's service access rules. Without the tool, skip this source and report it.
- User corrections that the user supplies, or that the session records or saved feedback the user names contain.
- The repository's written rules and any rule-to-enforcer index it keeps, to tell which rules a check already
  enforces.

### 2. Group mistakes into classes

A class is one wrong action with one correct alternative, such as "edits a generated file instead of its
source". Merge instances that describe the same wrong action in different words. A class counts once it has at
least two independent instances: two sessions, commits, or review comments. Keep a single instance as a watch
item and do not propose a fix for it.

For each class, record every instance with its evidence (commit hash, comment link, or quoted correction with its
session), the written rule it breaks if one exists, and whether a check already enforces that rule.

### 3. Choose the enforcement level

Choose the highest level that works, in this order:

1. Structure: remove the possibility. Give the decision one owner, keep one supported way, and delete the old path.
2. Type or schema: make the wrong state unrepresentable.
3. Lint or test: add a check whose error message names the correct alternative.
4. Instruction: only for a judgment call that no check can decide.

For every class, state the chosen level and, for each higher level, the concrete reason it does not work. An
instruction proposal names the judgment it leaves to the agent. When a check makes a written rule's mistake
impossible, propose removing that rule.

### 4. Prove each check

Draft every level 1 to 3 proposal as a runnable check in the temporary folder, then run it twice:

- Against the current tree, where it passes, or fails only on live instances that you report. When running it
  would write into the repository, such as caches or build output, run it on a copy of the working tree in the
  temporary folder instead.
- Against a real past instance: export the tree of a commit that still contained the mistake with
  `git archive <commit> | tar -x -C <temporary folder>/<commit>` and run the check there. It must fail, and its
  error must name the correct alternative.

A check that does not fail on the past instance is unproven. Revise it once; if it still passes, report it as
unproven. When no past tree holds the mistake, such as a correction made only in conversation, build the smallest
fixture from the quoted instance and record the proof as fixture-based. Install nothing and run no unrelated
suite; when a check needs a missing dependency, report it.

### 5. Report

Present the result in the user's language:

| Class | Instances and evidence | Rule and current enforcement | Level and why not higher | Proposal | Proof |
|---|---|---|---|---|---|

In "Proof", write the command and result for the current tree and for the past instance, or "fixture" or
"unproven". Then list the watch items, the sources you could not read, and the rules a proposal would let the
repository remove. Ask once which proposals to apply.

### 6. Apply on request

Apply only the proposals the user accepts. Add each check to the repository and run it with the repository's
related tests. Remove a written rule only when the user agreed to its removal. When the repository keeps a
rule-to-enforcer index, add or update its row in the same change. Follow the repository's own rules for mirrors,
tests, and commits.

## Final report

State the scope and sources read, the classes with their levels and proof results, the watch items, what was
applied, and the checks run after applying.
