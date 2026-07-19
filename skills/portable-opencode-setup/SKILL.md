---
name: portable-opencode-setup
description: Adds missing pieces of the custom opencode/oh-my-openagent configuration on any machine while preserving existing settings, except that it removes only agents.*.ultrawork from the target oh-my-openagent.json. Resolves model recommendations exclusively from the live upstream dev branch. Covers plugins, MCPs, AAI apps, provider models, agent/category routing, team mode, and backups. Does not embed secrets.
---

# Portable OpenCode Setup

Add the missing pieces of this custom opencode and oh-my-openagent configuration on any machine without overwriting the machine's existing setup.

## When to Use

- Setting up a new development machine.
- Sharing this configuration with another user.
- Recovering from a clean install.

## Prerequisites

- opencode CLI installed.
- oh-my-openagent plugin installed.

## Additive-Only Policy

- Preserve all existing OpenCode and oh-my-openagent settings by default.
- Add only plugins, MCPs, AAI apps, provider models, agents, categories, and settings that are missing.
- Merge arrays and maps with de-duplication; do not replace whole arrays or objects.
- Do not overwrite existing agent/category `model`, `variant`, or `fallback_models` values. If they differ from the live upstream `dev` recommendation, preserve them and report the difference as a conflict for manual review.
- Do not overwrite scalar settings such as `team_mode.*` or `runtime_fallback` if they already exist. Add only missing scalar keys.
- The only removal exception is every `agents.*.ultrawork` block inside the target
  `oh-my-openagent.json`. Do not remove similarly named keys or anything from another file.
- Before changing a target file, create a timestamped backup of only that file. Do not copy unrelated backup files as part of setup.

## Step 1: Install Plugins

Install only missing opencode plugins listed in `setup-manifest.json` under the `plugins` array. Leave already installed plugins untouched.
TUI plugins are intentionally out of scope for this portable setup.

```bash
# Example (install all server plugins from the manifest)
opencode plugin add opencode-claude-auth
opencode plugin add opencode-antigravity-auth
opencode plugin add @datadog/opencode-plugin
opencode plugin add oh-my-openagent
```

## Step 2: Configure MCPs

### Always-On MCPs
Enable any missing MCPs listed in `setup-manifest.json` under `mcps.always_on`. Each entry must include a concrete OpenCode MCP definition, not only `{ "enabled": true }`.
For local stdio MCPs, use OpenCode's local MCP shape:

```json
{
  "type": "local",
  "command": ["npx", "-y", "package-name"],
  "environment": {},
  "enabled": true
}
```

Merge MCP entries additively: add missing keys to incomplete entries, preserve unrelated existing environment variables, and do not remove, disable, or rewrite existing MCP entries unless they conflict with the AAI Gateway on-demand rule below.

Current direct MCP commands from `setup-manifest.json`:

| MCP | Command | Notes |
|-----|---------|-------|
| `context7` | `npx -y @upstash/context7-mcp` | Documentation retrieval. |
| `grep_app` | `npx -y @kenkaiiii/kencode-search` | grep.app-style code search replacement. |
| `aai-gateway` | `npx -y aai-gateway` | Gateway for on-demand Agent Apps. |

Do not add a separate `websearch` MCP from this skill. Treat web search as provided by the target machine's OpenCode installation unless the user explicitly asks for an additional web-search MCP.

Do not directly register the AAI Gateway app MCPs (`github-mcp`, `azure-devops-mcp`, `atlassian-rovo`, `postman-mcp`) as OpenCode MCPs. Keep them available only through the AAI Gateway on-demand app list so their tool schemas are loaded only when needed instead of being exposed on every prompt.

## Step 3: Configure AAI Apps

### Preset Apps (Auto-Registered)
Ensure all preset apps listed in `setup-manifest.json` under `aai_apps.preset` are available. Do not remove existing preset apps.
Treat these as discovery checks: if `opencode`, `codex`, or `claude` is not installed on the target machine, report it as unavailable instead of installing unrelated CLIs automatically.

### On-Demand Apps
Register only missing on-demand apps listed in `setup-manifest.json` under `aai_apps.on_demand` through AAI Gateway. After `aai-gateway` is connected, use AAI Gateway tools such as `search:discover` and `mcp:import` to search for the latest version, install it, and register it with AAI Gateway.
These apps should not also be configured as direct OpenCode MCPs unless a specific machine needs direct, always-visible tool access.

## Step 4: Configure Provider Models

Under `provider.google`, add only missing Antigravity/Gemini custom models required by the live
upstream model routes resolved in Step 5. Preserve any existing provider models, aliases,
credentials, and provider-specific settings. Build the availability set from the target machine's
OpenCode model discovery, installed provider capabilities, and existing provider configuration;
use only those target-machine sources. Report an upstream-recommended model that the target
provider does not confirm instead of guessing a replacement. If provider authentication is
needed for discovery, defer this model step until after Step 6 and retry it then. If the live
upstream sources cannot be fetched, skip this step; never use a local or cached
model-recommendation snapshot as a fallback.

## Step 5: Configure Oh My OpenAgent

Fetch the following files from the current GitHub `dev` branch of
`code-yeongyu/oh-my-openagent` on every run:

