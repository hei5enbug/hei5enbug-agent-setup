# Plugin updates

This page explains how to release and update the plugin, including applying updates to running Orca sessions.

## Release and update

Both plugin manifests, `pyproject.toml`, and `uv.lock` must use the same semantic version. The newest `v<version>` tag
reachable from `HEAD` is the release baseline. The first change after it sets the next version in these files within the
same commit. A version that appears only in these files is the planned next version, even when it is already on `main`,
so fold every later unreleased change into it instead of bumping again. A release adds no commit: after the [development
checks](../README.md#development-checks) pass on `HEAD`, tag `HEAD` `v<version>` and push the tag.

After the release is available, end affected coding-agent sessions and run the update from a normal terminal. Replacing
a loaded plugin directory can leave a running session with missing hook paths.

Update Codex:

```bash
codex plugin marketplace upgrade hei5enbug
codex plugin add hei5enbug-agent-setup@hei5enbug
```

Update Claude Code:

```bash
claude plugin marketplace update hei5enbug
claude plugin update hei5enbug-agent-setup@hei5enbug
```

Start a new Codex thread or restart Claude Code after updating so the host loads the new skills and instructions.

## Apply an update to running Orca sessions

Ask for `orca-plugin-refresh` after a release to update this plugin, and any other plugins you name, and apply the
installed versions to idle Orca-managed sessions without restarting them. The skill runs only when you ask for it.
`update --json` installs the new version in Claude Code and Codex. Add `--also <plugin@marketplace>` for each other
plugin; without it, the `HEI5ENBUG_REFRESH_PLUGINS` environment variable (comma-separated IDs) and then the saved
`refresh_plugins` option name them, and the first non-empty source wins. Each companion is updated and validated per
host and reported as `updated`, `current`, `not_installed`, `local_source`, `deferred`, or `error`. A plugin that loads
from a local folder is never installed, so uncommitted code is not deployed. A companion error never blocks this plugin
or the session apply. `apply-installed --json` validates the installed roots and companions without marketplace or
install commands. Both create a run ID for `apply --run-id <run_id> --json`.

Each host has its own install gate. Claude Code always installs, because an update adds the new version beside the old
one and running sessions keep their loaded directory until `/reload-plugins`. A Codex update deletes the old install, so
it waits until no Codex turn is running: it defers when the command itself runs inside a Codex turn, when a Codex
session file from the last 30 minutes does not end in a finished turn, or when those files cannot be read. A deferred
Codex host stays untouched, its companions are reported as `deferred`, and the result gives its current root and a
`recovery_command` to run after the Codex turn ends. Busy sessions are retried for up to one hour. Manual updates and
another process deleting a loaded directory remain outside this protection. See the [refresh
workflow](../skills/orca-plugin-refresh/SKILL.md) for commands and limits.

| Part | Claude Code | Codex |
|---|---|---|
| Skills, agents, and hooks | The skill sends `/reload-plugins` | The next turn picks up the new install automatically |
| Session instructions | The skill sends `/compact` when they are stale | The skill sends `/compact` when they are stale; the session loads them on its next turn |

The skill decides that instructions are stale from the session-start marker: it is missing, holds another digest, or
points at a plugin directory that was replaced or removed. It sends a command only to an idle terminal whose input line
is empty and confirms every result from the session transcript or the screen. For a Claude Code session, the skill may
type and delete one character to tell a grey prompt suggestion from typed text; it never sends to a session with typed
text. A busy session is retried for up to one hour and is then reported as skipped. The session that runs the skill is
handled last by a detached helper after its turn ends. Sessions outside Orca need `/reload-plugins` or `/compact` by
hand. The skill supports macOS and Linux user-scope installations from the `hei5enbug` marketplace.
