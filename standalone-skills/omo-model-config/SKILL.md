---
name: omo-model-config
description: >-
  Provider-agnostic model-routing updates for agents.* and categories.* in oh-my-openagent.json from
  commit-pinned upstream chains and available-models.json; adds missing upstream targets, removes
  agents.*.ultrawork, preserves every unrelated setting, and offers confirmed-only sync to external
  configs. Use for full routing refreshes, targeted model, reasoning, and fallback-chain changes
  across any provider or model family, and migration of deprecated routing fields to the current
  models and reasoning shape.
compatibility: >-
  Works from any agent host with filesystem access, safe JSON editing, and access to the pinned
  upstream sources. If authoritative sources are unavailable, routing changes must be deferred as
  described below.
---

# OmO Model Configurator

Update model routing across all providers and model families from the current upstream `dev` branch without changing unrelated config.

## Hard scope

- **WRITE ONLY** `agents.*.{models,model,reasoning}` and `categories.*.{models,model,reasoning}`.
- Add a missing agent or category only when upstream defines its exact name. A new entry may contain only `models`, or `model` with optional `reasoning`.
- Remove every `agents.*.ultrawork` block. Do not touch similarly named keys elsewhere.
- **PRESERVE** every other key, value, order, and formatting choice, including `$schema`, `disabled_*`, `runtime_fallback`, and every host block such as `[opencode]`.
- Never invent a target, field, provider, model, or reasoning level.
- Never write a deprecated routing field. `variant` and `reasoningEffort` are replaced by `reasoning`; `fallback_models` is replaced by `models`.
  When the target config still uses a deprecated field, rewrite that target to the current shape instead of preserving it.
- Edit the project-local `oh-my-openagent.json` directly by default. Treat an external config as a target only after the user explicitly approves that exact sync.

## Required inputs and authority

Read this file, `available-models.json`, and the target config before editing.

Treat no provider or model family as the default. Derive every choice from the pinned upstream sources, `available-models.json`, and explicit user policy.

