---
name: omo-model-config
description: Safely updates the model, variant, and fallback_models fields under agents.* and categories.* in oh-my-openagent.json, adds missing upstream-defined agents/categories under the same gates, and removes agents.*.ultrawork entirely when present. Treats the upstream oh-my-openagent agent-model-requirements.ts / category-model-requirements.ts as the authoritative candidate set and validates every model against available-models.json, treating required_providers as the one explicit exception to upstream guidance for provider coverage.
---

# OmO Model Configurator (GitHub-First)

Edits the model routing in `oh-my-openagent.json` against an authoritative upstream definition. This skill changes **only** the `model`, `variant`, and `fallback_models` of each `agents.*` / `categories.*` target, **adds** brand-new targets that upstream defines but the local file lacks, and **removes** any `agents.*.ultrawork` block. Every other key, value, and formatting choice is preserved untouched.

## Scope

**Inputs (read all three before editing):**
- This file (`SKILL.md`).
- `available-models.json` — local environment limits: `allowlist`, `tiers`, `required_providers`.
- `oh-my-openagent.json` — the single edit target.

**Editable (the only writes allowed):**
- `agents.*.model`, `agents.*.variant`, `agents.*.fallback_models`.
- `categories.*.model`, `categories.*.variant`, `categories.*.fallback_models`.
- **ADD** a brand-new top-level key under `agents.*` or `categories.*` only when that key is defined upstream (in `AGENT_MODEL_REQUIREMENTS` / `CATEGORY_MODEL_REQUIREMENTS`) but absent locally. A new entry may contain only `model`, `variant` (when upstream specifies one), and `fallback_models`, and must pass every gate that existing entries pass.
- **REMOVE** `agents.*.ultrawork` entirely whenever an `ultrawork` block exists on an agent.

**Forbidden:**
- Editing any file other than `oh-my-openagent.json`.
- Editing any key other than the three editable fields (e.g. never touch `runtime_fallback`, `disabled_hooks`, `disabled_providers`, `google_auth`, `$schema`, `description`, `temperature`, `tools`, `prompt`, etc.).
- Inventing an agent/category name that upstream does not define. Adding is permitted only as a strict subset of the upstream target list.
- Adding a provider/model that upstream never assigned to that exact target, except under the two explicit exceptions below (user request, `required_providers`).

**Default target:** When invoked for a model-config change, treat the project-local `oh-my-openagent.json` as the target and apply the change directly. Do **not** ask whether to edit the project file first. (A *separate*, non-project config is handled by Step 6, which is ask-only.)

## Authority & References

GitHub upstream (`code-yeongyu/oh-my-openagent`, branch `dev`) is the primary authority. On any conflict: **GitHub code > GitHub prose docs > local assumptions.**

