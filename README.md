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
└── skills/
    ├── deep-interview/
    ├── flowchart-design/
    ├── humanize-korean/
    ├── omo-model-config/
    ├── portable-opencode-setup/
    ├── skill-builder/
    ├── suggest-commit/
    ├── technical-design-writer/
    └── tiki-taka/
```

Each folder holds its own `SKILL.md` plus any references or scripts it needs. There is no shared top-level config — every skill is self-contained.

## Skills

| Skill | What it does |
|---|---|
| [`deep-interview`](skills/deep-interview/SKILL.md) | Runs a Socratic interview that scores requirement ambiguity after every answer and will not move to execution until it drops below the threshold. |
| [`flowchart-design`](skills/flowchart-design/SKILL.md) | A shared design standard so flow charts built in SVG, HTML/CSS, Figma, or draw.io all read as one design system. |
| [`humanize-korean`](skills/humanize-korean/SKILL.md) | Rewrites AI-sounding Korean text into natural, human-sounding Korean without changing its meaning. |
| [`omo-model-config`](skills/omo-model-config/SKILL.md) | Safely edits OpenCode/oh-my-openagent model routing (`model`, `variant`, `fallback_models`) against an upstream allowlist. |
| [`portable-opencode-setup`](skills/portable-opencode-setup/SKILL.md) | Adds missing OpenCode/oh-my-openagent config pieces on a new machine, additive-only, without touching existing settings. |
| [`skill-builder`](skills/skill-builder/SKILL.md) | Creates, tests, and packages agent skills through a draft → test → review → improve loop. |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | Reads the current diff and recent commit history, then suggests five commit messages that match the repo's style. |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | Rules and a five-step narrowing process for writing or cleaning up technical design docs. |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | Runs a turn-limited debate between the current agent and an opposing Claude/Codex session to surface and resolve issues. |

## Known Limitation

`tiki-taka` hardcodes its opponent-agent paths to `~/.claude/skills` and `~/.codex/skills`. Update those paths before running it under any other host.

## Related

- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — plugin system that `omo-model-config` and `portable-opencode-setup` configure
