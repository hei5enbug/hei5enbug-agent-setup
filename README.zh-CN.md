# hei5enbug-agent-setup

[English](./README.md) | [한국어](./README.ko.md) | [日本語](./README.ja.md) | **简体中文** | [Español](./README.es.md) | [Deutsch](./README.de.md) | [Français](./README.fr.md)

面向 AI 编程 agent 的自定义 skill 合集，设计为可在多个 agent host 之间直接共享，无需针对每个 host 重写。

## 概述

插件包含的每个 skill 都位于 `skills/` 下，指令、参考资料和脚本都放在一起。
插件不包含的 skill 位于 `standalone-skills/` 下。
同一份 `SKILL.md` 在所有支持的 host 上都能原样运行，无需修改。

## 支持的 Host

- Claude Code
- Codex
- OpenCode（通过 [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) 插件）

## 结构

```
hei5enbug-agent-setup/
├── .agents/plugins/marketplace.json
├── .claude-plugin/
│   ├── marketplace.json
│   └── plugin.json
├── .codex-plugin/plugin.json
├── .github/workflows/validate.yml
├── LICENSE
├── pyproject.toml
├── standalone-agents/
│   ├── scout.md
│   └── codex-explorer.toml
├── standalone-skills/
│   └── omo-model-config/
└── skills/
    ├── decision-navigator/
    ├── deep-interview/
    ├── flowchart-design/
    ├── humanize-korean/
    ├── markdown-to-confluence/
    ├── skill-builder/
    ├── suggest-commit/
    ├── technical-design-writer/
    └── tiki-taka/
```

每个插件 skill 文件夹都包含自己的 `SKILL.md` 以及所需的参考资料或脚本。
插件清单为 Codex 和 Claude Code 打包同一个 `skills/` 目录，不会把 skill 复制到 host 专用目录。
`standalone-skills/` 目录不在任何一个插件的 skill 发现路径中。

`standalone-agents/` 目录存放 `CLAUDE.md` 和 `AGENTS.md` 按名称引用的子 agent 定义。
请手动把 `scout.md` 复制到 `~/.claude/agents/`；把 `codex-explorer.toml` 复制为 `~/.codex/agents/explorer.toml`。
它会覆盖 Codex 内置的 `explorer`，固定其推理强度和只读沙箱。它不指定模型，因此沿用 host 的默认模型，
这与 Claude Code 上固定单一模型的 `scout` 不同。
它们放在插件包之外，所以安装插件不会新增任何子 agent。

## 安装插件

从 GitHub 仓库安装一次即可。

### Codex

```bash
codex plugin marketplace add hei5enbug/hei5enbug-agent-setup --ref main
codex plugin add hei5enbug-agent-setup@hei5enbug
```

### Claude Code

```bash
claude plugin marketplace add hei5enbug/hei5enbug-agent-setup
claude plugin install hei5enbug-agent-setup@hei5enbug
```

## 更新插件

两个插件清单和 `pyproject.toml` 使用同一个语义化版本，当前为 `0.2.0`。发布新版本前，先让下面的开发检查全部通过，
再同时提升 `.codex-plugin/plugin.json`、`.claude-plugin/plugin.json` 和 `pyproject.toml` 中的版本号。

版本发布后更新 Codex：

```bash
codex plugin marketplace upgrade hei5enbug
codex plugin add hei5enbug-agent-setup@hei5enbug
```

版本发布后更新 Claude Code：

```bash
claude plugin marketplace update hei5enbug
claude plugin update hei5enbug-agent-setup@hei5enbug
```

更新后请开启新的 Codex 线程或重启 Claude Code，以便 host 加载新的 skill 版本。

## 开发检查

内置脚本需要安装了 PyYAML 的 Python 3.12 或更高版本，Node 测试需要 Node.js。
用同样的命令运行 `.github/workflows/validate.yml` 在 macOS 和 Linux 上执行的三项检查：

```bash
python3 -m pip install -e ".[dev]"
for skill in skills/*/ standalone-skills/*/; do python3 skills/skill-builder/scripts/quick_validate.py "$skill"; done
python3 -m pytest
node --test skills/markdown-to-confluence/tests/test_render_diagrams.mjs
```

## 指令语言

agent 执行的 skill 指令用英文编写。skill 目录中的 `README.ko.md` 是与对应英文文档保持同步的非权威韩文翻译，
仅供人阅读，agent 在执行 skill 时不得加载或使用它。可执行文件中只在韩文本身就是目标数据时保留韩文，
例如触发短语、示例、必需的输出标签或评估数据。

## Skill 列表

| Skill | 作用 |
|---|---|
| [`decision-navigator`](skills/decision-navigator/SKILL.md) | 把跨多个会话的工作拆成决策工单，并逐个解决，直到实现路线清晰。 |
| [`deep-interview`](skills/deep-interview/SKILL.md) | 进行苏格拉底式访谈，每次回答后都为需求的模糊程度打分，只有分数降到阈值以下才会进入执行阶段。[韩文指南](skills/deep-interview/README.ko.md) |
| [`flowchart-design`](skills/flowchart-design/SKILL.md) | 一套通用的流程图设计标准，无论用 SVG、HTML/CSS、Figma 还是 draw.io 制作，都能呈现为同一套设计体系。 |
| [`humanize-korean`](skills/humanize-korean/SKILL.md) | 在不改变内容的前提下，把带有 AI 痕迹的韩语文本改写成自然、像人写的韩语。[韩文指南](skills/humanize-korean/README.ko.md) |
| [`markdown-to-confluence`](skills/markdown-to-confluence/SKILL.md) | 将 Markdown 文档发布为 Confluence 页面，并在后续修改中保持目录宏、正文图片、附件以及渲染为图片的图表正确显示。 |
| [`skill-builder`](skills/skill-builder/SKILL.md) | 通过“起草 → 测试 → 审查 → 改进”的循环来创建、验证并打包 agent skill。 |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | 一并读取已暂存和未暂存的变更，或你指定的范围，结合最近的提交历史，给出 5 条符合本仓库风格的 commit message 建议。 |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | 编写或整理开发设计文档时遵循的规则，以及逐步收窄目录的 5 步流程。[韩文指南](skills/technical-design-writer/README.ko.md) |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | 让当前 agent 与对面的 Claude/Codex 会话进行有轮次限制的辩论，揭示并收敛争议点。[韩文指南](skills/tiki-taka/README.ko.md) |

## 相关链接

- [`omo-model-config`](standalone-skills/omo-model-config/SKILL.md) 仍作为独立源码保留，
  不包含在插件 skill 列表中。
- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — 由该独立 skill 更新其模型路由的插件系统

## 许可证

本仓库采用 Apache License 2.0 授权。全文见 [`LICENSE`](./LICENSE)。
