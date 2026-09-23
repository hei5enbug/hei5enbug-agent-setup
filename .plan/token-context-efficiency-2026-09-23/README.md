# Reduce execution cost while preserving skill outcomes

This is the original improvement plan. The later implementation and trial decisions are in the
[execution record](execution-results.md).

Keep the current runtime as the default until each proposed optimization preserves every required outcome
on both Sonnet(high) and Luna(xhigh) and demonstrates lower execution cost without slower completion.
Fix the description optimizer's explicit permission to sacrifice accuracy before evaluating shorter prompts.

## Intent and scope

The user requested a repository-wide investigation and an improvement plan under `.plan/`.
This deliverable proposes changes; it does not implement them or claim measured token savings.

| Item | Frozen scope |
|---|---|
| Outcome | Reduce unnecessary instruction loading, repeated reads, model input, tool output, and duplicate work. |
| Coverage | All 10 plugin skills, the standalone `omo-model-config` skill, session instructions, agents, hooks, supporting scripts, evaluation resources, and discovery configuration. |
| Quality | Preserve objectives, triggers, requirements, exceptions, authorization, failure handling, and usable deliverables. |
| Models | Validate in native Claude Code and Codex environments using the repository's required evaluation adapters. |
| Performance | Measure time through a usable artifact, including reads, tools, workers, retries, and recovery. |
| Protected surfaces | Skill names, discovery paths, portable behavior, public output formats, model/effort contracts, locks, freshness checks, mirrors, and release policy. |
| Exclusions | Model downgrades, fewer required reviews, changed approval policy, new skill objectives, external publishing, and plugin installation. |
| Original planning change | Only this plan directory was created at this stage. No runtime instructions, code, manifests, or versions were changed then. |

“No degradation” is an acceptance gate, not a claim that static inspection can prove all future executions.
A candidate with a missing required measurement or an unresolved quality regression stays unadopted.
Passing finite trials supports only the tested models, tasks, and conditions.

## Evidence and navigation

The source snapshot is commit `72f66ac69cf02ac7b7f64bfba0a11adc8736ed04` on 2026-09-23.
The worktree was clean before this investigation.

| Artifact | Reader goal |
|---|---|
| [Findings](findings.md) | Inspect each opportunity, its source, proposed change, and preservation condition. |
| [Validation](validation.md) | Implement the comparison cases, measurements, and adoption gates. |
| [Inventory](inventory.json) | Check all 204 tracked paths, classifications, sizes, and source hashes. |
| [Ten-strategy assessment](strategy-assessment.md) | See the decision for each user proposal, score interpretation, current official sources, and control boundaries. |
| [Execution record](execution-results.md) | See the later implementation trials, rejected candidates, retained evaluation fixtures, and validation limits. |
| [Native trial metrics](trial-metrics.json) | Inspect per-pair elapsed time, requested model/effort, and host-reported usage without loading full prompts or outputs. |

All 57 English runtime Markdown files were reviewed.
Code inspection followed entry points, prompt construction, output, retry, packaging, and lifecycle paths.
Tests were inventoried and relevant contract checks were inspected; this was not a complete code correctness audit.
Human translations were inventoried without loading them as executable instructions.
The existing `.plan/orca-plugin-refresh-resume/` directory was left intact and is not a runtime source.
The user's existing global Git ignore excludes `.plan/`; at plan creation these files existed locally and were not force-added.

These are source measurements, not token counts:

| Surface | UTF-8 bytes | Observation |
|---|---:|---|
| 10 plugin `SKILL.md` files | 170,733 | Loaded after skill selection, not all at session startup. |
| Their descriptions | 5,006 | 4,779 characters; routing context when the host exposes all 10 skills. |
| English runtime Markdown, including references and standalone skill | 344,261 | Repository inventory total; never assume one invocation loads this total. |
| Codex session context | 4,703 | Rendered at this repository path; installed path length changes the result. |
| Claude session context | 4,717 | Same measurement method and limitation. |
| `skill-builder/SKILL.md` | 31,229 | 524 lines, spanning authoring, evaluation, reporting, and packaging. |
| `flowchart-design/SKILL.md` | 27,852 | 433 lines, including SVG and PNG details for all renderers. |
| `tiki-taka/SKILL.md` | 22,846 | 377 lines, including recovery and conditional question-file authoring. |
| Deep Interview UI and scoring references | 14,128 | Instructions currently direct repeated reads during interview rounds. |

