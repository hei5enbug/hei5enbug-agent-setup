# hei5enbug-agent-setup

A personal agent harness that gives Claude Code and Codex users shared skills, session instructions, and guard hooks.

[한국어 안내](docs/ko/README.ko.md)

- [What it does](#what-it-does)
- [Supported hosts and requirements](#supported-hosts-and-requirements)
- [Installation](#installation)
- [Skills](#skills)
- [Documentation](#documentation)
- [Development checks](#development-checks)
- [Related](#related)
- [License](#license)

## What it does

| Capability | What you get |
|---|---|
| Session instructions | Shared operating rules loaded automatically, with detailed references read only when needed. |
| Skills | Reusable workflows for engineering, documentation, browser work, and maintenance. |
| Delegation and model routing | Bounded worker assignments with model, effort, and execution checks. |
| Approval guard | Reads without approval, session approvals for writes and sensitive reads, and repeated approval for destructive calls. |
| Claude Code mod | Role pinning, built-in agent restrictions, risk labels, a work board, and secret redaction. |
| Response language and DataGrip guards | Response-language checks and database query safeguards. |

Each skill keeps its instructions, references, and scripts together. The same `SKILL.md` works unmodified on both hosts.

## Supported hosts and requirements

| Requirement | Details |
|---|---|
| Host | Claude Code or Codex. See [mod compatibility](docs/claude-code-mod.md) for the tested Claude Code minimum. |
| Platform | macOS and Linux. Windows execution is not covered by the tests. |
| Python | Python 3.12 or later on `PATH` as `python3`, or a [configured hook interpreter](docs/configuration.md#feature-options). |
| Hooks | Enable plugin hooks; in Codex, review and trust them in `/hooks`. Managed policies may prevent them from running. |
| Optional SQL parser | Install `pglast` for the [DataGrip PostgreSQL parser](docs/guards.md#datagrip-query-guard). |

OpenCode configuration remains source material only; this plugin does not install, maintain, or execute it.

## Installation

Install the bundle once from the GitHub repository using your host's commands.

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

### First use

Start a new Codex thread or restart Claude Code. Check that the plugin hooks are enabled and, in Codex, trusted.
Session instructions load automatically; new Codex roles become available in the next session.
To try a skill in a project, ask:

```text
Use suggest-commit to suggest commit messages for my current changes.
```

Choose options in Claude Code's `/config` or set the corresponding environment variables before starting Codex.
See [configuration](docs/configuration.md) for defaults and [updates](docs/updates.md) when updating an installation.

## Skills

| Skill | Purpose |
|---|---|
| [`aside-browser-tasks`](skills/aside-browser-tasks/SKILL.md) | Finish browser tasks through your logged-in Aside Browser when other tools cannot. [한국어](docs/ko/skills/aside-browser-tasks/SKILL.ko.md) |
| [`decision-navigator`](skills/decision-navigator/SKILL.md) | Resolve decision tickets until an implementation route is clear. [한국어](docs/ko/skills/decision-navigator/SKILL.ko.md) |
| [`deep-interview`](skills/deep-interview/SKILL.md) | Clarify requirements through a scored Socratic interview. [한국어](docs/ko/skills/deep-interview/SKILL.ko.md) |
| [`flowchart-design`](skills/flowchart-design/SKILL.md) | Create and repair flow diagrams with a shared design standard. [한국어](docs/ko/skills/flowchart-design/SKILL.ko.md) |
| [`docs-rewrite`](skills/docs-rewrite/SKILL.md) | Make existing prose natural while preserving its meaning, including awkward Korean. [한국어](docs/ko/skills/docs-rewrite/SKILL.ko.md) |
| [`document-to-confluence`](skills/document-to-confluence/SKILL.md) | Publish documents to Confluence and synchronize revisions while preserving web edits and comments. [한국어](docs/ko/skills/document-to-confluence/SKILL.ko.md) |
| [`local-data-cleanup`](skills/local-data-cleanup/SKILL.md) | Check agent data, report it by size, and delete only the items you select. [한국어](docs/ko/skills/local-data-cleanup/SKILL.ko.md) |
| [`mistake-enforcer`](skills/mistake-enforcer/SKILL.md) | Turn recurring repository mistakes into checks proven on past cases, when requested. [한국어](docs/ko/skills/mistake-enforcer/SKILL.ko.md) |
| [`report-skill-gap`](skills/report-skill-gap/SKILL.md) | File a skill or instruction gap at its declared tracker after removing private case details. [한국어](docs/ko/skills/report-skill-gap/SKILL.ko.md) |
| [`session-retro`](skills/session-retro/SKILL.md) | Review session history for evidence-backed skill improvements and requested plans. [한국어](docs/ko/skills/session-retro/SKILL.ko.md) |
| [`skill-builder`](skills/skill-builder/SKILL.md) | Create, evaluate, improve, and package agent skills. [한국어](docs/ko/skills/skill-builder/SKILL.ko.md) |
| [`orca-plugin-refresh`](skills/orca-plugin-refresh/SKILL.md) | Update plugins and apply them to idle Orca sessions without restarting them. [한국어](docs/ko/skills/orca-plugin-refresh/SKILL.ko.md) |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | Suggest five repository-style commit messages, or commit when asked. [한국어](docs/ko/skills/suggest-commit/SKILL.ko.md) |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | Write and review technical design documents and RFCs, separate from implementation planning. [한국어](docs/ko/skills/technical-design-writer/SKILL.ko.md) |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | Resolve issues through a bounded Claude/Codex debate. [한국어](docs/ko/skills/tiki-taka/SKILL.ko.md) |

Each linked skill defines its full workflow, invocation conditions, and limits.

## Documentation

| Document | What it answers |
|---|---|
| [Claude Code mod](docs/claude-code-mod.md) | Which Claude-only guards and views run, and on which host versions? |
| [Response language and DataGrip guards](docs/guards.md) | How are replies checked and database queries protected? |
| [Approval guard](docs/approval-guard.md) | Which calls pass, ask, or are denied, and how do approvals work? |
| [Configuration](docs/configuration.md) | Which options are available, and which host settings can change? |
| [Instructions and delegation](docs/instructions-and-delegation.md) | How do instructions load, workers run, and model checks work? |
| [Updates](docs/updates.md) | How do releases, host updates, and running Orca sessions work? |
| [Development](docs/development.md) | Where does code live, and how is an issue tracker declared? |
| [Rule enforcement](docs/rule-enforcement.md) | Which checks enforce each written rule? |

## Development checks

The bundled scripts need Python 3.12 or later with PyYAML. The Node tests need Node.js. The mod tests and the plugin
validation need the Claude Code CLI, version 2.1.307 or later, and 2.1.307 in CI.
Run the checks that `.github/workflows/validate.yml` runs on macOS and Linux, plus the plugin validation:

```bash
python3 -m pip install -e ".[dev]"
for skill in skills/*/; do python3 skills/skill-builder/scripts/quick_validate.py "$skill"; done
python3 -m pytest
node --test skills/document-to-confluence/tests/test_render_diagrams.mjs
claude plugin validate .
claude plugin test .
```

Tests that need the Orca CLI skip when it is not installed, so CI passes without Orca. After installing Orca,
run `python3 -m pytest` again to cover them.

For a faster run on a multi-core machine, run `python3 -m pytest -n auto`,
which spreads the tests over worker processes.

To block a commit, push, tag, or GitHub write that breaks the public boundary before it runs, run
`git config core.hooksPath .githooks` once per clone. To also block names that cannot be listed in this public
repository, set `HEI5ENBUG_PUBLIC_BOUNDARY_WORDS` to a word list file outside the repository, one word or phrase per
line. Claude Code loads the project hook from `.claude/settings.json`; Codex runs the hook in `.codex/hooks.json`
only after you trust the project and review the hook in `/hooks`.

The end-to-end evaluation in `evals/e2e/` runs real agent sessions, so it is not one of these checks; only its
unit tests run with `python3 -m pytest`. See [its README](evals/e2e/README.md).

## Related

- For help or contributions, use the [issue tracker](https://github.com/hei5enbug/hei5enbug-agent-setup/issues) and
  [development guide](docs/development.md).
- The removed `omo-model-config` skill is available in its [archive](docs/development.md#archived-skill).

## License

This repository is licensed under the Apache License 2.0. See [`LICENSE`](./LICENSE) for the full text.
