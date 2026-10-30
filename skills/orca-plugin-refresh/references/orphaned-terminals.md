# Orphaned terminals

An orphaned terminal is one whose Orca tab was closed while its agent process kept running. Run `orphans` and `close`
only at the end of a run, and run `close` only for the terminals the user approved in the current request.

## List

Run `python3 <script> orphans --run-id <run_id> --json`. It lists every orphaned Claude Code or Codex terminal with
`host`, `worktree`, and `idle_seconds`, the time since its transcript or rollout was last written. It closes nothing.
For Claude Code it may type one character and delete it to tell a grey prompt suggestion from typed text.

A terminal is `recommended` only when every check passes. Otherwise `failed_check` names the first check that failed:

| `failed_check` | Meaning |
|---|---|
| `terminal_unreachable` | The terminal is not connected or not writable, so its screen cannot be read. |
| `turn_busy` | The host's turn record shows a turn in progress. |
| `turn_record_unavailable` | The turn record is missing or not decisive, so idle cannot be confirmed. |
| `background_task_pending` | A background task, subagent, or scheduled wakeup still owes a notification. |
| `activity_unknown` | The last transcript write time cannot be read. |
| `recently_active` | The last transcript write was less than 24 hours ago. |
| `input_not_empty` | The input line holds typed text. |
| `input_unknown` | The input line could not be read. |

Show the list and ask the user once which recommended terminals to close. Offer only recommended terminals for closing.

## Close

Run `python3 <script> close --run-id <run_id> --terminal <handle> --json`, repeating `--terminal` once per approved
terminal. The handle is the full `handle` from the list, not the `…` suffix. The script runs `orca terminal close` for
one terminal at a time, after it checks again that the terminal is still orphaned, is an agent session, and passes
every check above. It never deletes transcripts, markers, or worktrees.

## Report each terminal

- `closed`: Orca closed the terminal and it no longer appears in `orca terminal list`.
- `skipped`: the terminal stays open. `detail` is a failed check above, `not_orphaned` (the terminal is not
  orphaned, so it is never closed), `terminal_not_found`, or `not_an_agent_session`. Tell the user and let them choose
  again later.
- `failed`: the close was requested but the terminal still appears in the list (`close_unconfirmed`), or Orca returned
  an error. Tell the user to check that terminal; the script never retries.