No Sonnet/Luna skill-behavior benchmark, hook lifecycle execution, or release operation was performed.
The strategy assessment adds public official-documentation research to the original static source inventory.
The session measurement called only the pure `render_context` function; it did not provision an agent.

## Implementation strategy

### Preserve the decision procedure

Each skill entrypoint must retain its trigger, required result, mandatory ordered steps, material exceptions,
stop conditions, and a short completion gate.
Move only substantial details for a named mode, renderer, host, or recovery state.
Every moved section needs an explicit read condition before its first dependent action.
An unknown route loads the necessary alternatives or resolves the uncertainty; it never guesses and skips them.

Keep conditions next to their actions, exact thresholds next to their comparisons, and a concrete example
where it distinguishes a likely mistake.
Preserve useful repetition between a procedure and its final check when the check catches omitted work.
Do not replace ordered rules with “use judgment,” acronym lists, or a summary that assumes strong inference.

Prefer one additional reference per selected mode over many tiny files.
Do not add a universal instruction registry, preprocessing framework, or new cross-skill dependency.
Retain the existing self-contained packaging and declared sibling-reference contracts.
Update every affected English document and its complete Korean mirror together.

### Optimize the cost the change actually affects

Distinguish logical tokens, active context, monetary cost, and completion time.
F25 adds stable-prefix optimization to repository-owned prompt assembly; F26 uses existing host tool discovery.
Neither adds cache flags or a tool registry to this plugin.
F27 strengthens recovery checks inside existing stateful workflows; it does not introduce automatic session resets.
The [strategy assessment](strategy-assessment.md) owns the detailed ten-way mapping and official evidence.

Quality and authorization remain hard gates before any weighted ranking.
The supplied score arithmetic is correct, but its Q/V/S/A values do not establish measured repository results.
Cache-only savings may leave logical input unchanged; record that as cache economics rather than context reduction.
Preserve accurate sources and instructions even when refreshing them breaks a cached prefix.

### Reuse only evidence that remains valid

Reuse a loaded instruction while its file revision, relevant runtime/tool schema, and available context remain valid.
Apply the instruction again at each required step without fetching identical text again.
Reload after file changes, relevant capability changes, a new independent context, or compaction that lost the rule.
Keep source/page version checks, ticket re-reads under locks, registry checks, and stored-result verification.

For interview questions, check the required payload rules against instructions actually available in context.
For scoring, check the formula, aggregation, thresholds, and transition rules the same way.
If those rules cannot be located, reload the active reference before acting; a remembered “loaded” flag is insufficient.
After an observable resume or compaction, reload the active UI/scoring reference before the next dependent action.

Preserve full raw evidence outside the prompt when the workflow already supports artifacts.
Use a concise index and targeted reads to navigate it; never silently truncate required evidence.
Do not introduce persistence to a skill that currently requires the user's approval for state files.

### Separate necessary measurements from ordinary use

Freeze the old skill plus its complete reference closure before any implementation.
Prepare equivalent old/new installations in isolated evaluation locations.
Keep model configuration, tools, permissions, inputs, and expected outcomes identical within each pair.
Measure optimization during development and keep ordinary skill use free of benchmark dependencies.

Keep the audited snapshot as `B0`. After S1, record a separate `B1` experimental snapshot with F01 corrected.
S2 compares against `B1`, so F11 does not mix prompt deduplication with the F01 quality-policy correction.
For each later candidate, freeze the preceding accepted experimental snapshot and change only that candidate.
These experimental baselines do not change the installed default.
Before adoption, also compare the combined version against `B0`; do not hide a cost increase introduced by S1.

Use `timing.json`, `grading.json`, and existing benchmark tools where their contracts apply.
Keep additional load traces, model/effort receipts, and adoption decisions in the evaluation workspace.
Do not extend the shipping benchmark schema merely to store this investigation's metadata.

## Execution slices

Use the listed order as a sequential resource schedule. No parallel implementation is assumed.
The dependency column lists actual prerequisites; S3, S4, and S5 do not depend on each other's code changes.
The listed Markdown edits always include their Korean mirrors.
The `F` identifiers refer to [Findings](findings.md).

