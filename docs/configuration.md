# Configuration

This page explains plugin options, host-setting checks, and the settings the plugin may change.

## Host settings

Some host settings add approval prompts or stop the guard from running. `scripts/host_settings.py` checks them and, on
Codex only, fixes a short allowlist:

```bash
python3 <plugin root>/scripts/host_settings.py check [--host claude|codex] [--json]
python3 <plugin root>/scripts/host_settings.py apply [--host claude|codex] [--json]
```

Both commands also take `--claude-dir`, `--codex-home`, and `--codex-bin`. The host defaults to the one that runs the
command. `check` is a read and writes nothing. It reports one line per problem:

- Claude Code: `defaultMode` is `dontAsk`, and `permissions.ask` rules that match Bash or MCP tools, up to three named.
- `[features] plugin_hooks` is not `true` in `~/.codex/config.toml`, on either host.
- Codex only: the plugin hooks are unconfirmed (the heartbeat hash differs), `config.toml` is not valid TOML,
  `rules/hei5enbug.rules` is missing, unreadable, outdated, or not plugin-owned, MCP servers lack the `prompt` approval
  mode, the mode step is skipped because `approval_guard` is off, or guard-covered MCP tools carry a per-tool `prompt`
  that would ask even for reads.
- Codex only: a `prompt` or `forbidden` rule in your own `rules/*.rules` files for a read prefix such as `kubectl get`,
  `helm list`, `az show`, or `git status`.

`apply` changes only this allowlist, and only on Codex. On Claude Code it changes nothing and reports that.

- `[features] plugin_hooks`, through `codex features enable plugin_hooks` when `codex features list` shows it. Without
  that command, `apply` says to set it by hand.
