# Codex release updates

Before the first Codex command in an `update` run, the script resolves each selected Git marketplace's newest
`v<major>.<minor>.<patch>` tag from its remote and writes the commit that tag points to (the peeled commit of an
annotated tag) to its `config.toml` ref, not the tag name, because Codex reinstalls a marketplace pinned to an annotated
tag name at every start. Preview tags are excluded. The tag name stays in the pins and reports. A ref that is already
the commit of an advertised tag counts as pinned to that tag.
It snapshots the installed versions first because even `codex plugin list` can trigger an automatic update.
If the initial install gate defers Codex before ref selection, it leaves refs unchanged, a tag-name ref included, and runs
no Codex command for configured Git marketplaces; the install job pins the commit when it actually installs.

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
- The install marker's source equals the configured marketplace source, its ref equals the pinned commit, and
  its revision equals the commit that the remote currently advertises for the pinned tag.
- Every installed file matches that commit's plugin directory, with no extra files except Git metadata and the
  marketplace install marker. Symlinks and unsupported plugin sources are refused.

The script uses Codex's `config/value/write` to trust the current hashes and confirms them with `hooks/list`.
Report `codex_hooks_trusted: true` on success. Otherwise report `codex_hooks_need_trust` with its reason and ask the
user to review the remaining hooks in `/hooks`; Codex skips them until trusted.

## Sessions on replaced folders

For a Codex session that has run a turn, `apply` compares its process start with the selected plugins' install-marker
times. A process that predates an installed folder receives no compact command. `apply` resumes it when it is idle with an empty
input line (`done` with `resumed`) and hands a busy one to the helper with the remaining action `resume`. When a resume
check fails it is `skipped` with `codex_plugin_folder_replaced`, `resume_check`, and `resume_approval_needed`; report it as
not refreshed and offer its resume in step 6. A process started after installation, including a resumed one, and a
session with no turn are excluded.

## Busy sessions and the install gate

The install gate names every Codex rollout modified in the last 30 minutes whose last complete line does not end a turn,
and matches each to an Orca terminal through the Codex session markers' transcript path. `update` defers the Codex install
and asks one `codex_install` question per busy session; `references/busy-sessions.md` holds the options and the install
job that `decide` starts.