| Slice | Result and concrete surfaces | Depends on | Completion evidence |
|---|---|---|---|
| S1 — Freeze and protect quality | Snapshot B0; derive requirement matrix; prepare runnable fixtures for F02–F03. Correct F01 in `skills/skill-builder/scripts/improve_description.py` and test prompt priority and existing invalid-candidate retry handling in `skills/skill-builder/tests/test_evaluation.py`. Resolve stale expected outcomes, then snapshot B1. | None | B0/B1 remain reproducible; optimizer prefers concise descriptions subject to complete intent coverage. Focused regressions pass; live quality and cost remain adoption gates. |
| S2 — Skill Builder execution | Evaluate F09–F13, then F25 independently after F11. Split mode detail, select schema sections, deduplicate prompt data, compare stable-prefix ordering, and keep full history out of parent output. Establish F26's canonical hosted-tool discovery guidance in `instructions/services.md`; skill capability sections defer to it where active. Preserve CLI defaults and JSON fields. | S1 | Authoring, evaluation, retry, report, package, cache, and tool-discovery cases pass; complete-path cost improves on both hosts without quality or performance loss. |
| S3 — Stateful skills | Evaluate F05–F07, F18–F19, and the interview/map part of F27. Scope UI reads, reuse valid instructions, verify checkpoints, and scan ticket metadata before relevant bodies. F06 depends on F05's measured residual cost. | S1, S2 | Dedicated native main-session, multi-round, compaction, state recovery, contradiction, lock, and concurrent-edit cases preserve every gate and required state. |
| S4 — Document and diagram skills | Evaluate F08, F16–F17, F20–F21, and Confluence's F26 capability route. Scope renderer/mode references and batch existing assets. Reuse the active service-access/discovery contract. | S1, S2 | Fidelity, visual inspection, source adapters, bounded tool discovery, publication concurrency, and missing-reference cases pass. Semantic review remains required. |
| S5 — Remaining entrypoints | Evaluate F14–F15, F22–F24, and Tiki-taka's F27 checkpoint/recovery safeguards. Preserve refresh transactions and exact-session debate behavior. | S1, S2 | Scope, consent, recovery, output shape, model selection, and complete search impact coverage are preserved. |
| S6 — Routing, integration, and release readiness | Evaluate F04 descriptions against the final bodies and native host routing. Validate adopted combinations against B0, complete mirrors, run README development checks, and prepare source/measurement receipts. Modify README only if actual file organization needs updating. | S2–S5 | Every adopted candidate passes validation; trigger precision and recall do not regress. Failed or unmeasured candidates remain at baseline. |

S1 and S6 are required gates. Every other optimization is conditional on its evidence.
A failed candidate does not block unrelated proven improvements, but it must not enter the released default.
Do not label the repository fully optimized while deferred candidates or unavailable model lanes remain.

## Integrated verification

Map every changed requirement to a scenario in [Validation](validation.md).
Verify both the complete installed plugin and standalone skill behavior where it is currently supported.
Test fresh selection, repeated invocation, long inputs, missing capabilities, and restored context.
Keep every critical assertion mandatory; a higher average score cannot offset one missing requirement.

For each affected scenario and native model lane, complete three matched old/new trials.
Use the conservative quality, time, token, and context gates from the validation document.
Use additional trials only in a later explicitly bounded investigation; an inconclusive result retains baseline.
For descriptions, preserve the existing repeated trigger trials and add native routing evidence.

Run these repository checks after implementation, using the environment setup from README:

```bash
for skill in skills/*/ standalone-skills/*/; do
  python3 skills/skill-builder/scripts/quick_validate.py "$skill"
done
python3 -m pytest
node --test skills/document-to-confluence/tests/test_render_diagrams.mjs
```

For this documentation-only deliverable, check local links, source measurements, mirror coverage, and diff scope.
Do not interpret those checks as evidence of Sonnet/Luna behavior or runtime savings.

## Rollout and stopping rule

Adopt each candidate independently after its complete evidence passes, then check the combined version.
If integration introduces a regression, revert the responsible candidate and its mirrors together.
Re-run only the affected comparisons plus shared integration checks.
Stop when the adopted changes pass and no unresolved finding requires further work.

Keep the source snapshot and trial artifacts outside normal runtime loading.
Do not remove quality checks, required independent perspectives, model effort, source coverage, or authorization
to satisfy an arbitrary token reduction percentage.

This plan does not change the current `0.6.0` version or claim it is the latest published release.
Before a later release, verify the published baseline and all other unreleased changes.
Behavior-preserving efficiency and reliability work normally contributes to one patch release.
If an implementation changes objectives, requirements, or external contracts, re-scope it and apply the repository's
minor/major policy instead. Keep both manifests, `pyproject.toml`, and `uv.lock` aligned.
Use a cachebuster for local reinstalls; publishing and session refresh require their own authorization.
