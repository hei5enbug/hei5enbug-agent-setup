# hei5enbug-agent-setup

**English** | [한국어](./README.ko.md) | [日本語](./README.ja.md) | [简体中文](./README.zh-CN.md) | [Español](./README.es.md) | [Deutsch](./README.de.md) | [Français](./README.fr.md)

Model and variant configuration for an AI agent harness, assigned to match each agent's role.

## Overview

Each agent in a harness requires different capabilities. This configuration optimizes `model`, `variant`, and fallback chains per agent role and task category.

## Supported Tools

- [OpenCode](https://github.com/code-yeongyu/oh-my-openagent) (via [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) plugin)

## Structure

```
hei5enbug-agent-setup/
├── oh-my-openagent.json       # Config file read and modified by the skill
├── available-models.json     # Allowlist used by the skill to validate model changes
└── .opencode/
    └── skills/
        └── omo-model-config/ # Custom skill for safe config editing
            └── SKILL.md
```

## Custom Skills

### omo-model-config

A workflow for safely editing agent model assignments. It applies the following rules:

- **GitHub-first resolution** — upstream [oh-my-openagent](https://github.com/code-yeongyu/oh-my-openagent) docs are the primary authority for model-role matching
- **Availability gate** — every model must be in the `available-models.json` allowlist
- **Provider diversity gate** — required providers must be covered in each agent's fallback chain
- **Scoped editing** — only `model`, `variant`, and `fallback_models` fields are modified; everything else is preserved

See [`.opencode/skills/omo-model-config/SKILL.md`](.opencode/skills/omo-model-config/SKILL.md) for details.

## Usage

Open as a project root in a supported agent tool. The configuration is loaded automatically on session start.

```bash
cd hei5enbug-agent-setup
opencode
```

### Updating Model Assignments

Invoke the `omo-model-config` skill from within the agent session:

```
/omo-model-config
```

Or ask the agent directly:

```
"Oracle의 primary model을 claude-opus-4-6으로 변경해줘"
"Librarian fallback에 gpt-5.4 추가해줘"
```

The skill validates changes against the allowlist and ensures provider diversity rules are met before applying.

## Settings

| Key | Value | Description |
|---|---|---|
| `runtime_fallback` | `true` | Automatically falls back to the next model if the primary is unavailable |
| `disabled_hooks` | `["no-sisyphus-gpt"]` | Allows GPT models to be used by the Sisyphus agent |

## Related

- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — plugin system powering the configuration
- [oh-my-openagent docs](https://github.com/code-yeongyu/oh-my-openagent) — upstream documentation and model-matching guides
