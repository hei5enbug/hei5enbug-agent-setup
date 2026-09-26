# Remaining work before replacing the two registered skills

This document tracks the remaining work already agreed with the user. It does not authorize starting
human UI trials, installing the candidate into live sessions, or releasing the plugin. The current request
is to commit and push this record. The user previously selected candidate-only preparation.

## Starting point and completion target

- Original comparison baseline: `08b0ec27cfc2878bae007c319e10ab5f6903f8df`.
- Delivered candidate: `b823f16570c6e79d6de99f649d040453a04a21eb`, under
  `candidate/clarify-requirements/` in this directory.
- Existing defaults: `skills/deep-interview/` and `skills/decision-navigator/`; version `0.6.0`
  at candidate delivery. Recheck the actual checkout and published release before promotion.
- Completed evidence: [verification record](verification.md), [trial receipts](trial-results.json),
  and [contract coverage](coverage.md). Keep these historical results attached to their source revisions.
- Target: one registered `skills/clarify-requirements/` skill, preserved required behavior and existing map
  data, verified native model behavior, and no demonstrated regression under the agreed acceptance gates.

The unified name, common investigation/question/uncertainty loop, conditional strict specification gates,
optional authorized map persistence, and retirement of the two old entrypoints are settled. No further
product choice is needed to start the remaining work. Human test participation is still a prerequisite
for the native question cases. A discovered conflict with the quality/performance constraints must be
reported with evidence; it does not authorize silently relaxing those constraints.

## Open work and dependencies

| ID | Status | Work | Depends on | Completion evidence |
|---|---|---|---|---|
| R1 | Open | Reproduce and address the observed cost increase on the missing-scoring-reference route. | Frozen old/new sources and equivalent quality criteria. | Correct missing-resource behavior plus comparable repeated time/usage receipts; revise and retest only affected behavior. |
| R2 | Waiting for operator/host availability | Run the required native model and human UI comparisons across the contract coverage. | Native host/model/effort availability; human operator; frozen fixtures and answers. | Case-level outputs, actions, model/effort receipts, and grading for both hosts. |
| R3 | Open | Decide adoption from complete quality, time, usage, routing, and recovery evidence. | R1 and R2. | Every required gate passes for the exact candidate revision; otherwise the default stays unchanged. |
| R4 | Not started | Promote the accepted candidate and update discovery, references, translations, and versions together. | R3. | One registered entrypoint; preserved map compatibility; coherent minor-version change; no broken references. |
| R5 | Not started | Run final integration checks, then commit and push the accepted replacement when that work is authorized. | R4. | Required checks and package verification pass; commit subject, remote commit, and worktree state are confirmed. |

R1 can progress without a human operator. R2's independent preparation can proceed in parallel only with
isolated files and contexts; measured latency trials must not compete for local resources. Freeze a new
candidate revision after any correction, and invalidate only the evidence affected by that correction.

## R1: resolve the measured cost concern

The final read-only missing-reference pair reported 20.235 seconds and 26,714/708 input/output tokens for
the original, versus 29.686 seconds and 57,558/1,223 for the candidate. This is one observation, not a
population-level regression estimate. The candidate correctly stopped before questions/scoring and did
not substitute its Korean mirror. Preserve those outcomes while investigating the additional work.

1. Export the baseline commit and freeze the candidate with its complete reference closure and hashes.
   Use disposable workspaces and the same task, available files, permissions, model, and effort.
2. Inspect actual instruction reads, tool calls, retries, and answers. Remove redundant work only when
   its required checks and missing-resource behavior remain intact. Do not skip verification merely
   because the baseline was faster or shorten instructions by dropping a required exception.
3. Run the `missing-scoring` case using [run_readonly_trials.py](run_readonly_trials.py) on the supported
   Codex lane. Freeze three matched pairs before starting. The runner does not cover Claude or human UI.
4. Compare each case within its host and comparable context/cache condition. Preserve raw usage categories
   and wall time; do not double-count cache/reasoning subsets or treat absent data as zero.
5. If the corrected revision still fails or remains inconclusive, record that outcome and keep it a
   candidate. Do not continue sampling until a favorable average appears.

The earlier mixed-snapshot diagnostic remains excluded. The final one-pair observations are useful for
diagnosis but do not replace the agreed repeated acceptance comparisons.

## R2–R3: native behavior and adoption evidence

Use the repository's [evaluation adapter](../../skills/skill-builder/references/execution-methods.md):
Sonnet 5/high in Claude Code and gpt-5.6-luna/xhigh in Codex. Verify the actual model and effort; the
existing receipts contain requested selectors but no echoed Codex model ID. Do not promote requested
configuration alone to verified runtime identity, substitute another model, or launch Sonnet from Codex.

