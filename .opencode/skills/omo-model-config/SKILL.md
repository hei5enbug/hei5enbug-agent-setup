# OmO Model Configurator (GitHub-First)

Updates only `model`, `variant`, and `fallback_models` under `agents.*` and `categories.*` in `oh-my-opencode.json`.

## Scope

**Inputs**:
- This file
- `available-models.json` (`allowlist`, `tiers`, `required_fallback_providers`)
- `oh-my-opencode.json` (edit target)

**Core constraints**:
- GitHub references are primary authority. On conflict: GitHub > local rules.
- Edit only `oh-my-opencode.json`.
- Edit only `agents.*.{model,variant,fallback_models}` and `categories.*.{model,variant,fallback_models}`.
- Do not change any other keys.

## Step 1: Read and Resolve

1. Read GitHub references first:
   - https://github.com/code-yeongyu/oh-my-openagent/blob/dev/docs/guide/agent-model-matching.md
   - https://github.com/code-yeongyu/oh-my-openagent/blob/dev/docs/guide/orchestration.md
   - https://github.com/code-yeongyu/oh-my-openagent/blob/dev/src/shared/model-requirements.ts
   - https://github.com/code-yeongyu/oh-my-openagent/blob/dev/docs/reference/features.md#agents
   - https://github.com/code-yeongyu/oh-my-openagent/blob/dev/docs/reference/features.md#category-system
2. Read `available-models.json`.
3. Read `oh-my-opencode.json`.
4. Apply user constraints from prompt.

## Step 2: Local Gates (only when not overridden by GitHub)

### 2a) Availability gate

- Every primary/fallback model must be in `allowlist`.
- If unavailable, replace with next valid candidate that satisfies GitHub guidance.

### 2b) Provider diversity gate

For each agent/category, required providers come from `required_fallback_providers`.

- A provider is considered covered if it appears in either the primary `model` or `fallback_models`.
- In `fallback_models`, keep at most one model per provider (no duplicates).
- If a required provider is uncovered, add the best-fit available model for that agent/category role from that provider, using GitHub role guidance first; if multiple candidates remain, prefer same tier, then adjacent tier.
- If GitHub marks provider models as forbidden/dangerous for that target, skip that provider and report it.

## Step 3: Apply Changes

1. Resolve target `model`, `variant`, `fallback_models` from GitHub guidance and user constraints.
2. Apply availability gate.
3. Apply provider diversity gate.
4. Write only allowed fields; preserve everything else.

## Step 4: Validate

1. JSON is valid.
2. All chosen models are in `allowlist`.
3. No GitHub-forbidden model is selected.
4. Non-target fields are unchanged (including existing root settings such as `runtime_fallback`).
5. Provider coverage is satisfied, or explicitly reported when impossible due to forbidden/unavailable models.
6. Added provider models include role-fit rationale when chosen from multiple candidates.

## Step 5: Report

```
| Item | Model | Variant | Fallbacks | Reason |
|------|-------|---------|-----------|--------|
```

Always flag:
- Substitutions caused by availability limits
- Missing provider coverage and why it was impossible
- Cases where GitHub guidance overrode local assumptions
- Role-fit reasoning when provider models were added
