# Oh My OpenCode Model Configurator (GitHub-First)

You are an expert at configuring oh-my-opencode model assignments.
Your job is to update `oh-my-opencode.json` using official oh-my-opencode GitHub guidance first.

---

## Scope (Hard Constraint)

Use these 3 local files as working inputs:

1. `skills/omo-model-config.md` (this rule file)
2. `available-models.json` (allowlist and tier metadata)
3. `oh-my-opencode.json` (target config)

GitHub-first constraints:
- Always prioritize official oh-my-opencode GitHub links/rules when there is any conflict.
- Treat local files as secondary snapshots for compatibility and availability checks.
- GitHub references are read-only: do not generate extra local files from external content.
- Keep edits focused on `oh-my-opencode.json` (and only required direct updates requested by the user).

---

## Step 1: Read Inputs (GitHub First)

1. Check these official oh-my-opencode GitHub guides first and treat them as primary references:
   - https://github.com/code-yeongyu/oh-my-opencode/blob/dev/docs/guide/agent-model-matching.md
   - https://github.com/code-yeongyu/oh-my-opencode/blob/dev/docs/guide/orchestration.md
2. Read `available-models.json`.
   - Use `allowlist` for model availability checks.
   - Use `tiers` for local model-pool metadata.
3. Read current `oh-my-opencode.json`.
4. Apply any user constraints from the prompt.
5. Use local rule text only when these primary GitHub guides do not provide newer/conflicting direction.

---

## Step 2: Local Rules (Baseline Defaults)


### 2a. Local availability gate (agent execution rule)

- MUST validate every selected model and fallback against `available-models.json` `allowlist`.
- If a model is not in the allowlist, treat it as unavailable and substitute it with the next valid candidate from GitHub-prioritized rules.

### 2b. Lightweight model efficiency-priority policy (agent execution rule)

At each run, determine lightweight priority using local config signals only:
1. Higher `background_task.modelConcurrency` value wins.
2. If tie, higher `background_task.providerConcurrency` for that model's provider wins.
3. If still tie, use deterministic order from `available-models.json` `tiers.lightweight` order.

Apply this dynamic order first to lightweight-oriented slots (utility agents and lightweight categories).
If a higher-priority lightweight model is unavailable, move to the next candidate.

---

## Step 3: Apply to `oh-my-opencode.json`

1. Resolve chains, canonical IDs, fallback sets, and explicit variants from the Step 1 GitHub guides.
2. Apply local availability filtering using Section 2a.
3. For lightweight-oriented slots, reorder lightweight candidates by Section 2b before selecting primary/fallback.
4. Enforce safety constraints from the Step 1 GitHub guides.
5. Preserve unrelated valid settings unless conflicting.

---

## Step 4: Validate

1. JSON syntax valid.
2. All selected models and fallbacks exist in `available-models.json` `allowlist`.
3. Dangerous overrides absent.
4. `runtime_fallback` remains `true`.
5. Lightweight-oriented slots reflect Section 2b efficiency-priority order.
6. GitHub-guide-derived decisions are not overridden by stale local duplicates.

---

## Step 5: Report

Return a concise summary table:

```
| Item | Model | Variant | Fallbacks | Reason |
|------|-------|---------|-----------|--------|
```

Also flag:
- substitutions due to unavailable models
- any unresolved shortage caused by allowlist limits
- which GitHub links/rules were prioritized over local snapshots
