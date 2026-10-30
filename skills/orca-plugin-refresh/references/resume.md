# Resume a session

Run this only for a Claude Code session that reports `resume_approval_needed`, and only for the terminals the user
approved in the current request. Run `python3 <script> resume --run-id <run_id> --terminal <handle> --json`, repeating
`--terminal` once per approved session. The handle is the full Orca terminal handle, not the `…` suffix in a report.

## What the script does

For each named terminal, in this order, it:

1. Reads the conversation ID from the session marker's transcript file name. Without one it skips the session.
2. Checks that the session is idle by its own turn record, owes no background notification, has no open question or
   approval prompt on screen, and has an empty input line. Otherwise it skips the session and sends nothing.
3. Finds the session's process by the `ORCA_TERMINAL_HANDLE` in its own environment, and reads its exact arguments and
   `CLAUDE_CONFIG_DIR` from that process, never from the terminal's shell.
4. Sends `/exit`, waits for that process to end, then sends one line in the same terminal: the process's
   `CLAUDE_CONFIG_DIR`, the current `claude` executable, the original option arguments, and
   `--resume <conversation ID>`.
   It reads which tokens are option values from `claude --help`, drops the positional prompt, and drops `--continue`,
   `--resume`, `--session-id`, `--fork-session`, and `--print`. When the help is unreadable or an option is not in it,
   it skips the session before `/exit` as `launch_arguments_unknown`.
5. Confirms that the session marker was rewritten with `source: resume` for the same conversation, that the new process
   has the same `CLAUDE_CONFIG_DIR`, and that a following `/reload-plugins` loads without an error.

## Report each session

- `done` with `resumed`: every confirmation passed. `note: no_config_dir_in_process` means the ended process had no
  `CLAUDE_CONFIG_DIR`, so the line carries none. `release_before` and `release_after` name the two releases.
- `skipped`: nothing was sent and the session was not ended. `busy`, `unsent_input`, `input_unknown`, and the other
  not-ready reasons mean it was not idle with an empty input line. `background_task` means a background task, subagent,
  or wakeup still owes a notification, and ending the session would stop it; tell the user and let them choose again
  later. `session_id_unknown`, `process_not_found`, `session_process_ambiguous`, `claude_missing`, and
  `launch_arguments_unknown` mean the script could not identify what to resume. `not_a_claude_session` means
  the terminal is not a Claude Code session.
- `failed`: the session was ended. `exit_timeout` means the process did not end, and no resume line was sent.
  `resume_marker_missing` and `resume_session_mismatch` mean the resumed session was not confirmed to hold the same
  conversation. `resumed_process_missing` and `config_dir_mismatch` mean the new process is missing or runs on a
  different configuration folder. `plugin_load_error` means the resumed session still reports a load error, with
  `plugin_load` holding the counts. Tell the user to check that terminal; the script never retries.