- The plugin-owned `~/.codex/rules/hei5enbug.rules`, created or updated to the text of the plugin version. It holds the
  `prompt` rule for the wrapper script used by [Approval guard](approval-guard.md#approval-guard). `apply` only reports,
  and writes nothing, when that path is a symbolic link or an existing file lacks the plugin-owned header line.
- `default_tools_approval_mode = "prompt"` on every `[mcp_servers.<name>]` table, and `approval_mode = "prompt"` on each
  per-tool table that already sets another mode, while `approval_guard` is on. It edits only those lines and writes
  nothing when the result would not parse as intended.

Before it changes a file, `apply` copies it to `<file>.bak-hei5enbug-<YYYYMMDD>`, once per day. It prints one line per
change, and a second run changes nothing. It never edits your own rules files, Claude Code settings, or hook trust.

At session start, the `host_settings` option decides what the hook does. `apply` (the default) runs `apply` on Codex
first and adds one notice naming what changed, then reports the remaining problems from `check`. `report` only reports.
Any other value means `apply`. Claude Code reads the option from `/config`; Codex reads `HEI5ENBUG_HOST_SETTINGS`.

## Feature options

Seven boolean features can be turned off, and each defaults to on. The implementation worker route, the worker models
and efforts, the review model, the host settings mode, the minimum free memory for starting an agent session
(`session_memory_min_mb`), the hook Python interpreter, and the plugins refreshed with this one (`refresh_plugins`)
are string options in Claude Code. Choose `auto`, `codex`, `haiku`, `sol`, or `sonnet` for the
route; an unset or unrecognized value uses `auto`, where the main session picks the worker per assignment. Choose
`apply` or `report` for the host settings mode; an unset or unrecognized value uses `apply`. It decides whether
`SessionStart` may change allowlisted Codex settings; see [Host settings](#host-settings). The review model runs skill
review roles at `high`, or at `xhigh` under the effort rule in [model
routing](../instructions/model-routing.md#keep-role-settings-fixed); independent validation does not use it. Choose one
of the seven pinned model IDs; an unset or unrecognized value uses `gpt-6-astra`. Set plugin options in `/config` or
with `claude plugin configure`. On Codex, set environment variables before starting the session. A value of `false`,
`0`, `off`, or `no`, in any letter case, turns a boolean feature off.

The Claude Code `worker` agent runs on `worker_model` and `worker_effort`; the mod spawns it on them, and an invalid
value keeps the registry pin. The session context reports them as `Worker agent model: <model> at <effort>.` Codex has
no plugin settings UI, so its session hook reads `codex_worker_model` and `codex_worker_effort` read-only from Claude
Code's saved settings (`pluginConfigs` in `~/.claude/settings.json`, or under `CLAUDE_CONFIG_DIR`). The environment
variables override them, and an invalid value falls back to the defaults with a one-line notice. The session context
reports them as `Codex worker model: <model> at <effort>.` They apply from the next Codex session, and reading them
never writes Codex or Claude settings. Only the allowlisted changes in [Host settings](#host-settings) write Codex
settings.

| Feature | Claude Code `/config` key | Codex environment variable |
|---|---|---|
| Block built-in subagents | `agent_guard` | `HEI5ENBUG_AGENT_GUARD` |
| Pin role models | `role_pinning` | Not applicable |
| Risk labels on tool calls | `risk_highlight` | Not applicable |
| Work board for subagents | `work_board` | Not applicable |
| Secret redaction in tool results | `secret_redaction` | Not applicable |
| Implementation worker route | `implementation_worker` (`auto`, `codex`, `haiku`, `sol`, or `sonnet`) | Not applicable |
| Claude Code worker model and effort | `worker_model` (default `claude-haiku-5-5`) and `worker_effort` (default `high`) | Not applicable |
| Codex worker model and effort | `codex_worker_model` (`gpt-5.6-luna` or `gpt-6.1-sol`, default `gpt-5.6-luna`) and `codex_worker_effort` (`high` or `xhigh`, default `high`) | `HEI5ENBUG_CODEX_WORKER_MODEL` and `HEI5ENBUG_CODEX_WORKER_EFFORT` |
| Review model | `review_model` (a pinned model ID, default `gpt-6-astra`) | Not applicable |
| Response language guard | `language_guard` | `HEI5ENBUG_LANGUAGE_GUARD` |
| DataGrip query guard | `datagrip_guard` | `HEI5ENBUG_DATAGRIP_GUARD` |
| Approval guard | `approval_guard` | `HEI5ENBUG_APPROVAL_GUARD` |
| Approval scope | `approval_scope` (`tiered` or `session`, default `tiered`) | `HEI5ENBUG_APPROVAL_SCOPE` |
| Orca worktrees for other repositories | `orca_worktree` | `HEI5ENBUG_ORCA_WORKTREE` |
| Host settings mode | `host_settings` (`apply` or `report`, default `apply`) | `HEI5ENBUG_HOST_SETTINGS` |
| Minimum free memory to start an agent session | `session_memory_min_mb` (MB, default `2048`; `0`, `off`, `false`, or `no` turns the gate off; see [Orca session start](guards.md#orca-session-start)) | `HEI5ENBUG_SESSION_MEMORY_MIN_MB` |
| Hook Python interpreter | `python` (an absolute path, default empty) | `HEI5ENBUG_PYTHON` |
| Plugins refreshed with this one | `refresh_plugins` (comma-separated `plugin@marketplace` IDs, default empty) | `HEI5ENBUG_REFRESH_PLUGINS` |
| Subagent permission block in `~/.codex/AGENTS.md` | Not applicable | `HEI5ENBUG_SUBAGENT_POLICY` |
| Question tool flag | Not applicable | `HEI5ENBUG_CODEX_ASK_TOOL` |

The hook Python interpreter is the absolute path of a Python 3.12 or later interpreter. Install `pglast` into it to run
the SQL guard's parser. Every hook starts through `scripts/hook_python.sh`, which runs its script with this interpreter.
It uses the Claude Code `python` option first and then `HEI5ENBUG_PYTHON`, and only a path that starts with `/` and
names an existing executable file counts. An empty, relative, missing, or invalid value falls back to `python3` on the
`PATH`, so an unset option behaves as before. Setting the path skips a version-manager shim, such as a pyenv shim, which
adds about 150 ms to each hook process on one measured machine and can select a different Python per project. The
launcher caches compiled bytecode under `$XDG_STATE_HOME/hei5enbug-agent-setup/pycache/` (default `~/.local/state`).
This is a guard state folder, so the approval guard denies agent writes there like those to `approvals/` and
`heartbeats/`. Without an absolute state folder, hooks run without a cache.

Without a matching launcher environment, the Mod refuses pinned GPT requests before a provider request. This refusal has
no toggle. The session instructions and operating rules also have no toggle, except the `orca_worktree` line, which
loads the cross-repository rules; disable the plugin itself to turn them off.

## Codex automatic settings

On Codex, the session hook manages two settings, and both take effect from the next session. It keeps this marked block
at the end of `~/.codex/AGENTS.md`, creating the file when it is missing:

```text
<!-- hei5enbug:subagents -->
When hei5enbug-agent-setup is active, use subagents according to its situation-based delegation rules.
<!-- /hei5enbug:subagents -->
```

It also enables the `default_mode_request_user_input` feature when `codex features list` shows it off, so
`request_user_input` is available in Default mode. This does not enforce blocking or disable client-side automatic
resolution. Required decisions follow the [clarification rule](../instructions/session/common.md#clarification); after
an interrupted connection, use [connection recovery](../instructions/connection-recovery.md). Setting
`HEI5ENBUG_SUBAGENT_POLICY=off` removes only the marked block and never edits anything outside it. Setting
`HEI5ENBUG_CODEX_ASK_TOOL=off` disables the feature again, but only when the plugin enabled it; a feature you enabled
yourself stays on. A failed step is retried at the next session start and never stops the session instructions from
loading. Hosts, hook trust, and available tools still govern execution. See the official [Codex subagent
contract](https://learn.chatgpt.com/docs/agent-configuration/subagents).
