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
├── AGENTS.md
├── AGENTS.ko.md
├── CLAUDE.md
├── CLAUDE.ko.md
├── hooks/hooks.json
├── instructions/
│   ├── claude-agents.md
│   ├── codex-agents.md
│   ├── confluence.md
│   ├── documentation.md
│   ├── protected-values.md
│   ├── services.md
│   └── session/
│       ├── claude-code.md
│       ├── codex.md
│       └── common.md
├── scripts/
│   ├── agent_guard.py
│   ├── datagrip_guard.py
│   ├── language_guard.py
│   ├── session_approval_guard.py
│   └── session_context.py
├── tests/
├── LICENSE
├── pyproject.toml
├── agents/
│   ├── ko/
│   │   ├── scout.ko.md
│   │   └── worker.ko.md
│   ├── scout.md
│   └── worker.md
├── standalone-agents/
│   ├── codex-scout.toml
│   └── codex-worker.toml
├── standalone-skills/
│   └── omo-model-config/
└── skills/
    ├── decision-navigator/
    ├── deep-interview/
    ├── flowchart-design/
    ├── docs-rewrite/
    ├── document-to-confluence/
    ├── orca-plugin-refresh/
    ├── skill-builder/
    ├── suggest-commit/
    ├── technical-design-writer/
    └── tiki-taka/
