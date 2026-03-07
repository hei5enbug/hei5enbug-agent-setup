# OmO Model Configurator (GitHub-First)

Expert at oh-my-opencode model config. Updates only `model`, `variant`, `fallback_models` in agents/categories of `oh-my-opencode.json`. GitHub guidance takes priority.

## Scope

**Inputs**: this file, `available-models.json` (allowlist + tiers), `oh-my-opencode.json` (target).

| Constraint | Rule |
|---|---|
| Priority | GitHub links > local files on conflict |
| Local files | Secondary snapshots for compatibility/availability |
| No generation | Do not create extra local files from external content |
| Edit target | `oh-my-opencode.json` only |
| Editable fields | `agents.*.{model,variant,fallback_models}`, `categories.*.{model,variant,fallback_models}` |
| Forbidden edits | All other keys (hooks, root-level fields, etc.) |

## Step 1: Read Inputs

1. Fetch GitHub references first (primary authority):
   - https://github.com/code-yeongyu/oh-my-opencode/blob/dev/docs/guide/agent-model-matching.md
   - https://github.com/code-yeongyu/oh-my-opencode/blob/dev/docs/guide/orchestration.md
   - https://github.com/code-yeongyu/oh-my-opencode/blob/dev/src/shared/model-requirements.ts
   - https://github.com/code-yeongyu/oh-my-openagent/blob/dev/docs/reference/features.md
2. Read `available-models.json` — `allowlist` for availability, `tiers` for model pools.
3. Read `oh-my-opencode.json`.
4. Apply user constraints from prompt.
5. Local rules apply only when GitHub guides lack coverage.

## Step 2: Local Rules

### 2a. Availability gate

- Every target/fallback model MUST ∈ `available-models.json` `allowlist`.
- Unavailable → substitute with next valid candidate per GitHub rules.
- Non-target fields unchanged.

### 2b. Provider diversity gate

Every `fallback_models` array (per agent or category) MUST include exactly one model from each provider listed in `available-models.json` `required_fallback_providers`.

1. Read `required_fallback_providers` from `available-models.json`.
2. For each agent/category, verify its `fallback_models` contains exactly one model from each required provider.
3. If a required provider is missing → append the highest-ranked available model from that provider (prefer same-tier, then adjacent tier).
4. If a required provider's model is already used as the primary `model`, the provider requirement is satisfied — do not duplicate in `fallback_models`.
5. Provider diversity is checked AFTER 2a (availability).
6. GitHub references may mark certain models as **dangerous** or **forbidden** for specific agents. Never use a forbidden model to satisfy provider diversity — skip that provider for that agent.

## Step 3: Apply

1. Resolve models, variants, fallbacks from Step 1 GitHub guides.
2. Filter through 2a availability gate.
3. Apply 2b provider diversity gate to all agents/categories.
4. Write only `{model,variant,fallback_models}` fields.
5. Preserve everything else.

## Step 4: Validate

1. JSON syntax valid.
2. All models/fallbacks ∈ `allowlist`.
3. No dangerous overrides.
4. `runtime_fallback` still `true`.
5. Non-target fields unchanged.
6. Provider diversity: every agent/category covers all providers from `required_fallback_providers`.

## Step 5: Report

```
| Item | Model | Variant | Fallbacks | Reason |
|------|-------|---------|-----------|--------|
```

Flag: substitutions from unavailable models · unresolved shortages · GitHub rules prioritized over local.
