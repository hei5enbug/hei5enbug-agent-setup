# Delegation

Rules for handing the issue to a session in the owning plugin's repository. Read this before drafting when
`orca status --json` reports a reachable runtime and this session is not working in that repository. The handoff
sends drafting, the duplicate search, filing, and verification away, so the original session returns to its task.

## Decide

Take `plugin_name` from the `find_tracker.py` result. The owning repository is the registered repository in
`orca repo list --json` whose clone holds a `.claude-plugin/plugin.json` or `.codex-plugin/plugin.json` naming that
plugin. This session already works in it when the Git root of its working directory holds such a manifest with that name;
then skip this file and continue in this session.

File the issue in this session, and say why in one line, when any of these holds:

- Orca lists no workspace for the owning repository: its clone or one of its worktrees in
  `orca worktree list --repo id:<repoId> --json`.
- `ORCA_TERMINAL_HANDLE` is unset, or the marker in "Original session" has no `transcript_path`.
- The send in "Hand off" is not accepted, or no delegate session becomes idle.

## Find the delegate

`<host>` is `claude` on Claude Code and `codex` on Codex; use only a session of the same host as this one.

1. List the terminals of the workspace and of each of its worktrees with
   `orca terminal list --worktree id:<workspace id> --json`.
2. Take the first terminal of `<host>` that passes all of these:
   - `orca terminal wait --terminal <handle> --for tui-idle --timeout-ms 5000 --json` reports `wait.satisfied`.
   - `orca terminal read --terminal <handle> --screen` shows no open question or approval prompt.
   - Its input line is empty: send `--text x`; when the line then shows only `x`, delete it with `--text $'\x7f'`.
     Otherwise delete the `x`, send nothing to that terminal, and go on to the next one.
3. When none passes, run `orca terminal create --worktree id:<workspace id> --command <host> --json`, then
   `orca terminal wait --terminal <handle> --for tui-idle --timeout-ms 60000 --json`. When `wait.satisfied` is
   still false after one longer wait, file in this session.

Never answer a prompt in another session. The [messaging rules](../../../instructions/cross-repository.md) cover the
send and read flags.

## Original session

The session-start hook records each interactive Orca terminal in
`$ORCA_USER_DATA_PATH/hei5enbug-agent-setup/terminals/$ORCA_TERMINAL_HANDLE.json`. Read its `transcript_path`: the
original session's transcript file. The original terminal handle is `$ORCA_TERMINAL_HANDLE`.

## Hand off

Send one message with `orca terminal send --terminal <handle> --text "<handoff>" --enter --json`. It states:

- to run `skill-issue-creator` for one issue;
- the gap in a few lines, the owning file's path inside the plugin, and the case's identifiers from step 1;
- the original session's transcript file, with the instruction to read every user message in it and apply the
  requirement and question rules in the delegate's own session;
- the original terminal handle, and that the delegate reports the issue link back as in "Report back".

Include no secret and no local path other than the transcript file. The handoff is done when the send reports
`accepted: true`; do not wait for the work. Tell the user in one line which workspace's session took the issue and that
its questions appear there, then continue the original task.

The link arrives in this terminal's Orca mailbox, which keeps it only while this terminal is open. When the host
notifies you when a background command ends, run
`orca orchestration check --terminal $ORCA_TERMINAL_HANDLE --wait --types status --timeout-ms 1800000 --json` in the
background and report the link when it returns. Otherwise, or after it times out, run the same check without
`--wait` once before your final reply.

## Delegate session

Run `skill-issue-creator` from step 2 on, with the transcript file as the source of user messages. Ask the user in this
session. After step 9, report back.

## Report back

Run `orca orchestration send --to <original terminal handle> --from $ORCA_TERMINAL_HANDLE --subject "Issue filed"
--body "<issue link>" --type status --json`, where the handle is the one the handoff names. Send the link or the
reason nothing was filed, and no draft text.