```

每个插件 skill 文件夹都包含自己的 `SKILL.md` 以及所需的参考资料或脚本。
插件清单为 Codex 和 Claude Code 打包同一个 `skills/` 目录，不会把 skill 复制到 host 专用目录。
`standalone-skills/` 目录不在任何一个插件的 skill 发现路径中。

`agents/` 目录随 Claude Code 插件一起发布，因此安装插件包会添加 `hei5enbug-agent-setup:scout` 和
`hei5enbug-agent-setup:worker` 子 agent，无需手动复制。清单只列出这两个英文定义，因此 `agents/ko/` 中的韩文译本
不会注册为子 agent。

Codex 只在 `~/.codex/agents/` 和 `.codex/agents/` 中查找子 agent，插件无法注册。
因此，会话钩子仅在 `~/.codex/agents/scout.toml` 和 `~/.codex/agents/worker.toml` 各自不存在时，把
`standalone-agents/codex-scout.toml` 和 `standalone-agents/codex-worker.toml` 复制到该位置。它们定义与 Claude Code
同名的 `scout` 和 `worker` agent，并固定推理强度和沙箱。插件的 `worker` 取代 Codex 内置的 `worker`，而 `scout`
不会改动内置的 `explorer`。你修改过的文件绝不会被覆盖，这些 agent 从下一个 Codex 会话起可用。修改过的副本不会更新，
因此它们不指定模型，而由 Codex 指令在每次启动时传入固定模型。钩子也会删除旧版本写入的 `explorer.toml` 并替换旧版本写入的
`worker.toml`，但仅在文件与该版本发布的文件逐字节相同时才这样做，因此你修改过的副本会保留。禁用插件后，已安装的
`worker` 角色不会拒绝编辑，而是作为普通实现 worker 运行。

`PreToolUse` 钩子 `scripts/agent_guard.py` 在两个 host 上阻止内置子 agent。在 Claude Code 上，它拒绝省略类型的调用，
以及所有内置类型：`general-purpose`、`Explore`、`Plan`、`claude` 和 fork。用途狭窄的内置类型 `claude-code-guide` 和
`statusline-setup`，以及插件 agent 和用户、项目、CLI 或托管设置提供的定义都会通过。在 Codex 上，
它拒绝省略类型的调用、`default`、`explorer` 以及没有角色文件的所有类型，包括插件角色存在之前的内置 `worker`。
需要独立只读 worker 的技能使用 `scout`，写入试运行输出的技能则运行单独的 `claude -p` 或 `codex exec` 进程。

### 响应语言

语言守卫 `scripts/language_guard.py` 检查每条回复和每条进度更新是否使用响应语言。Claude Code 从 `language` 设置取得语言，
依次读取本地项目设置、项目设置和用户设置；没有该设置时不做任何强制。Codex 读取 `HEI5ENBUG_RESPONSE_LANGUAGE`，
未设置时使用韩语。只检查有独特文字的语言：韩语、日语、中文、俄语、乌克兰语、希腊语、阿拉伯语、希伯来语、泰语和印地语。
对英语或法语等其他语言，只有指令生效。

检查会忽略代码、引用和 URL。当字母中目标文字至少占 30% 时通过，很短的文本始终通过。回复未通过时，`Stop` 钩子会要求重写，
每个回合最多 3 次。进度更新使用其他语言时，`PostToolUse` 钩子会追加提醒。用户要求以其他语言提供的文本，请放入代码块或引用块。

### DataGrip 查询守卫

`PreToolUse` 钩子和 `PermissionRequest` 钩子 `scripts/datagrip_guard.py` 在 DataGrip MCP 工具 `execute_sql_query` 运行前执行。守卫从
`projectPath` 指向的 DataGrip 项目中的 `.idea/dataSources.xml` 读取连接。名称包含 `승인` 的连接始终要求批准。PostgreSQL 和 SQL Server
的读取无需批准即可运行，PostgreSQL 的读取在只读事务内运行。写入、守卫无法分类的查询、未知连接以及其他数据库类型始终要求批准。守卫从不拒绝调用。在 Codex 中，需要在 `/hooks` 中信任该钩子。

可以选择一次性安装 `pglast` 解析器：

```bash
uv venv --python 3.12 "${XDG_STATE_HOME:-$HOME/.local/state}/hei5enbug-agent-setup/sql-parser"
uv pip install --python "${XDG_STATE_HOME:-$HOME/.local/state}/hei5enbug-agent-setup/sql-parser/bin/python" pglast==8.4
```

没有它时，PostgreSQL 会退回到更严格的文本检查。这可能更频繁地要求批准，但写入仍不会在未经批准的情况下运行。

### 会话批准

仅限 Claude Code 的会话批准守卫 `scripts/session_approval_guard.py` 让你对某些面向外部的写入操作每个会话只批准一次。覆盖范围包括创建 git 标签、向已配置的远程推送标签、
仅使用标签和标志 `--title`, `--notes`, `--target`, `--generate-notes`, `--notes-from-tag`, `--latest`, `--draft`,
`--prerelease`, `--verify-tag` 的 `gh release create` 与 `gh release edit`，以及名称中包含写入动词的 MCP 工具。批准一次后，
同一类操作在该会话的剩余时间内无需提示即可运行。每种工具或命令类型需要分别批准。

不可撤销的操作始终要求批准：强制推送、删除远程分支或标签、删除标签、`gh release delete`、`gh repo delete`，以及执行删除、移入回收站或移除的 MCP 工具。
`gh release upload` 可以发布任意本地文件，因此也始终要求批准。向 URL、未列出的远程或 `--repo` 推送标签，或在 `--tags` 推送中混入分支，以及带有附件、
`--notes-file` 或任何其他标志的 `gh release create` 和 `gh release edit`，同样始终要求批准。包含守卫无法验证的内容的复合命令也始终要求批准。子 agent 不会继承批准。
批准随会话失效，并保存在插件数据目录中。普通推送和其他命令继续使用常规权限流程。

不要为这些操作添加 `permissions.ask` 规则，因为 ask 规则即使在会话批准之后也会每次都提示。

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

## 自动应用指令

在 macOS 和 Linux 上，钩子会把 `instructions/session/common.md` 与当前 host 的 `codex.md` 或 `claude-code.md` 合并。
钩子在会话启动、恢复、清空、上下文压缩后以及子 agent 启动时执行。
`instructions/` 中的详细规则只在对应操作之前读取。
工具调用结束后和回复结束时，语言守卫也会分别通过 `PostToolUse` 和 `Stop` 运行。
DataGrip 查询守卫在 `execute_sql_query` 运行前通过 `PreToolUse` 和 `PermissionRequest` 运行。
在 Claude Code 上，会话批准守卫针对 Bash 和 MCP 工具通过 `PreToolUse` 和 `PostToolUse` 运行。
需要可通过 `python3` 执行的 Python 3.12 或更高版本，并启用钩子。
Codex 还需要用户确认信任钩子。agent 守卫、语言守卫和 DataGrip 查询守卫等由更新新增的钩子在 `/hooks` 中信任之前会被跳过。
会话批准守卫只在 Claude Code 上运行，因此此信任步骤不适用于它。更新插件后请启动新会话。
有关引用、错误和限制，请参阅[英文说明](README.md#automatic-instructions)。

## 更新插件

两个插件清单、`pyproject.toml` 和 `uv.lock` 必须使用同一个语义化版本。
从 `HEAD` 可达的最新 `v<version>` 标签是发布基线。基线之后的第一个变更在同一次提交中确定这些文件里的下一个版本。
只出现在这些文件里的版本，即使已经在 `main` 上，也只是计划中的下一个版本，因此不要再次提升，而是把之后所有未发布的
变更并入它。发布不新增提交：下面的开发检查在 `HEAD` 上全部通过后，给 `HEAD` 打上 `v<version>` 标签并推送该标签。

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

更新后请开启新的 Codex 线程或重启 Claude Code，以便 host 加载新的 skill 和指令。

## 开发检查

内置脚本需要安装了 PyYAML 的 Python 3.12 或更高版本，Node 测试需要 Node.js。
用同样的命令运行 `.github/workflows/validate.yml` 在 macOS 和 Linux 上执行的三项检查：

```bash
python3 -m pip install -e ".[dev]"
for skill in skills/*/ standalone-skills/*/; do python3 skills/skill-builder/scripts/quick_validate.py "$skill"; done
python3 -m pytest
node --test skills/document-to-confluence/tests/test_render_diagrams.mjs
```

需要 Orca CLI 的测试在未安装 Orca 时会跳过，因此 CI 无需 Orca 即可通过。安装 Orca 后重新运行
`python3 -m pytest` 即可覆盖这些测试。

## 指令语言

英文文件是 skill、参考资料、agent 和会话指令的规范可执行来源。
每个供人阅读的英文 Markdown 文件旁都有含义相同的韩文 `.ko.md` 翻译。
翻译不具权威性，agent 执行时不得加载。原文和译文必须一起修改、移动或删除。
代码、架构定义、测试数据、生成文件和非英文文档不需要韩文副本。
韩文只可作为触发短语、示例或必需输出等目标语言数据保留在可执行文件中。

## Skill 列表

| Skill | 作用 |
|---|---|
| [`decision-navigator`](skills/decision-navigator/SKILL.md) | 把跨多个会话的工作拆成决策工单，并逐个解决，直到实现路线清晰。 |
| [`deep-interview`](skills/deep-interview/SKILL.md) | 进行苏格拉底式访谈，每次回答后都为需求的模糊程度打分，只有分数降到阈值以下才会进入执行阶段。[韩文指南](skills/deep-interview/SKILL.ko.md) |
| [`flowchart-design`](skills/flowchart-design/SKILL.md) | 一套通用的流程图设计标准，无论用 SVG、HTML/CSS、Figma 还是 draw.io 制作，都能呈现为同一套设计体系。 |
| [`docs-rewrite`](skills/docs-rewrite/SKILL.md) | 在保持每条主张、数字和确定程度完全不变的前提下改写既有文本，使其读起来自然，并修复带有 AI 痕迹的韩语。[韩文指南](skills/docs-rewrite/SKILL.ko.md) |
| [`document-to-confluence`](skills/document-to-confluence/SKILL.md) | 将 Markdown、HTML、PDF、DOCX 和 Google Docs 内容转换为 Confluence 页面，保留文档结构和附件，并同步后续源文件修订。 |
| [`skill-builder`](skills/skill-builder/SKILL.md) | 通过“起草 → 测试 → 审查 → 改进”的循环来创建、验证并打包 agent skill。 |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | 一并读取已暂存和未暂存的变更，或你指定的范围，结合最近的提交历史，给出 5 条符合本仓库风格的 commit message 建议。要求提交时，它会直接用最合适的一条标题完成提交。 |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | 编写或整理开发设计文档时遵循的规则，以及逐步收窄目录的 5 步流程。[韩文指南](skills/technical-design-writer/SKILL.ko.md) |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | 让当前 agent 与对面的 Claude/Codex 会话进行有轮次限制的辩论，揭示并收敛争议点。[韩文指南](skills/tiki-taka/SKILL.ko.md) |

## 相关链接

- [`omo-model-config`](standalone-skills/omo-model-config/SKILL.md) 仍作为独立源码保留，
  不包含在插件 skill 列表中。
- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — 由该独立 skill 更新其模型路由的插件系统

## 许可证

本仓库采用 Apache License 2.0 授权。全文见 [`LICENSE`](./LICENSE)。
