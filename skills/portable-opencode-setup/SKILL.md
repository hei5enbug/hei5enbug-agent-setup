---
name: portable-opencode-setup
description: Reproduces the custom opencode/oh-my-openagent configuration on any machine, covering plugins, npm deps, MCPs, AAI apps, provider models, agent/category routing, team mode, and backups. Does not embed secrets.
---

# Portable OpenCode Setup

Reproduce this custom opencode and oh-my-openagent configuration on any machine.

## When to Use

- Setting up a new development machine.
- Sharing this configuration with another user.
- Recovering from a clean install.

## Prerequisites

- opencode CLI installed.
- Node.js and npm available.
- oh-my-openagent plugin installed.

## Step 1: Install Plugins

Install all opencode plugins listed in `setup-manifest.json` under the `plugins` array.

```bash
# Example (install all items from the manifest)
opencode plugin add opencode-claude-auth
opencode plugin add opencode-antigravity-auth
opencode plugin add @datadog/opencode-plugin
opencode plugin add oh-my-openagent
opencode plugin add oh-my-openagent/tui
```

## Step 2: Install NPM Dependencies

Install all npm packages listed in `setup-manifest.json` under the `npm_packages` array.

```bash
# Example (install all items from the manifest)
npm install -g @ex-machina/opencode-anthropic-auth
npm install -g @opencode-ai/plugin
npm install -g oh-my-opencode
```

## Step 3: Configure MCPs

### Always-On MCPs
Enable all MCPs listed in `setup-manifest.json` under `mcps.always_on`.

### Registered-Disabled MCPs
Register all MCPs listed in `setup-manifest.json` under `mcps.registered_disabled`, but leave them disabled by default.

## Step 4: Configure AAI Apps

### Preset Apps (Auto-Registered)
Ensure all preset apps listed in `setup-manifest.json` under `aai_apps.preset` are available.

### On-Demand Apps
Register all on-demand apps listed in `setup-manifest.json` under `aai_apps.on_demand`.

## Step 5: Configure Provider Models

Under `provider.google`, add the **10 Antigravity/Gemini custom models** used in this environment. Refer to the local `available-models.json` or upstream documentation for the exact model identifiers.

## Step 6: Configure Oh My OpenAgent

Use the `oh-my-openagent.json` from this repository (`skills/omo-model-config/oh-my-openagent.json`) as the source of truth.

### Agents
Ensure the following agents have their `model`, `variant`, and `fallback_models` set exactly as defined in the source file:

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
Ensure the following categories have their `model`, `variant`, and `fallback_models` set exactly as defined:

- `visual-engineering`
- `ultrabrain`
- `deep`
- `artistry`
- `quick`
- `unspecified-low`
- `unspecified-high`
- `writing`

### Global Settings
Set these top-level keys:

| Key | Value |
|-----|-------|
| `team_mode.enabled` | `true` |
| `team_mode.max_parallel` | `3` |
| `team_mode.max_total` | `5` |
| `team_mode.timeout_minutes` | `60` |
| `team_mode.visualization` | `tmux` |
| `runtime_fallback` | `true` |
| `disabled_hooks` | `["no-sisyphus-gpt"]` |

## Step 7: Auth State

Do **not** copy `antigravity-accounts.json` or any other auth token file. On the new machine, run the antigravity login flow to regenerate the auth state:

```bash
opencode auth antigravity
```

Verify that `antigravity-accounts.json` is created in the expected config directory.

## Step 8: Backups

If backup files for opencode or oh-my-openagent settings exist in this repository, copy them to the new machine's config directory after completing the steps above. Treat backups as the final restore layer, not the primary setup method.

## Validation Checklist

- [ ] All plugins from Step 1 are installed.
- [ ] All npm packages from Step 2 are installed.
- [ ] Always-on MCPs are connected.
- [ ] Registered-disabled MCPs appear in the config but are disabled.
- [ ] AAI preset and on-demand apps are listed.
- [ ] `provider.google` contains the 10 custom models.
- [ ] `oh-my-openagent.json` matches the source file in this repository.
- [ ] `antigravity-accounts.json` exists on the new machine after fresh login.
- [ ] Backups are copied if applicable.

## Constraints

- **No secrets.** Never embed `antigravity-accounts.json`, API keys, tokens, or credentials in this skill or any committed file.
- **Read-only source files.** The JSON files in this repository (`oh-my-openagent.json`, `available-models.json`) are the source of truth. Do not edit them during setup reproduction.
- **Machine-specific paths.** Use the new machine's actual config directory paths when copying files.
