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
├── standalone-skills/
│   ├── omo-model-config/
│   └── portable-opencode-setup/
└── skills/
    ├── deep-interview/
    ├── flowchart-design/
    ├── humanize-korean/
    ├── markdown-to-confluence/
    ├── skill-builder/
    ├── suggest-commit/
    ├── technical-design-writer/
    └── tiki-taka/
```

每个文件夹都包含自己的 `SKILL.md` 以及所需的参考资料或脚本。
插件只发现 `skills/`，不会发现 `standalone-skills/`。

## Skill 列表

| Skill | 作用 |
|---|---|
| [`deep-interview`](skills/deep-interview/SKILL.md) | 进行苏格拉底式访谈，每次回答后都为需求的模糊程度打分，只有分数降到阈值以下才会进入执行阶段。 |
| [`flowchart-design`](skills/flowchart-design/SKILL.md) | 一套通用的流程图设计标准，无论用 SVG、HTML/CSS、Figma 还是 draw.io 制作,都能呈现为同一套设计体系。 |
| [`humanize-korean`](skills/humanize-korean/SKILL.md) | 在不改变内容的前提下，把带有 AI 痕迹的韩语文本改写成自然、像人写的韩语。 |
| [`markdown-to-confluence`](skills/markdown-to-confluence/SKILL.md) | 将 Markdown 文档发布为 Confluence 页面，并在后续修改中保持目录宏、正文图片、附件以及渲染为图片的图表正确显示。 |
| [`skill-builder`](skills/skill-builder/SKILL.md) | 通过“起草 → 测试 → 审查 → 改进”的循环来创建、验证并打包 agent skill。 |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | 读取当前 diff 和最近的提交历史，给出 5 条符合本仓库风格的 commit message 建议。 |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | 编写或整理开发设计文档时遵循的规则，以及逐步收窄目录的 5 步流程。 |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | 让当前 agent 与对面的 Claude/Codex 会话进行有轮次限制的辩论，揭示并收敛争议点。 |

## 相关链接

- [`omo-model-config`](standalone-skills/omo-model-config/SKILL.md) 和
  [`portable-opencode-setup`](standalone-skills/portable-opencode-setup/SKILL.md) 仍作为独立源码保留，
  不包含在插件 skill 列表中。
- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — 独立 OpenCode skill 所配置的插件系统
