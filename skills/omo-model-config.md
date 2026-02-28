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
2. Read `available-models.json` — `allowlist` for availability, `tiers` for model pools.
3. Read `oh-my-opencode.json`.
4. Apply user constraints from prompt.
5. Local rules apply only when GitHub guides lack coverage.

## Step 2: Local Rules

### 2a. Availability gate

- Every target/fallback model MUST ∈ `available-models.json` `allowlist`.
- Unavailable → substitute with next valid candidate per GitHub rules.
- Non-target fields unchanged.

### 2b. Lightweight model selection

**Lightweight slots** = agents/categories whose primary `model` ∈ `tiers.lightweight`.

At each run:
1. Web-search current benchmarks, pricing, cost-efficiency for all `tiers.lightweight` models as of today.
2. Rank by quality-per-cost.
3. Top-ranked → primary for all lightweight slots; remainder → fallbacks in rank order.
4. If top-ranked fails 2a gate, promote next.

## Step 3: Apply

1. Resolve models, variants, fallbacks from Step 1 GitHub guides.
2. Filter through 2a availability gate.
3. Lightweight slots → apply 2b selection.
4. Write only `{model,variant,fallback_models}` fields.
5. Preserve everything else.

## Step 4: Validate

1. JSON syntax valid.
2. All models/fallbacks ∈ `allowlist`.
3. No dangerous overrides.
4. `runtime_fallback` still `true`.
5. Lightweight slots reflect 2b ranking.
6. Non-target fields unchanged.

## Step 5: Report

```
| Item | Model | Variant | Fallbacks | Reason |
|------|-------|---------|-----------|--------|
```

Flag: substitutions from unavailable models · unresolved shortages · GitHub rules prioritized over local.
