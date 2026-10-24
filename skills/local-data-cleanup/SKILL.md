---
name: local-data-cleanup
description: >-
  Find reclaimable local data that Claude Code and Codex leave on this machine, such as scratch folders of
  ended sessions, superseded host and plugin releases, old session records, and stale temporary folders,
  report it by size, and delete only the items the user selects after every safety check passes. Use only when
  the user asks to find or free disk space used by Claude Code or Codex, such as "Claude랑 Codex가 쓰는 디스크
  정리해줘" or "free up space the agents use", or when the user approves, in a later message, a one-line
  recommendation to run it. Never start it automatically, and do not use it for general disk cleanup or for a
  project's own build output.
compatibility: >-
  Needs Python 3.12 or later, filesystem access to the hosts' data folders, and the `ps`, `lsof`, and `git`
  commands; a missing command, or one that exits with a non-zero status, makes the checks that need it unknown,
  so nothing they cover is offered. `lsof` runs without search terms, so no exit status means "no matches".
  Without administrator rights, `lsof` sees only the current user's processes. The second verdict needs a
  read-only agent on the other host.
---

# Local Data Cleanup

Use this English `SKILL.md` and its English references as the only executable sources.

Survey the local data of Claude Code and Codex read-only, check every candidate against fixed safety rules and
an independent verdict from the other host, and delete only what the user selects. Every deletion is
irreversible, so the user always chooses the items; a size or an age alone never makes an item deletable.

## Execution placement

| Step | Owner |
|---|---|
| 1. Settle the scope | main |
| 2. Survey | main, with the bundled script |
| 3. Second verdict | the other host's read-only agent |
| 4–5. Merge and report | main, with the bundled script |
| 6–7. Delete and verify | main, with the bundled script, only after the user selects items |

## Boundaries

- Start only on the user's request, or after the user approves a one-line recommendation in a later message.
  Never start on your own because a disk looks full.
- Steps 1 to 5 are read-only. They read sizes, modification times, link targets, process and open-file state,
  Git status, the host's installed-plugin list, and its live-session records. Read conversation transcripts and
  session records only as metadata, never their contents.
- Delete only in step 6, only the items the user selected, and only through the bundled script. Never delete,
  move, or change the permissions of anything by hand.
- Write the survey, verdict, and plan files only to the host's session temporary folder; without one, use a new
  folder under the operating system's temporary folder. The current session's own temporary folder then shows as
  report-only because its session is active; that is expected.
- Never lower a threshold to find more items. When a kind has nothing reclaimable, say so.

## Workflow

Run the bundled script by its path relative to the directory that holds this `SKILL.md`:

```text
python3 scripts/local_data.py <survey|merge|delete> ...
```

Every subcommand prints one JSON object. Exit 0 means it finished, 1 means it finished with items it skipped or
could not verify, and 2 means an invalid argument or input file, which you fix before running again.

### 1. Settle the scope

Take from the request which hosts to scan (default both), the age threshold for old session records (default 30
days), and an optional minimum size (default 1 MiB). State the values you use. Pass a data folder option only
when the user names a folder other than the host's default.

### 2. Survey

```text
python3 scripts/local_data.py survey --host <claude|codex|both> [--age-days N] [--min-size SIZE] \
  [--claude-dir DIR] [--claude-plugin-cache DIR] [--claude-install-dir DIR] [--claude-launcher PATH] \
  [--codex-dir DIR] [--temp-root DIR]... [--protect PATH]... --out <temporary folder>/survey.json
```

The script finds items of these kinds under the known data roots and session temporary roots, and checks each
one:

| Kind | Example | User decision |
|---|---|---|
| Superseded release | a host release older than the one its `current` or launcher link points to | no |
| Superseded plugin version | a cached plugin version older than every installed version | no |
| Ended-session scratch | a session's temporary folder after the session ended | no |
| Stale temporary entries | entries of a host temporary folder | no |
| Old session records | records whose newest file is older than the age threshold | yes |

