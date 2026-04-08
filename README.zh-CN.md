# hei5enbug-agent-setup

[English](./README.md) | [한국어](./README.ko.md) | [日本語](./README.ja.md) | **简体中文** | [Español](./README.es.md) | [Deutsch](./README.de.md) | [Français](./README.fr.md)

为 AI agent harness 中每个 agent 的角色分配最适合的模型和 variant 的配置。

## 概述

harness 中的每个 agent 所需的能力各不相同。此配置根据 agent 角色和任务类别优化 `model`、`variant` 和回退链。

## 支持工具

- [OpenCode](https://github.com/code-yeongyu/oh-my-openagent)（通过 [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) 插件）

## 结构

```
hei5enbug-agent-setup/
├── oh-my-openagent.json       # skill 读取和修改的配置文件
├── available-models.json     # skill 验证模型变更时使用的 allowlist
└── .opencode/
    └── skills/
        └── omo-model-config/ # 安全编辑配置的自定义 skill
            └── SKILL.md
```

## 自定义 Skill

### omo-model-config

安全编辑 agent 模型分配的工作流。应用以下规则：

- **GitHub 优先解析** — 上游 [oh-my-openagent](https://github.com/code-yeongyu/oh-my-openagent) 文档是模型-角色匹配的主要依据
- **可用性门控** — 所有模型必须存在于 `available-models.json` 的 allowlist 中
- **供应商多样性门控** — 每个 agent 的回退链中必须包含必需的供应商
- **编辑范围限制** — 仅修改 `model`、`variant`、`fallback_models` 字段，其余保持不变

详情请参阅 [`.opencode/skills/omo-model-config/SKILL.md`](.opencode/skills/omo-model-config/SKILL.md)。

## 使用方法

在支持的 agent 工具中作为项目根目录打开即可。会话启动时配置会自动加载。

```bash
cd hei5enbug-agent-setup
opencode
```

### 变更模型分配

在 agent 会话中调用 `omo-model-config` skill：

```
/omo-model-config
```

或直接向 agent 提出请求：

```
"把 Oracle 的 primary model 改成 claude-opus-4-6"
"给 Librarian 的 fallback 添加 gpt-5.4"
```

skill 会对照 allowlist 验证变更，并在确认供应商多样性规则后生效。

## 设置

| 键 | 值 | 说明 |
|---|---|---|
| `runtime_fallback` | `true` | 主模型不可用时自动回退到下一个模型 |
| `disabled_hooks` | `["no-sisyphus-gpt"]` | 允许 Sisyphus agent 使用 GPT 模型 |

## 相关链接

- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — 驱动此配置的插件系统
- [oh-my-openagent docs](https://github.com/code-yeongyu/oh-my-openagent) — 上游文档及模型匹配指南
