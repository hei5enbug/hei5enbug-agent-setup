---
name: portable-opencode-setup
description: Adds missing pieces of the custom opencode/oh-my-openagent configuration on any machine while preserving existing settings. Covers plugins, MCPs, AAI apps, provider models, agent/category routing, team mode, and backups. Does not embed secrets.
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
- Do not overwrite existing agent/category `model`, `variant`, or `fallback_models` values. If they differ from this repository's source file, report the difference as a conflict for manual review.
- Do not overwrite scalar settings such as `team_mode.*` or `runtime_fallback` if they already exist. Add only missing scalar keys.
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

Under `provider.google`, add only missing Antigravity/Gemini custom models used in this environment. Preserve any existing provider models, aliases, credentials, and provider-specific settings. Use `skills/omo-model-config/available-models.json` as the local allowlist and report any desired model that is absent from that file instead of guessing a replacement.

## Step 5: Configure Oh My OpenAgent

Use the `oh-my-openagent.json` from this repository (`skills/omo-model-config/oh-my-openagent.json`) as the reference for missing entries. It is not an overwrite template.

### Agents
Ensure the following agents exist. For missing agents, add the full definition from the source file. For existing agents, preserve their current `model`, `variant`, and `fallback_models`; if they differ from the source file, report the difference instead of overwriting it:

- `sisyphus`
- `hephaestus`
- `oracle`
- `librarian`
- `explore`
- `multimodal-looker`
- `prometheus`
- `metis`
- `momus`
- `atlas`
- `sisyphus-junior`

### Categories
Ensure the following categories exist. For missing categories, add the full definition from the source file. For existing categories, preserve their current `model`, `variant`, and `fallback_models`; if they differ from the source file, report the difference instead of overwriting it:

- `visual-engineering`
- `ultrabrain`
- `deep`
- `artistry`
- `quick`
- `unspecified-low`
- `unspecified-high`
- `writing`

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

## Step 7: Backups

Before modifying any target file, create a timestamped backup next to that file. Back up only files this skill will change, such as `opencode.json` and `oh-my-openagent.json`; do not copy unrelated backup files from this repository or overwrite existing backups.

## Validation Checklist

- [ ] All plugins from Step 1 are installed.
- [ ] Always-on MCPs have `type: "local"`, executable `command` arrays, and are connected in `opencode mcp list`.
- [ ] AAI app MCPs are not directly registered as OpenCode MCPs.
- [ ] AAI preset and on-demand apps are listed in AAI Gateway.
- [ ] `provider.google` contains the missing custom models while preserving existing provider settings.
- [ ] Missing agents/categories/settings from this repository have been added without overwriting existing values.
- [ ] Any source-vs-existing differences are reported as conflicts for manual review.
- [ ] `antigravity-accounts.json` exists on the new machine after fresh login.
- [ ] Backups are copied if applicable.

## Constraints

- **No secrets.** Never embed `antigravity-accounts.json`, API keys, tokens, or credentials in this skill or any committed file.
- **Read-only source files.** The JSON files in this repository (`oh-my-openagent.json`, `available-models.json`) are the source of truth. Do not edit them during setup reproduction.
- **Machine-specific paths.** Use the new machine's actual config directory paths when copying files.
- **No implicit overwrites.** Existing settings may be augmented but not replaced unless the user explicitly asks for overwrite or restore behavior.