- `packages/model-core/src/agent-model-requirements.ts`
- `packages/model-core/src/category-model-requirements.ts`
- `packages/model-core/src/model-requirement-types.ts`
- `src/config/schema/fallback-models.ts`
- `src/config/schema/agent-overrides.ts`
- `src/config/schema/categories.ts`

The live TypeScript code is the only authority for model recommendations and model-related entry
shape. Do not fall back to a checked-in model-routing example, cache, previous run, generated
output, or prose documentation. If the live source cannot be fetched, make no provider-model or
agent/category model-routing additions; continue only the independent setup steps, remove
`agents.*.ultrawork`, and report the deferred model work.

### Deterministic Model Mapping

Resolve every missing entry and every comparison with the same rules:

1. Evaluate the live upstream gate flags exactly as the current TypeScript code defines them.
   If a gate cannot be evaluated on the target machine, defer that entry and report why.
2. Preserve the live `fallbackChain` order and keep only entries whose model the target machine's
   provider discovery or existing configuration confirms as available. Do not invent or
   substitute a model that is absent from the live chain.
3. Use the first viable chain entry as `model` and copy its `variant` to the sibling `variant`
   field when present.
4. Serialize the remaining viable entries as `fallback_models` in their original order. Use a
   string when an entry has no variant and `{ "model": "...", "variant": "..." }` when it does.
5. If no viable entry remains, do not create the missing agent/category. Report it as deferred.
6. Use this resolved result only to add a missing entry or compare with an existing one. Never
   overwrite an existing entry's model fields.

### Agents
Enumerate the agent names defined by the live `AGENT_MODEL_REQUIREMENTS`. For a missing agent, add
only the resolved live recommendation's `model`, optional `variant`, and `fallback_models`, after
checking target-machine availability. For an existing agent, preserve its current model fields;
when they differ from the live recommendation, report the difference instead of overwriting it.

### Categories
Enumerate the category names defined by the live `CATEGORY_MODEL_REQUIREMENTS`. For a missing
category, add only the live recommendation's `model`, optional `variant`, and `fallback_models`,
after checking target-machine availability. For an existing category, preserve its current model
fields; when they differ from the live recommendation, report the difference instead of
overwriting it.

### Obsolete Ultrawork Cleanup

Remove every `agents.*.ultrawork` block found inside the target `oh-my-openagent.json`, including
blocks on agents whose model values are preserved. Remove no other key and touch no other file for
this cleanup.

### Global Settings
Add these top-level keys only when they are missing. Preserve existing values and report differences instead of overwriting them:

| Key | Value |
|-----|-------|
| `team_mode.enabled` | `true` |
| `team_mode.max_parallel` | `3` |
| `team_mode.max_total` | `5` |
| `team_mode.timeout_minutes` | `60` |
| `team_mode.visualization` | `tmux` |
| `runtime_fallback` | `true` |
| `disabled_hooks` | `["no-sisyphus-gpt"]` |

## Step 6: Auth State

Do **not** copy `antigravity-accounts.json` or any other auth token file. On the new machine, run the antigravity login flow to regenerate the auth state:

```bash
opencode auth antigravity
```

Verify that `antigravity-accounts.json` is created in the expected config directory.
If model discovery was deferred for authentication, retry Steps 4 and 5 after login.

## Step 7: Backups

Before modifying any target file, create a timestamped backup next to that file. Back up only files this skill will change, such as `opencode.json` and `oh-my-openagent.json`; do not copy unrelated backup files from this repository or overwrite existing backups.

## Validation Checklist

- [ ] All plugins from Step 1 are installed.
- [ ] Always-on MCPs have `type: "local"`, executable `command` arrays, and are connected in `opencode mcp list`.
- [ ] AAI app MCPs are not directly registered as OpenCode MCPs.
- [ ] AAI preset and on-demand apps are listed in AAI Gateway.
- [ ] `provider.google` contains the missing custom models while preserving existing provider settings.
- [ ] Model availability was resolved only from the target machine's discovery and configuration.
- [ ] Every added model route follows the live `fallbackChain` order and deterministic serialization rules.
- [ ] Missing live-upstream agents/categories and configured settings have been added without overwriting existing values.
- [ ] Existing model values that differ from live upstream are preserved and reported as conflicts for manual review.
- [ ] Every `agents.*.ultrawork` block is absent from the target `oh-my-openagent.json`; no unrelated key was removed.
- [ ] The report identifies the exact upstream branch and fetch time used for model recommendations.
- [ ] `antigravity-accounts.json` exists on the new machine after fresh login.
- [ ] Backups are copied if applicable.

## Constraints

- **No secrets.** Never embed `antigravity-accounts.json`, API keys, tokens, or credentials in this skill or any committed file.
- **Read-only repository inputs.** Do not edit `setup-manifest.json` or the checked-in
  `oh-my-openagent.json` during setup reproduction. The manifest defines non-model setup items;
  only the live upstream `dev` code defines model recommendations, and the target machine defines
  local model availability.
- **Machine-specific paths.** Use the new machine's actual config directory paths when copying files.
- **No implicit overwrites.** Existing settings may be augmented but not replaced unless the user explicitly asks for overwrite or restore behavior.