Every other top-level entry of the Claude Code and Codex data folders is listed as `other`: protected when it holds
state, such as a database, credential, configuration, or history, and report-only otherwise, so the user sees where
the rest of the space goes. It is never offered.

A size is the space on disk that deleting the item frees. A hard-linked file counts only when every one of its
links lies inside the item, because a link elsewhere keeps its space in use.

An item is a candidate only when every check passes; any failed or unknown check makes it report-only:

- No live process names the item or its session, no recorded session that owns it is active, and no running host
  process could still load a superseded plugin version. Old session records get the same session checks as
  scratch folders; a record file whose session ID cannot be read, or a process list or session file that cannot be
  read, makes the check unknown.
- No process holds a file or its working folder open under the item.
- The item is not the target of a `current` or launcher link, not an installed plugin path, and does not contain
  or sit inside one.
- Nothing under the item changed within the last 24 hours.
- The item is not and does not contain a state database, credential, configuration, history, memory, or an entry
  the user protected with `--protect`. These are never offered. Inside a superseded release, a cached plugin
  version, or a plugin or marketplace package, only state databases and credentials count, because the
  configuration-like files there ship as code.
- Its resolved real path stays inside the known data and session temporary roots.
- No Git work tree that holds the item or sits inside it has uncommitted changes or untracked files that are not
  ignored.

### 3. Second verdict

Fill `references/peer-assignment.md` with the survey's candidates and give it to one read-only agent on the other
host: Codex when this session runs in Claude Code, Claude Code when it runs in Codex. Run it through the session's
route for a skill review role when that route runs on the other host. Accept the result only when the run's evidence
names a model of the other host's family. Save the agent's JSON reply as `peer.json` next to the survey.

When that route is unavailable, fails, or runs on the same host, or its evidence names no model of the other
host's family, do not write a verdict file yourself. Merge with `--peer-unavailable <reason>` instead; every
candidate then stays report-only with that reason, and nothing is offered for deletion.

### 4. Merge

```text
python3 scripts/local_data.py merge --survey <survey.json> (--peer <peer.json> | --peer-unavailable <reason>) \
  --self-host <claude|codex> --out <temporary folder>/plan.json
```

A candidate becomes `offer` only when the peer verdict is `delete`. A `keep`, an `unknown`, or a missing verdict
makes it report-only with the peer's reason. A peer file from the same host is rejected with exit 2.

### 5. Report

Present, in the user's language, one table of the `offer` items sorted by size, largest first, with the number,
size, path with its root shown as a placeholder such as `<codex>`, what it is, verdict, and reason. For an
old-session-record item, mark it as the user's decision and state its consequence: the sessions it holds can no
longer be resumed or reviewed. Then list the report-only and protected items, including `other` entries, separately,
also by size, with the reason each was not offered, and every note the plan holds, such as a kind with nothing
reclaimable. When the user wants old Claude Code conversation records kept for less time, name its
`cleanupPeriodDays` setting as the lasting alternative to deleting them by hand. End with the total the offered
items would free and ask which numbers to delete, stating that deletion cannot be undone.

### 6. Delete the selected items

Run this only after the user names the items in a later message. When the user selects nothing or declines,
delete nothing and say so.

```text
python3 scripts/local_data.py delete --plan <plan.json> --select <id> [--select <id>]...
```

The script refuses an ID that is not `offer`, and deletes nothing when any selected ID is refused. It repeats
every check on each selected item first and skips an item whose state changed. Inside a selected item only, it
adds owner permissions to folders that block removal; it never changes a permission outside the item.

### 7. Verify and report

From the delete output, report for each item whether it is gone and the size it freed, the total, every skipped
or failed item with its reason, and whether the protected items and the link targets are unchanged. When a
verification failed, say so plainly and do not retry the deletion without the user.

## Final report

State the scope and thresholds, the second verdict's host and model evidence or why it was unknown, the offered
and report-only tables, the user's selection, and the verification result.