Run native main-session question cases with a human operator. Codex strict interviews use Plan mode and
its supported question UI. Keep operator guides outside model prompts, supply answers only when asked,
record question/answer alignment and human wait time, and do not impersonate the human with an agent.
Use isolated disposable maps for claim races and write/recovery cases, and authorized local prototypes
for feedback cases. No live external tracker, production page, or user decision map is an evaluation target.

Cover all applicable branches in [coverage.md](coverage.md), including the 29 existing candidate cases,
representative greenfield research, and native discovery positive/negative cases that still need execution.
Map old cases using [source-cases.json](candidate/clarify-requirements/evals/source-cases.json). For new
integration cases, record which original workflow supplies the comparable baseline and why.
Check the critical behaviors separately: explicit invocation, one question, evidence before decisions,
quantitative-gate selection, no unapproved writes, strict closure, scope changes, delegated assumptions,
round limits, resumed state, human prototype feedback, and claim/map transaction correctness.

Apply the established [metrics and adoption gates](../token-context-efficiency-2026-09-23/validation.md#metrics-and-adoption-gates).
Freeze three matched pairs per affected case and native lane, alternating old/new order. Preserve every
critical quality condition; better averages cannot compensate for one omitted requirement. Compare
completion-time and complete-usage median/observed maximum per case under comparable conditions.
Include all participants, tool work, retries, and recovery. Measure setup/grading separately and retain
raw human wait time. Do not infer token savings from bytes or combine the two model lanes into one score.

For each case, record source hashes, configuration evidence, task/fixtures, tool actions, output, grading,
timing, usage completeness, and pass/fail/unverified status. Check exact predicates with tools and judge
meaning and usability from source/artifact evidence. Unavailable lanes or missing metrics remain unverified.
Use the current skill evaluation workflow for independent grading when its required configuration is available.
The existing read-only pilots do not establish installed-plugin routing, actual UI, concurrency, or recovery.

## R4–R5: replacement, checks, and delivery

After adoption passes for the exact frozen candidate:

1. Place the accepted self-contained skill at `skills/clarify-requirements/` and retire both old registered
   skill directories in the same change. Keep one canonical common loop and its conditional references.
   Retain the new `agents/openai.yaml` explicit-invocation policy and host question adapters.
2. Preserve `.decision-navigator/` user data, ticket types/statuses, file names, and lock ownership/ordering.
   Do not migrate or delete user maps or claims. Move the relevant tests/evals with the new skill.
3. Update README skill listings and migration guidance, including other language editions with links to
   retired paths. Update hardcoded fixture paths in `tests/test_korean_mirrors.py` and search the repository
   for remaining runtime references to the old names. Preserve baseline inventories; convert historical
   source links to their original immutable commit when their former paths are removed.
4. Keep each English document and complete Korean mirror synchronized. Add a dated promotion receipt to
   the candidate records without rewriting earlier observations as if they described the new default.
5. Verify the latest published release and other unreleased changes. The merge warrants at least a minor
   change; select one planned next version from the highest unreleased impact under AGENTS.md. Do not
   assume a version from today's candidate. Align `.codex-plugin/plugin.json`,
   `.claude-plugin/plugin.json`, `pyproject.toml`, and `uv.lock`. Update tests tied to the actual project
   version where needed; do not blindly replace fixed sample versions in unrelated fixtures.
6. Run the current README development checks: all skill metadata validators, the Python suite, and Node
   renderer tests. Run plugin validation, mirror/link checks, and the packaging check. Verify packaged
   runtime references and scripts are complete and no evaluation caches leak into the archive.
7. Check the final diff scope and whitespace, apply suggest-commit to choose an evidence-supported subject,
   then commit and push the authorized replacement. Verify remote/local commit equality and report the
   actual worktree state. Publishing a release or refreshing live sessions remains a separate action.

If integration fails before promotion, keep the existing defaults and retain the candidate/evidence.
If a replacement must be rolled back later, revert the specific replacement change with a normal reviewed
commit, preserving unrelated work, evaluation evidence, and all user map data. Do not use a hard reset or
delete user state as a rollback mechanism.

## Completion record

For each row R1–R5, add the completed revision and evidence links before changing its status to complete.
Record unavailable prerequisites and exact failures against the affected row. Keep the final promotion
commit, chosen version, required-check results, and remote receipt together. A candidate package or this
document's commit does not complete R3–R5.
