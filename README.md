# hei5enbug-agent-setup

**English** | [한국어](./README.ko.md) | [日本語](./README.ja.md) | [简体中文](./README.zh-CN.md) | [Español](./README.es.md) | [Deutsch](./README.de.md) | [Français](./README.fr.md)

A portable collection of custom skills for AI coding agents, built to be shared across multiple agent hosts without host-specific rewrites.

## Overview

Each skill lives in its own folder under `skills/` and is self-contained: its instructions, references, and scripts travel together. The same `SKILL.md` works unmodified on every supported host.

## Supported Hosts

- Claude Code
- Codex
- OpenCode (via the [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) plugin)

## Structure

```
hei5enbug-agent-setup/
├── .agents/plugins/marketplace.json
├── .claude-plugin/
│   ├── marketplace.json
│   └── plugin.json
├── .codex-plugin/plugin.json
└── skills/
    ├── decision-navigator/
    ├── deep-interview/
    ├── flowchart-design/
    ├── humanize-korean/
    ├── markdown-to-confluence/
    ├── omo-model-config/
    ├── portable-opencode-setup/
    ├── skill-builder/
    ├── suggest-commit/
    ├── technical-design-writer/
    └── tiki-taka/
```

Each skill folder holds its own `SKILL.md` plus any references or scripts it needs. The plugin manifests package the
same `skills/` directory for Codex and Claude Code without copying the skills into host-specific directories.

## Plugin installation

Install the bundle once from the GitHub repository.

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

## Plugin updates

Both plugin manifests use the same semantic version. Bump the version in `.codex-plugin/plugin.json` and
`.claude-plugin/plugin.json` before publishing a release.

Update Codex after the release is available:

```bash
codex plugin marketplace upgrade hei5enbug
codex plugin add hei5enbug-agent-setup@hei5enbug
```

Update Claude Code after the release is available:

```bash
claude plugin marketplace update hei5enbug
claude plugin update hei5enbug-agent-setup@hei5enbug
```

Start a new Codex thread or restart Claude Code after updating so the host loads the new skill versions.

## Instruction language

Executable skill instructions are written in English. A `README.ko.md` inside a skill directory is a
non-authoritative Korean translation kept synchronized with its corresponding English document. It is
for human readers and must not be loaded or used by an agent during skill execution. Korean text may
remain in executable files only when it is target-language data, such as trigger phrases, examples,
required output labels, or evaluation fixtures.

## Skills

| Skill | What it does |
|---|---|
| [`decision-navigator`](skills/decision-navigator/SKILL.md) | Maps a multi-session effort into decision tickets and resolves them one at a time until the implementation route is clear. |
| [`deep-interview`](skills/deep-interview/SKILL.md) | Runs a Socratic interview that scores requirement ambiguity after every answer and will not move to execution until it drops below the threshold. [Korean guide](skills/deep-interview/README.ko.md). |
| [`flowchart-design`](skills/flowchart-design/SKILL.md) | A shared design standard so flow charts built in SVG, HTML/CSS, Figma, or draw.io all read as one design system. |
| [`humanize-korean`](skills/humanize-korean/SKILL.md) | Rewrites AI-sounding Korean text into natural, human-sounding Korean without changing its meaning. [Korean guide](skills/humanize-korean/README.ko.md). |
| [`markdown-to-confluence`](skills/markdown-to-confluence/SKILL.md) | Publishes a Markdown document to Confluence and keeps the page correct on later edits, covering the table of contents macro, inline images, attachments, and diagrams rendered to images. |
| [`omo-model-config`](skills/omo-model-config/SKILL.md) | Safely edits OpenCode/oh-my-openagent model routing (`model`, `variant`, `fallback_models`) against an upstream allowlist. |
| [`portable-opencode-setup`](skills/portable-opencode-setup/SKILL.md) | Adds missing OpenCode/oh-my-openagent config pieces on a new machine, additive-only, without touching existing settings. [Korean guide](skills/portable-opencode-setup/README.ko.md). |
| [`skill-builder`](skills/skill-builder/SKILL.md) | Creates, tests, and packages agent skills through a draft → test → review → improve loop. |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | Reads the current diff and recent commit history, then suggests five commit messages that match the repo's style. |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | Rules and a five-step narrowing process for writing or cleaning up technical design docs. [Korean guide](skills/technical-design-writer/README.ko.md). |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | Runs a turn-limited debate between the current agent and an opposing Claude/Codex session to surface and resolve issues. [Korean guide](skills/tiki-taka/README.ko.md). |

## Related

- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — plugin system that `omo-model-config` and `portable-opencode-setup` configure
