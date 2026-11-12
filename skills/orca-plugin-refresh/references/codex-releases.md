# Codex release updates

Before the first Codex command in an `update` run, the script resolves each selected Git marketplace's newest
`v<major>.<minor>.<patch>` tag from its remote and writes that tag to its `config.toml` ref. Preview tags are excluded.
It snapshots the installed versions first because even `codex plugin list` can trigger an automatic update.
If the initial install gate defers Codex before ref selection, it leaves refs unchanged and runs no Codex command
for configured Git marketplaces.

A marketplace with no release tag keeps its ref and gets `codex_marketplace_untagged`. The script runs no explicit
upgrade or install for it and continues with other marketplaces. Report that any Codex start can still install its
untagged commits until it has a tag or the user sets its ref. A configuration read or update failure stops Codex
commands for that run.

## Hook trust

`codex_hooks_need_trust` means hooks remain untrusted or could not be verified. This plugin retains its existing
check of a clean official checkout before trusting its own hooks: HEAD must be advertised by the official remote
for `main` or a `v*` tag, or contained in its current `main`. A companion's hooks are trusted without another
question only when all of these checks pass:

- Each hook identifies that companion, its source file is inside the installed folder, and its command points into
  that folder without shell chaining or mutable Git/install metadata.
- The install marker's source equals the configured marketplace source, its ref equals the pinned tag name, and
  its revision equals the commit that the remote currently advertises for that tag.
- Every installed file matches that commit's plugin directory, with no extra files except Git metadata and the
  marketplace install marker. Symlinks and unsupported plugin sources are refused.

The script uses Codex's `config/value/write` to trust the current hashes and confirms them with `hooks/list`.
Report `codex_hooks_trusted: true` on success. Otherwise report `codex_hooks_need_trust` with its reason and ask the
user to review the remaining hooks in `/hooks`; Codex skips them until trusted.

## Sessions on replaced folders

For a Codex session that has run a turn, `apply` compares its process start with the selected plugins' install-marker
times. A process that predates an installed folder is reported as `skipped` with `codex_plugin_folder_replaced` and
`resume_approval_needed`; it receives no compact command. A process started after installation, including a resumed
one, and a session with no turn are excluded. Report it as not refreshed and offer its resume in step 6.
