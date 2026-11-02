# Repository development

This page explains the repository layout and issue-tracker declaration for contributors.

## Structure

```text
hei5enbug-agent-setup/
├── .agents/plugins/marketplace.json
├── .claude-plugin/
│   ├── marketplace.json
│   └── plugin.json
├── .codex-plugin/plugin.json
├── .github/workflows/validate.yml
├── AGENTS.md
├── issue-target.json
├── docs/
│   ├── approval-guard.md
│   ├── claude-code-mod.md
│   ├── configuration.md
│   ├── development.md
│   ├── guards.md
│   ├── instructions-and-delegation.md
│   ├── rule-enforcement.md
│   ├── updates.md
│   └── ko/
│       ├── AGENTS.ko.md
│       ├── README.ko.md
│       ├── agents/
│       ├── evals/
│       ├── instructions/
│       └── skills/
├── evals/e2e/
├── hooks/hooks.json
├── hooks/claude-hooks.json
├── hooks/codex-hooks.json
├── hooks/mod/
├── config/claude-mod.json
├── config/model-registry.json
├── instructions/
│   ├── claude-agents.md
│   ├── codex-agents.md
│   ├── confluence.md
│   ├── cross-repository.md
│   ├── documentation.md
│   ├── failure-and-maintenance.md
│   ├── implementation-delegation.md
│   ├── implementation-execution.md
│   ├── implementation-planning.md
│   ├── independent-model-validation.md
│   ├── model-evaluation.md
│   ├── model-routing.md
│   ├── protected-values.md
│   ├── readme-writing.md
│   ├── services.md
│   └── session/
│       ├── claude-code.md
│       ├── codex.md
│       ├── common.md
│       └── core.md
├── scripts/
│   ├── agent_guard.py
│   ├── approval_guard.py
│   ├── approval_state*.py
│   ├── approve_wrapper.sh
│   ├── datagrip*.py
│   ├── guard_*.py
│   ├── hook_python.sh
│   ├── host_settings.py
│   ├── language_guard.py
│   ├── plugin_toggles.py
│   ├── role_runner.py
│   ├── session_context.py
│   └── verify_spawn.py
├── tests/
├── LICENSE
├── pyproject.toml
├── agents/
│   ├── designer.md
│   ├── reviewer.md
│   ├── scout.md
│   ├── sonnet-worker.md
│   └── worker.md
├── standalone-agents/
│   ├── codex-designer.toml
│   ├── codex-reviewer.toml
│   ├── codex-scout.toml
│   └── codex-worker.toml
└── skills/
    ├── aside-browser-tasks/
    ├── decision-navigator/
    ├── deep-interview/
    ├── flowchart-design/
    ├── docs-rewrite/
    ├── document-to-confluence/
    ├── local-data-cleanup/
    ├── mistake-enforcer/
    ├── orca-plugin-refresh/
    ├── report-skill-gap/
    ├── session-retro/
    ├── skill-builder/
    ├── suggest-commit/
    ├── technical-design-writer/
    └── tiki-taka/
```

Each plugin skill folder holds its own `SKILL.md` plus any references or scripts it needs. The plugin manifests package
the same `skills/` directory for Codex and Claude Code without copying skills into host-specific directories.

## Issue tracker declaration

`report-skill-gap` files an issue only at a tracker that the owning plugin declares in `issue-target.json` at its root,
next to `.claude-plugin/` and `.codex-plugin/`. The skill learns every tracker from these files, so this plugin never
needs to know about a plugin that builds on it. This plugin declares its own repository:

```json
{
  "version": 1,
  "tracker": {"kind": "github", "location": "hei5enbug/hei5enbug-agent-setup"},
  "language": "en",
  "body_format": "markdown",
  "labels": ["bug", "enhancement"],
  "public": true,
  "write_approval": "preview"
}
```

| Field | Meaning |
|---|---|
| `version` | Always `1`. |
| `tracker` | `kind` is `github`, `gitlab`, `jira`, or `other`; `location` is `owner/repo` on GitHub, otherwise the project URL or key. |
| `language` | Language tag of the issue text, such as `en` or `ko`. |
| `body_format` | `markdown`, `jira-wiki`, `plain`, or `html`. |
| `labels` | Either a list of labels the skill may choose from, of which it picks one (none when the list is empty), or a template string of tags separated by `;` in which `{skill}` becomes the owning skill's name and every tag is applied. A new-skill proposal expands `{skill}` to the proposed skill's name followed by `new-skill`. No other placeholder is allowed. |
| `public` | `true` when anyone can read the tracker. A public tracker always gets a preview. |
| `write_approval` | `preview` shows the final text and waits for approval; `direct` files when you name the skill. |
| `content_rules` | Optional path, relative to the plugin root, of extra rules that remove content from every issue. |
| `recommend` | Optional boolean, `false` when absent. `true` lets the agent suggest filing in one line, without being asked, when no work remains and you corrected a finished result caused by a gap in this plugin or asked to turn a finished workflow into a skill or an issue. Filing starts only after you approve in a later message. |

Unknown keys make the declaration invalid. A plugin without the file, or with an invalid one, gets the draft in the
conversation and no issue. For a tracker kind other than `github`, the skill uses its connected tool when that tool
reaches the declared location, otherwise that tracker's official CLI when it is already authenticated; with neither, it
shows the draft and files nothing.

## Archived skill

- `omo-model-config` was removed; its last version is in the [`v1.3.0`
  tag](https://github.com/hei5enbug/hei5enbug-agent-setup/tree/v1.3.0/standalone-skills/omo-model-config).