For every run, resolve the current `dev` SHA from the [commit history](https://github.com/code-yeongyu/oh-my-openagent/commits/dev).
Use the [model-core directory](https://github.com/code-yeongyu/oh-my-openagent/tree/dev/packages/model-core/src) as the inventory.
Replace `dev` in the discovery links below with that full SHA, then read all required files from the same commit.

| Source group | Required files |
|---|---|
| Chains | [agents](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/model-core/src/agent-model-requirements.ts) |
| Chains | [categories](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/model-core/src/category-model-requirements.ts) |
| Chains | [types](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/model-core/src/model-requirement-types.ts) |
| Freshness contract | [invariants](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/model-core/src/model-requirements-invariants.test.ts) |
| Runtime matching | [availability](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/model-core/src/model-availability.ts) |
| Runtime matching | [pipeline](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/model-core/src/model-resolution-pipeline.ts) |
| Runtime matching | [provider transforms](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/model-core/src/provider-model-id-transform.ts) |
| Fallback parsing | [chain parser](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/model-core/src/fallback-chain-from-models.ts) |
| Fallback parsing | [resolver](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/model-core/src/model-resolver.ts) |
| Fallback parsing | [known variants](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/model-core/src/reasoning-level.ts) |
| Config shape | [model reference](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/omo-config-core/src/schema/model-ref.ts) |
| Config shape | [reasoning vocabulary](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/omo-config-core/src/schema/reasoning-vocabulary.ts) |
| Config shape | [legacy field normalization](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/omo-config-core/src/schema/fallback-models.ts) |
| Config shape | [agents](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/omo-config-core/src/schema/agent.ts) |
| Config shape | [categories](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/omo-config-core/src/schema/category.ts) |
| Config shape | [host agent overrides](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/omo-opencode/src/config/schema/agent-overrides.ts) |
| Config shape | [host categories](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/omo-opencode/src/config/schema/categories.ts) |
| Config shape | [JSON Schema](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/assets/omo.schema.json) |
| Field migration | [reasoning unification](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/omo-opencode/src/config-migration/reasoning-unification.ts) |
| Field migration | [expected output fixture](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/omo-opencode/src/config-migration/2026-08-reasoning-unification/fixture-expected.json) |

- Conditional tests: from the pinned model-core inventory, read every provider- or model-specific resolution test relevant to a candidate being considered. Ignore unrelated specialized tests.

The `model-requirements.ts` barrel is not a chain source.
The canonical `$schema` target is `assets/omo.schema.json`, published by [`OMO_SCHEMA_URL`](https://github.com/code-yeongyu/oh-my-openagent/blob/dev/packages/omo-opencode/src/config-migration/schema-url.ts).
`assets/oh-my-opencode.schema.json` covers only the `[opencode]` host block, and `oh-my-openagent.schema.json` does not exist. Prose docs are background only.

### Freshness gate

1. Confirm that all required files use one commit.
2. Confirm that both chain objects match the target list and every negative constraint in the invariants test, including retired identifiers.
3. On disagreement, re-fetch every file pinned to the resolved SHA.
4. If a required fetch fails or the pinned files still disagree, **STOP MODEL ROUTING** and report it as deferred. Only `agents.*.ultrawork` cleanup may continue.

Use this priority: chain objects > runtime code and contract tests > config schemas > prose docs > local assumptions.
Treat `available-models.json` and user policy as constraints, not upstream recommendations.

## Resolution policy

Enumerate every upstream and local target. For each target, record the ordered `fallbackChain`, variants, providers, and `requiresModel` / `requiresAnyModel` / `requiresProvider` gates.

Apply an explicit user request only to the named target and field:

- Require the requested model to be in `allowlist`; otherwise leave it unchanged and report `SKIPPED — not in allowlist`.
- Apply an allowlisted request even when it diverges from upstream role fit, but report a warning.
- Do not generalize the request to other targets or models.

Otherwise select only allowlisted candidates in this order:

1. Exact upstream model.
2. Runtime-recognized transformed or fuzzy match.
3. Version-near substitution from the same provider.
4. Next upstream candidate, preserving chain order.
5. Same-role-family equivalent under a provider supported for that target.
6. Same-tier equivalent from `tiers` under a provider supported for that target.

A version-near substitution must keep the same provider, base lineage, capability class, and major version. Only a speed suffix or minor/patch version may differ.
A specialty derivative or different size class is not version-near. Classify it as a substitution unless the runtime pipeline recognizes it directly. Preserve the selected upstream rung reasoning level.

**Never add a provider absent from the target chain** except for an explicit user request or `required_providers`.
Every non-exact model must have a target-specific rationale from the ordered rules above; allowlist membership alone is never enough.

After resolving the upstream subset:

- Keep upstream order and at most one fallback per path provider.
- Do not append redundancy or a model merely used by another target.
- Count a provider in either the primary model or fallbacks toward `required_providers`.
- For missing required coverage, prefer an allowlisted upstream candidate from that provider; otherwise add the closest allowlisted same-role/tier model from that provider.
  Add only the smallest coverage entry. Skip and report an upstream-forbidden provider.
- If no viable candidate exists, leave the existing target unchanged. Do not write an arbitrary or empty `models` array.
- Add an upstream-defined missing target when at least one viable candidate exists; otherwise report `addition deferred` and the models needed to unblock it.

### Antigravity local policy

Treat `google/antigravity-X` as wrapper-equivalent to upstream `X`. Place it before its non-wrapper sibling; keep the sibling immediately after when both are allowlisted.
Count the wrapper as the `google` path provider for diversity. This local policy is not an upstream recommendation.

## Serialization

- Write the resolved chain as one ordered `models` array whose first entry is the primary model and whose remaining entries are the fallbacks.
- Use a bare string for an entry that needs no reasoning level, and `{ "model": "...", "reasoning": "..." }` only when one is needed. Mixed arrays are valid.
- Write `reasoning` only when the selected upstream rung or user request specifies it. Preserve the rung level when substituting its model.
- `reasoning` accepts `off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, or `auto`.
- When a target resolves to a primary with no fallback, write either a single-entry `models` array or `model` with optional `reasoning`. Never write an empty array.
- Never write the `provider/model:level` suffix form when a separate `reasoning` field expresses the same thing.
- Never add unknown settings such as `temperature`, `max_tokens`, or `provider_options` in this skill.

## Apply and validate

Resolve every target before writing. Then apply only the scoped fields, add eligible missing targets, and remove `agents.*.ultrawork`.

Validate all of the following:

- JSON and schema shape are valid.
- Every selected model is in `allowlist`.
- Every selected model is an upstream/runtime match, a documented availability substitution, an explicit allowlisted request, or a `required_providers` exception.
- Upstream gates, provider coverage, chain order, and one-fallback-per-provider all hold.
- No target is degraded to an arbitrary or newly empty chain.
- No deprecated routing field (`variant`, `reasoningEffort`, `fallback_models`) remains in a written target.
- Every added target exists upstream and contains only legal routing fields.
- Every `agents.*.ultrawork` block is gone.
- All non-target data and formatting remain unchanged.

**MANDATORY CHECK:** Justify every provider or model absent from the target's exact chain.
Name the version-near, role, tier, explicit-request, or required-provider reason.
Remove it when no such justification exists.

## Report

| Item | Action | Primary | Reasoning | Fallbacks | Reason |
|------|--------|---------|-----------|-----------|--------|

Use only `MODIFIED`, `ADDED`, `UNCHANGED`, `SKIPPED`, `DEFERRED`, `ULTRAWORK_REMOVED`, or `FIELD_MIGRATED`.
Use `FIELD_MIGRATED` when a target kept its routing values but moved off a deprecated field.
Flag substitutions by type, coverage exceptions or gaps, user divergence warnings, deferred targets, upstream-over-local conflicts, and every added target.
For each addition, confirm the name exists upstream and give its full chain rationale.
Distinguish exact, runtime fuzzy/transformed, version-near, Antigravity wrapper, general availability substitution, and provider-coverage results.

## External sync

After reporting, find separate non-project `oh-my-openagent.json` files. If any exist, ask:

> Found a separate oh-my-openagent config outside this project.
> Would you like to apply the same model changes there too?

**NEVER sync an external config without explicit confirmation.** On confirmation, apply this same authority, allowlist, scope, validation, and reporting process to each approved file.
Do not call the project target an external sync target; if no external config exists, say nothing.
