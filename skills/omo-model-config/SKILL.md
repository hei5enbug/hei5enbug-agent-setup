---
name: omo-model-config
description: Updates model, variant, and fallback_models fields in oh-my-openagent.json, adds missing upstream-supported agents/categories under the same gates, and removes agents.*.ultrawork entirely when it exists. Validates against available-models.json while treating required_fallback_providers as an explicit exception to GitHub fallback guidance when needed for provider coverage.
---

# OmO Model Configurator (GitHub-First)

Updates only top-level `model`, `variant`, and `fallback_models` under `agents.*` and `categories.*` in `oh-my-openagent.json`; ADDS new top-level entries under `agents.*` or `categories.*` when upstream defines them but local does not (subject to the same gates); and removes `agents.*.ultrawork` entirely when it exists.

## Scope

**Inputs**:
- This file
- `available-models.json` (`allowlist`, `tiers`, `required_fallback_providers`)
- `oh-my-openagent.json` (edit target)

**Core constraints**:
- GitHub references are primary authority. On conflict: GitHub > local rules.
- Edit only `oh-my-openagent.json`.
- Edit only top-level `agents.*.{model,variant,fallback_models}` and `categories.*.{model,variant,fallback_models}`.
- You MAY also **ADD** brand-new top-level keys under `agents.*` or `categories.*` ONLY when the key is defined upstream (in `src/shared/model-requirements.ts`'s `AGENT_MODEL_REQUIREMENTS` / `CATEGORY_MODEL_REQUIREMENTS`) but absent locally. New entries must contain only `model`, `variant` (when upstream specifies), and `fallback_models`, and must pass every gate that existing entries pass.
- Plus remove `agents.*.ultrawork` when an existing `ultrawork` block is present.
- Do not change any other keys.
- Do not invent agent/category names that upstream does not define. Adding is permitted only as a strict subset of the upstream target list.
- When this skill is invoked for a model-config change, treat the project-local `oh-my-openagent.json` as the default target and apply the change directly. Do **not** ask whether to update the project's `oh-my-openagent.json` first.

## Hard Boundary: GitHub Chain Is the Superset (Except Required Provider Coverage)

Treat the GitHub references as the **default allowed candidate set** for each target agent/category.

- Start from the upstream primary model and upstream fallback chain for that exact target.
- Your local output may be a **subset** of the upstream-supported chain after applying local constraints.
- Your local output may substitute an unavailable upstream model only with the **closest allowed model that preserves the same upstream role fit**.
- **NEVER add a provider or model that does not appear in the GitHub guidance for that exact target**, unless either (a) the user explicitly asks to deviate from upstream, or (b) `required_fallback_providers` requires provider coverage that upstream does not supply for that target.
- `required_fallback_providers` is an **explicit exception** to the upstream-superset rule. If a required provider is uncovered for a target, you may add the closest allowed model from that provider even when GitHub does not list that provider for the exact target.
- When using this exception, choose the smallest addition that satisfies coverage while preserving the target's role fit and existing upstream intent as much as possible.

### Forbidden interpretation

The following reasoning is always invalid:

> "This provider/model is in the allowlist and seems role-compatible, so I can append it to `fallback_models` for better diversity."

If the model/provider is not supported by the upstream references for that exact target, do not add it **unless it is required solely to satisfy `required_fallback_providers` coverage**.

### Concrete example

- If upstream Sisyphus fallbacks do **not** include Gemini, you must not add Gemini to `agents.sisyphus.fallback_models` just because Gemini is allowed locally.
- If `required_fallback_providers` demands OpenAI coverage and upstream Sisyphus already includes GPT-5.4, coverage is already satisfied. Do not add any extra provider.
- If `required_fallback_providers` demands OpenAI coverage and upstream Explore has no OpenAI candidate, you may append the closest allowed OpenAI model that preserves Explore's lightweight utility role.

## Step 1: Read and Resolve

1. Read GitHub references first. **`src/shared/model-requirements.ts` is the authoritative source-of-truth for fallback chains** — when prose docs conflict with the `.ts` code, the code wins:
   - **https://github.com/code-yeongyu/oh-my-openagent/blob/dev/src/shared/model-requirements.ts** ← AUTHORITATIVE (`AGENT_MODEL_REQUIREMENTS` / `CATEGORY_MODEL_REQUIREMENTS` actual code)
   - https://github.com/code-yeongyu/oh-my-openagent/blob/dev/docs/guide/agent-model-matching.md
   - https://github.com/code-yeongyu/oh-my-openagent/blob/dev/docs/guide/orchestration.md
   - https://github.com/code-yeongyu/oh-my-openagent/blob/dev/docs/reference/features.md#agents
   - https://github.com/code-yeongyu/oh-my-openagent/blob/dev/docs/reference/features.md#category-system
2. Read `available-models.json`.
3. Read `oh-my-openagent.json`.
4. Build a per-target upstream map for each edited item:
   - upstream primary model + variant
   - upstream fallback candidates in order
   - upstream-supported providers for that exact target
5. Apply user constraints from prompt.

### Reference Priority Rules

These rules apply throughout Steps 2–4 whenever upstream candidate sets, near-variant resolution, or fallback ordering are evaluated.

1. **`model-requirements.ts` overrides prose docs.** When `AGENT_MODEL_REQUIREMENTS` / `CATEGORY_MODEL_REQUIREMENTS` in `src/shared/model-requirements.ts` disagree with any markdown doc (`agent-model-matching.md`, `orchestration.md`, `features.md`) about fallback ordering, providers, variants, or chain composition, the `.ts` code wins. Treat prose docs as background context only. If a doc says "Sisyphus fallback is X → Y → Z" but the `.ts` chain is X → W → Y → Z, use the `.ts` chain.

2. **Antigravity wrapper preference (overrides "Cross-provider near-variants are forbidden" specifically for antigravity).** When the local allowlist contains two entries that share the same base model identifier under different provider segments and one of them is `google/antigravity-*` (e.g., `anthropic/claude-sonnet-4-6` and `google/antigravity-claude-sonnet-4-6`), treat them as **wrapper-equivalent**:
   - The `google/antigravity-*` entry takes precedence and is placed at the higher slot (primary if originally primary, or the leading fallback position otherwise).
   - The non-antigravity sibling (if also allowlisted) is placed immediately after the antigravity entry in the same chain.
   - This rule applies regardless of which providers upstream lists for that base model.
   - Antigravity is not a "similar model from a different provider" — it is the same underlying model routed through Google's gateway, so it counts as a direct match against the upstream identifier rather than a substitution.

### Resolve Upstream Candidate Set

Before using any local gate, explicitly answer for each target:

1. What is the upstream primary model?
2. What are the upstream fallback candidates, in order?
3. Which providers are upstream-supported for this exact target?
4. Which locally allowed models are direct matches to upstream candidates?
5. Which locally allowed models are substitutions for unavailable upstream candidates?

If you cannot answer these five questions for a target, do not edit that target.

### Identify Missing Targets

After resolving the upstream candidate sets, compute the set difference between upstream and local:

1. Enumerate the full upstream agent list from `AGENT_MODEL_REQUIREMENTS` keys in `src/shared/model-requirements.ts`.
2. Enumerate the full upstream category list from `CATEGORY_MODEL_REQUIREMENTS` keys in the same file.
3. Enumerate local keys present under `agents.*` and `categories.*` in `oh-my-openagent.json`.
4. Compute `missing_targets = upstream_targets − local_targets` for each of agents and categories.

For each `missing_target`:

- Build the same per-target upstream map (primary, fallback chain, supported providers) as for existing targets.
- Queue it for ADDITION during Step 3.
- The same availability gate, provider diversity gate, and fallback shape rules apply unchanged.
- If the user prompt explicitly excludes a target by name (e.g., "do not add sisyphus-junior"), skip it and report the skip.
- If a missing target's upstream chain has zero allowlisted models AND no `required_fallback_providers` exception that yields a viable entry, do NOT add it; report it as "addition deferred — no viable allowlisted candidate".

Adding is mandatory by default whenever a target is upstream-supported, missing locally, and has at least one viable allowlisted candidate after gates. The user may opt out per-target via the prompt.

## Step 2: Local Gates (only when not overridden by GitHub)

### Availability gate

- Every primary/fallback model must be in `allowlist`.
- If an upstream model is unavailable, replace it only with the closest allowed candidate that preserves the same upstream role fit.
- Prefer, in order:
  1. Exact upstream model if allowed.
  2. **Near-variant** of the upstream model present in the allowlist (see "Near-Variant Equivalence" below). Treated as a direct match — outranks all substitution paths and any jump to a different upstream-listed candidate.
  3. Another upstream-listed candidate for the same target, preserving upstream order.
  4. If no upstream-listed candidate is locally allowed and no near-variant exists, the nearest allowed equivalent for the same role family and tier.
- Availability substitution does **not** permit adding a brand-new provider/model that upstream never assigned to that target.

#### Near-Variant Equivalence

A locally allowlisted model qualifies as a **near-variant** of an upstream-specified model — and is therefore treated as the same model for primary/fallback ranking — when ALL of the following hold:

1. **Same provider segment.** The path component before the first `/` is identical between the two identifiers.
2. **Same base model identity.** After normalizing away speed/throughput suffix segments and minor-version or patch-revision segments, the remaining base identifier is identical.
3. **The only differences are confined to one or more of these dimensions**:
   - A speed/throughput suffix segment is added or removed.
   - A minor-version or patch-revision segment differs within the same major-version line.

A model is **NOT a near-variant** when ANY of the following is true:

- The provider segment differs.
- The base model lineage or generation differs (different family, different major architecture, different intended role).
- The capability tier or size class differs (e.g., a lightweight tier vs. a flagship tier of the same family).
- The difference indicates a specialty derivative (e.g., a domain-specialized variant vs. a general-purpose model of the same generation).

**Resolution behavior**: when a near-variant exists in the allowlist for an upstream-specified entry, use it in place of the upstream identifier. Classify it as a **direct match (near-variant)** in reports — never as a substitution. The near-variant resolution step runs BEFORE any jump to a different upstream-listed candidate, and BEFORE any cross-family substitution.

**Cross-provider near-variants are forbidden** — with one explicit exception: **antigravity wrappers** (see "Antigravity wrapper preference" under [Reference Priority Rules](#reference-priority-rules) in Step 1). Superficial similarity to a model from a different provider never qualifies, regardless of role overlap. Antigravity is not "superficial similarity" — it is the same underlying model accessed through Google's gateway, and is therefore treated as a wrapper-equivalent direct match, not a cross-provider substitution.

### Provider diversity gate

For each agent/category, required providers come from `required_fallback_providers`.

- A provider is considered covered if it appears in either the primary `model` or `fallback_models`.
- In `fallback_models`, keep at most one model per provider (no duplicates).
- If a required provider is uncovered, first look for an upstream-supported candidate from that provider for that exact target.
- If such an upstream-supported candidate exists and is allowed locally, use it.
- If the exact upstream-supported candidate is unavailable, use the nearest allowed equivalent **only when it preserves the same upstream role/provider intent**.
- If GitHub does not support that provider for the target, this rule becomes an exception to the upstream-superset boundary: add the closest locally allowed model from that provider that best fits the target's role and tier.
- If GitHub marks provider models as forbidden/dangerous for that target, skip that provider and report it.

### Fallback shape rules

- Preserve upstream intent and ordering as much as local constraints allow.
- `fallback_models` should usually be an ordered subset of the upstream fallback chain after filtering/substitution.
- Do not append "nice to have" redundancy.
- Do not add a fallback only because it exists in another agent/category's upstream chain.
- Do not infer cross-target compatibility from shared model families.

## Step 3: Apply Changes

1. Resolve target `model`, `variant`, `fallback_models` from GitHub guidance and user constraints.
2. Apply availability gate.
3. Apply provider diversity gate.
4. If an edited agent already has an `ultrawork` block, remove `agents.*.ultrawork` entirely.
5. **For each missing target identified in Step 1 "Identify Missing Targets"**, construct a new top-level entry under `agents.*` or `categories.*`:
   a. Set `model` to the highest-priority allowlisted upstream candidate (and `variant` if upstream specifies one for that entry).
   b. Build `fallback_models` as the ordered subset of the remaining upstream chain after availability filtering and substitutions.
   c. Apply the provider diversity gate (`required_fallback_providers`); if the upstream chain does not cover a required provider, append the smallest closest-fit allowed model from that provider as a `required_fallback_providers` exception.
   d. The new entry must include only `model`, `variant` (when applicable), and `fallback_models`. No other keys.
   e. The new entry must satisfy every Step 4 validation rule.
6. Before writing, run this pre-write check for every edited AND every newly-added target:
   - Is every selected model either directly upstream-supported for this target, a justified availability substitution, or a justified `required_fallback_providers` exception?
   - Did I avoid adding any provider/model absent from this target's upstream chain unless it was required by `required_fallback_providers`?
   - Is provider coverage satisfied, including any justified `required_fallback_providers` exception beyond upstream support?
   - If `ultrawork` exists, was the entire `ultrawork` block removed?
   - For NEWLY-ADDED targets: is the target name present in the upstream `AGENT_MODEL_REQUIREMENTS` or `CATEGORY_MODEL_REQUIREMENTS`? (If no, do not add — that would be inventing a name.)
7. Write only allowed fields; preserve everything else.

## Step 4: Validate

1. JSON is valid.
2. All chosen models are in `allowlist`.
3. No GitHub-forbidden model is selected.
4. For every edited agent with an existing `ultrawork` block, `agents.*.ultrawork` is removed.
5. Non-target fields are unchanged (including existing root settings such as `runtime_fallback`).
6. Every selected provider/model is either directly supported by the upstream chain for that target, explicitly justified as an availability substitution, or explicitly justified by a `required_fallback_providers` exception.
7. No fallback provider/model was added solely because it was allowlisted, same-tier, or used by another target, except when required to satisfy `required_fallback_providers`.
8. Provider coverage is satisfied, or explicitly reported when impossible due to forbidden/unavailable models even after applying the `required_fallback_providers` exception.
9. Any substitution includes a target-specific rationale explaining why it is the nearest allowed equivalent.
10. For every NEWLY-ADDED target:
    - The target name exists in upstream `AGENT_MODEL_REQUIREMENTS` or `CATEGORY_MODEL_REQUIREMENTS`.
    - The new entry contains ONLY `model`, `variant` (when applicable), and `fallback_models` — no extra keys.
    - All gates (availability, provider diversity, fallback shape, mandatory failure mode check) pass identically as for edited entries.
    - Placement preserves alphabetical or upstream-canonical order if the surrounding file follows one; otherwise append at the end of the relevant `agents.*` / `categories.*` block.

### Mandatory failure mode check

Before finalizing, explicitly test the draft against this question for each edited target:

> "Am I adding anything here that upstream never assigned to this exact target, and if so, is it required by `required_fallback_providers` or an explicit user-requested upstream deviation?"

If the answer is yes, remove it unless it is required by `required_fallback_providers` or the user explicitly requested an upstream deviation.

## Step 5: Report

```
| Item | Action | Model | Variant | Fallbacks | Reason |
|------|--------|-------|---------|-----------|--------|
```

`Action` column values: `MODIFIED`, `ADDED`, `UNCHANGED`, `SKIPPED`, `ULTRAWORK_REMOVED`.

Always flag:
- Substitutions caused by availability limits
- Missing provider coverage and why it was impossible
- Cases where GitHub guidance overrode local assumptions
- Target-specific rationale for every substitution
- Any target intentionally left unchanged because upstream evidence was insufficient
- **NEWLY ADDED targets**: list each one explicitly with its full chain rationale and confirmation that it exists in upstream `AGENT_MODEL_REQUIREMENTS` / `CATEGORY_MODEL_REQUIREMENTS`.
- **Addition deferred**: any missing-upstream target that could not be added because zero allowlisted models satisfy gates — explain which models would be needed to enable addition.

When reporting `fallback_models`, distinguish between:
- **Direct upstream matches** (exact identifier match against the upstream chain)
- **Direct matches via near-variant** (per "Near-Variant Equivalence" — same provider, same base, differing only by speed/throughput or minor-version segment)
- **Wrapper-equivalent (antigravity)** (per "Antigravity wrapper preference" — `google/antigravity-*` entry of an upstream-listed base model; treated as a direct match, not a substitution)
- **Availability substitutions** (cross-family or cross-tier replacement when no near-variant or wrapper-equivalent entry exists)
- **Coverage gaps left unresolved because upstream offered no valid candidate**

## Step 6: Offer Local Config Sync (Ask Only — NEVER Auto-Apply)

After reporting, search for a separate non-project `oh-my-openagent.json` on the user's local machine. Do not confuse this step with the project-local `oh-my-openagent.json` that this skill edits by default.

### Search location

Check whether a separate non-project `oh-my-openagent.json` exists.

### Present findings

If the file exists, ask:

```
Found a separate oh-my-openagent config outside this project.
Would you like to apply the same model changes there too?
```

If the file does not exist, skip this step silently.

### Constraints

- **NEVER apply changes to a separate non-project config without explicit user confirmation.** This step is question-only.
- Wait for the user to respond before taking any action on that separate config.
- Do not describe the project's own `oh-my-openagent.json` as the local-config-sync target in this step.
- If the user confirms, apply the same gates (availability, provider diversity) to that separate config. Use the same `available-models.json` from this project for validation.