**Source-of-truth for model chains (read first):**
- `packages/model-core/src/agent-model-requirements.ts` ← **AUTHORITATIVE.** Holds the real `AGENT_MODEL_REQUIREMENTS` object literal (each agent's `fallbackChain` plus gate flags `requiresAnyModel`, `requiresProvider`, `requiresModel`).
- `packages/model-core/src/category-model-requirements.ts` ← **AUTHORITATIVE.** Holds the real `CATEGORY_MODEL_REQUIREMENTS` object literal (each category's `fallbackChain`).
- `packages/model-core/src/model-requirement-types.ts` ← **AUTHORITATIVE.** Defines the `FallbackEntry` / `ModelRequirement` types (the `variant` field and the gate flags).
- `packages/model-core/src/model-requirements.ts` — re-export **barrel only**; forwards `AGENT_MODEL_REQUIREMENTS`, `CATEGORY_MODEL_REQUIREMENTS`, and the types from the three modules above. Reading this file alone shows only `export` lines, **not** the chains — open the two `*-model-requirements.ts` files for the actual data.
- `src/shared/model-requirements.ts` — re-export entry point only; forwards `AGENT_MODEL_REQUIREMENTS`, `CATEGORY_MODEL_REQUIREMENTS`, and the types from `@oh-my-opencode/model-core`.

**Source-of-truth for the config FILE SHAPE (the legal serialization):**
- `src/config/schema/fallback-models.ts` — defines `FallbackModelsSchema` (what `fallback_models` may contain).
- `src/config/schema/agent-overrides.ts` — `AgentOverrideConfigSchema` (legal keys/types for an `agents.*` entry).
- `src/config/schema/categories.ts` — `CategoryConfigSchema` (legal keys/types for a `categories.*` entry).
- `assets/oh-my-opencode.schema.json` — the generated JSON Schema (note the filename is `oh-my-opencode.schema.json`, **not** `oh-my-openagent.schema.json`).

**Prose docs (background context only — the code wins on any disagreement):**
- `docs/guide/agent-model-matching.md`, `docs/guide/orchestration.md`, `docs/reference/features.md#agents`, `docs/reference/features.md#category-system`.

### Reference Priority Rules

Apply these whenever upstream candidate sets, near-variant resolution, or fallback ordering are evaluated.

1. **The `agent-model-requirements.ts` / `category-model-requirements.ts` chain files override prose docs.** If `AGENT_MODEL_REQUIREMENTS` / `CATEGORY_MODEL_REQUIREMENTS` disagree with any markdown doc about ordering, providers, variants, or chain composition, the `.ts` code wins. (Example: the prose `writing` chain has historically drifted from the code chain — trust the code.) Treat prose as background only.

2. **Antigravity wrapper preference (overrides "cross-provider near-variants are forbidden" for antigravity only).** When the allowlist contains two entries that share the same base model under different provider segments and one is `google/antigravity-*` (e.g. `anthropic/claude-sonnet-4-6` and `google/antigravity-claude-sonnet-4-6`), treat them as **wrapper-equivalent**:
   - The `google/antigravity-*` entry **always** takes the higher slot — primary if that slot was originally primary, otherwise the leading fallback position. This is top priority: when the exact same underlying model is available as an antigravity wrapper, the wrapper is used first.
   - The non-antigravity sibling (if also allowlisted) is placed immediately after the antigravity entry in the same chain.
   - This applies regardless of which providers upstream lists for that base model. Antigravity is the same underlying model routed through Google's gateway, so it counts as a **direct match** to the upstream identifier, not a substitution, and not a new provider.

## Decision Policy (GitHub-First Superset)

Treat the upstream references as the **default allowed candidate set** for each target.

- Start from the upstream primary model + variant and the upstream fallback chain for that exact target.
- The local output may be a **subset** of the upstream chain after local constraints are applied.
- The local output may substitute an unavailable upstream model only with the closest allowed model that preserves the same upstream role fit (see the substitution order in Step 2).
- **NEVER add a provider or model that upstream does not list for that exact target** — unless one of the two explicit exceptions below applies.

### Exception 1 — Explicit user request

When the user's prompt explicitly names a model or provider for a target (e.g. "set Oracle primary to claude-opus-4-8", "add gpt-5.4 to Librarian fallback"):

- **Hard gate — allowlist:** the requested model must be in `allowlist`. If it is not, do **not** apply it; report it as `SKIPPED — not in allowlist` and leave that target's affected field unchanged.
- **Soft gate — upstream role fit:** the request does **not** have to match the upstream candidate set for that target. If it diverges from upstream's role/provider intent, apply it anyway and record a **warning** in the report ("user-requested, diverges from upstream role fit"). Role fit never blocks an explicit, allowlisted user request.
- This exception is scoped to exactly what the user named. Do not generalize a single explicit request into other targets or extra "nice to have" additions.

### Exception 2 — `required_providers` coverage

`required_providers` (in `available-models.json`) lists providers that must be covered for every target. Coverage means the provider appears in **either** the primary `model` **or** somewhere in `fallback_models`.

- If a required provider is already covered (including by the primary), do nothing extra.
- If it is uncovered, first try an upstream-listed candidate from that provider for that target; if none is allowlisted, add the **closest allowed model from that provider** that best fits the target's role/tier — even when upstream does not list that provider for the target. This is the only provider-coverage-driven exception to the upstream-superset rule.
- Use the smallest addition that satisfies coverage while preserving the target's role intent.

> **Naming note:** this key was previously `required_fallback_providers`. It was renamed to `required_providers` because coverage is satisfied by the primary model too, not only by fallback entries — so "fallback" in the old name was misleading.

### Forbidden interpretation

This reasoning is always invalid:

> "This model is in the allowlist and seems role-compatible, so I can append it to `fallback_models` for better diversity."

If a model/provider is not in the upstream chain for that exact target, do not add it **unless** it satisfies Exception 1 (explicit user request) or Exception 2 (`required_providers`).

**Concrete examples:**
- If upstream Sisyphus fallbacks do not include Gemini, do not add Gemini to `agents.sisyphus.fallback_models` just because Gemini is allowlisted.
- If `required_providers` demands OpenAI and upstream Sisyphus already includes a GPT model, coverage is satisfied — add nothing extra.
- If `required_providers` demands OpenAI and upstream Explore has no OpenAI candidate, append the closest allowed OpenAI model that preserves Explore's lightweight utility role.

## Config Format Rules (`oh-my-openagent.json` shape)

The legal shape is defined by `src/config/schema/*.ts` (verified upstream). Follow it exactly.

**Primary entry:** top-level `model` (string) plus an optional sibling `variant` (string). Write `variant` only when upstream specifies one for that target or the user requests one. The skill always keeps a concrete `model` on every target it writes.

**`fallback_models` serialization** — `FallbackModelsSchema` accepts a string, a string array, an object array, **or a mixed array**. Therefore:
- Use a **plain string** for a fallback entry that needs no variant: `"opencode-go/kimi-k2.6"`.
- Use an **object** `{ "model": "...", "variant": "..." }` **only** when that entry needs a variant (upstream-specified or user-requested): `{ "model": "openai/gpt-5.5", "variant": "medium" }`.
- **Mixed arrays are valid** and expected — do not normalize a mixed array into all-objects or all-strings. Only the entries that carry a variant become objects.

**`variant` values:** the config schema accepts any string for `variant` (no enum at the config layer). Preserve the variant strings upstream/user specifies (e.g. `max`, `high`, `xhigh`, `medium`); do not invent or "normalize" them.

**Never write extra keys:** the parser strips unknown keys, so a new/edited entry must contain only `model`, `variant` (when applicable), and `fallback_models`. Do not add `reasoningEffort`, `temperature`, `thinking`, etc. unless the user explicitly asks (and even then, only via a different, explicit request — this skill's default scope is the three fields).

**`google_auth` is NOT a model gate.** `oh-my-openagent.json` may contain `google_auth: false` while many targets use `google/antigravity-*` models — this is valid. Upstream does not define `google_auth` in its config schema, no source path reads it, and the parser strips it. Google/antigravity availability is governed by provider connection (and `disabled_providers`), never by `google_auth`. Therefore:
- Do **not** treat `google_auth: false` as a reason to reject, substitute, or down-rank any `google/*` or `google/antigravity-*` model.
- Do **not** add or remove `google_auth` (it is a non-target key — preserve it as-is).

## Step 1 — Read & Resolve

1. Read the authoritative chain files — `packages/model-core/src/agent-model-requirements.ts` (`AGENT_MODEL_REQUIREMENTS`), `packages/model-core/src/category-model-requirements.ts` (`CATEGORY_MODEL_REQUIREMENTS`), and `packages/model-core/src/model-requirement-types.ts` (types + gate flags). The `model-requirements.ts` barrel only re-exports these, so it is not enough on its own. When prose docs conflict with the chain files, the `.ts` wins.
2. Read `available-models.json`.
3. Read `oh-my-openagent.json`.
4. Build a per-target upstream map for each item you will edit or add.
5. Apply user constraints from the prompt (Exception 1).

### Resolve the upstream candidate set

Before applying any local gate, answer for each target:

1. What is the upstream primary model (and variant)?
2. What are the upstream fallback candidates, in order?
3. Which providers are upstream-supported for this exact target?
4. Which allowlisted models are direct matches to upstream candidates (including near-variants and antigravity wrappers)?
5. Which allowlisted models are substitutions for unavailable upstream candidates?

If you cannot answer all five for a target, do not edit that target — report it as unchanged due to insufficient upstream evidence.

### Identify missing targets

1. Enumerate every key in `AGENT_MODEL_REQUIREMENTS` and `CATEGORY_MODEL_REQUIREMENTS`.
2. Enumerate every key under `agents.*` and `categories.*` in `oh-my-openagent.json`.
3. Compute `missing = upstream_targets − local_targets` for agents and for categories.

For each missing target, build the same per-target upstream map and queue it for ADDITION in Step 3. Adding is the default whenever a target is upstream-defined, missing locally, and has at least one viable allowlisted candidate after the gates.
- If the user prompt excludes a target by name, skip it and report the skip.
- If a missing target's upstream chain yields zero viable allowlisted candidates (even after the `required_providers` exception), do **not** add it; report it as `addition deferred — no viable allowlisted candidate` and name the model(s) that would unblock it.

## Step 2 — Local Gates

These apply whenever a choice is not already pinned by upstream or by an explicit user request.

### Availability gate and substitution order

Every primary/fallback model must be in `allowlist`. When an upstream model is not allowlisted, choose its replacement by evaluating candidates **in this fixed order** (first viable wins), using the allowlist as the final viability check at each step:

1. **Exact upstream model**, if allowlisted.
2. **Near-variant** of the upstream model in the allowlist (see below) — treated as a direct match; outranks any jump to a different upstream candidate. The antigravity wrapper of the upstream model also resolves here (and takes the higher slot per Reference Priority Rule 2).
3. **Another upstream-listed candidate** for the same target, preserving upstream order.
4. **Same role family** equivalent (a model upstream uses for the same role across the harness), if no upstream candidate for this target is allowlisted.
5. **Same tier** equivalent (per `tiers`) as the last resort, preserving the target's role intent.

This order is canonical: the same request must always yield the same chain. Availability substitution never adds a provider/model upstream never assigned to the target (the only provider additions come from Exceptions 1 and 2).

### No viable candidate → keep existing, report deferred

If, after walking the full substitution order (and the `required_providers` exception), a target has **zero** viable allowlisted candidates for a field:
- Do **not** invent a model, and do **not** write an empty `fallback_models: []`.
- **Leave that target's existing configuration unchanged**, and report it as `deferred / unsupported`, naming what would be required to resolve it.

This protects the file from being degraded into arbitrary or empty chains when the local environment cannot satisfy a target.

### Near-variant equivalence

A locally allowlisted model is a **near-variant** of an upstream-specified model — and is ranked as the same model — when ALL hold:
1. **Same provider segment** (identical path component before the first `/`).
2. **Same base model identity** after normalizing away speed/throughput suffixes and minor/patch-version segments.
3. The only differences are a speed/throughput suffix and/or a minor/patch-version segment within the same major-version line.

It is **NOT** a near-variant when ANY holds: the provider segment differs; the base lineage/generation differs; the capability tier/size class differs; or it is a specialty derivative of a general model. (Example: `claude-opus-4-8` is a near-variant of upstream `claude-opus-4-7` — same provider, same `claude-opus-4` base, patch-version bump.)

**Cross-provider near-variants are forbidden**, with the single exception of antigravity wrappers (Reference Priority Rule 2). Classify a near-variant as a **direct match (near-variant)** in reports, never as a substitution. Near-variant resolution runs before any jump to a different upstream candidate and before any cross-family substitution.

### Antigravity wrapper: ordering vs. diversity

Antigravity has two distinct, non-conflicting effects:
- **Upstream matching & ordering:** `google/antigravity-X` is a wrapper-equivalent direct match to upstream `X` and **always** takes the higher slot over its non-antigravity sibling (Reference Priority Rule 2).
- **Provider diversity counting:** diversity is computed on the **actual path provider**. `google/antigravity-claude-sonnet-4-6` counts as the `google` provider, and `anthropic/claude-sonnet-4-6` counts as `anthropic`. Wrapper-equivalence is used for *matching*, not for *diversity*. Because the wrapper and its sibling are different path providers, both may coexist in one `fallback_models` without violating the one-per-provider rule below.

### Provider diversity gate (`required_providers`)

Required providers come from `required_providers`.
- A provider is covered if it appears in the primary `model` **or** in `fallback_models` (path-provider based; see antigravity note above).
- In `fallback_models`, keep at most one model per provider (no duplicate providers).
- If a required provider is uncovered, resolve it via Exception 2 (prefer an upstream-listed candidate from that provider; otherwise the closest allowed model from that provider).
- If upstream marks a provider's models as forbidden/dangerous for the target, skip that provider and report it.

### Fallback shape rules

- Preserve upstream intent and ordering as far as local constraints allow; `fallback_models` should be an ordered subset of the upstream chain after filtering/substitution.
- Do not append "nice to have" redundancy.
- Do not add a fallback only because another target's upstream chain uses it, or only because it shares a model family.

## Step 3 — Apply Changes

1. Resolve each edited target's `model`, `variant`, `fallback_models` from upstream + user constraints.
2. Apply the availability gate and substitution order (Step 2), including the "no viable candidate → keep existing" rule.
3. Apply the provider diversity gate (`required_providers`).
4. If an edited agent has an `ultrawork` block, remove `agents.*.ultrawork` entirely.
5. For each missing target queued in Step 1, construct a new top-level entry:
   a. `model` = highest-priority allowlisted upstream candidate (and `variant` if upstream specifies one).
   b. `fallback_models` = ordered subset of the remaining upstream chain after availability filtering/substitution, serialized per the Config Format Rules (object only where a variant applies).
   c. Apply `required_providers` (Exception 2) if a required provider is uncovered.
   d. The entry contains only `model`, `variant` (when applicable), and `fallback_models`.
   e. It must pass every Step 4 rule.
6. Pre-write check for every edited AND newly-added target:
   - Is every selected model upstream-supported for this target, a justified availability substitution, an explicit allowlisted user request, or a justified `required_providers` exception?
   - Did I avoid adding any provider/model absent from this target's upstream chain except via Exception 1 or 2?
   - Is provider coverage satisfied?
   - If an `ultrawork` block existed, was it fully removed?
   - For newly-added targets: is the name present in `AGENT_MODEL_REQUIREMENTS` / `CATEGORY_MODEL_REQUIREMENTS`? (If not, do not add.)
   - Is the serialization legal (mixed array OK; object only where a variant exists; no stripped/unknown keys)?
7. Write only allowed fields; preserve every other key and the file's existing formatting.

## Step 4 — Validate

1. JSON is valid.
2. Every chosen model is in `allowlist`.
3. No upstream-forbidden model is selected.
4. Every existing `agents.*.ultrawork` block is removed.
5. Non-target fields are unchanged (including `runtime_fallback`, `disabled_hooks`, `disabled_providers`, `google_auth`, `$schema`, and any others).
6. Every selected provider/model is upstream-supported for that target, a justified availability substitution, an explicit allowlisted user request (role-fit warnings recorded), or a justified `required_providers` exception.
7. No fallback was added solely because it was allowlisted, same-tier, or used by another target (except Exception 1/2).
8. Provider coverage is satisfied, or its impossibility is reported (forbidden/unavailable even after Exception 2).
9. Every substitution has a target-specific rationale (why it is the nearest allowed equivalent).
10. No target was degraded to an empty or arbitrary chain; any target with no viable candidate is left unchanged and reported as deferred/unsupported.
11. `fallback_models` serialization is legal: mixed string/object arrays allowed; objects used only where a variant applies; no unknown keys.
12. For every newly-added target: the name exists upstream; the entry has only `model`, `variant` (when applicable), `fallback_models`; all gates pass; placement follows the file's existing ordering (otherwise append to the end of the relevant block).

### Mandatory failure-mode check

For each edited/added target, answer:

> "Am I adding anything upstream never assigned to this exact target? If so, is it justified by an explicit allowlisted user request or by `required_providers`?"

If yes and neither justification holds, remove it.

## Step 5 — Report

```
| Item | Action | Model | Variant | Fallbacks | Reason |
|------|--------|-------|---------|-----------|--------|
```

`Action` values: `MODIFIED`, `ADDED`, `UNCHANGED`, `SKIPPED`, `DEFERRED`, `ULTRAWORK_REMOVED`.

Always flag:
- Availability substitutions (with target-specific rationale).
- Missing provider coverage and why it was impossible.
- Cases where upstream overrode a local assumption.
- Explicit user requests that diverge from upstream role fit (**warning**).
- Targets left unchanged due to insufficient upstream evidence or no viable candidate (`DEFERRED`).
- Newly-added targets: list each with its full chain rationale and confirmation that the name exists in `AGENT_MODEL_REQUIREMENTS` / `CATEGORY_MODEL_REQUIREMENTS`.

When reporting `fallback_models`, distinguish:
- **Direct upstream matches** (exact identifier match).
- **Direct matches via near-variant** (same provider, same base, differing only by speed/throughput or minor-version).
- **Wrapper-equivalent (antigravity)** (`google/antigravity-*` of an upstream-listed base model; a direct match, not a substitution).
- **Availability substitutions** (cross-family or cross-tier replacement when no near-variant/wrapper exists).
- **Coverage exceptions** (`required_providers` additions beyond upstream support).
- **Coverage gaps** left unresolved because upstream offered no valid candidate.

## Step 6 — Offer Local Config Sync (Ask Only — NEVER Auto-Apply)

After reporting, check whether a **separate, non-project** `oh-my-openagent.json` exists on the user's machine (distinct from the project file this skill edits by default).

- If it exists, ask:

  ```
  Found a separate oh-my-openagent config outside this project.
  Would you like to apply the same model changes there too?
  ```

- If it does not exist, skip this step silently.

**Constraints:**
- **Never** apply changes to a separate, non-project config without explicit user confirmation. This step is question-only.
- Wait for the user's response before touching that file.
- Do not describe the project's own `oh-my-openagent.json` as the sync target here.
- If the user confirms, apply the same gates and the same `available-models.json` validation to that separate config.
