# Why the script skips, defers, or fails a session

## Safety and limits

- Commands are argument lists, never a shell. Each host updates a marketplace at most once per run, then the
  plugin: Claude Code runs `claude plugin marketplace update` and `claude plugin update`, and Codex runs
  `codex plugin marketplace upgrade` and `codex plugin add`. `update` and `apply-installed` also run `claude update`
  once first.
- Before reporting an install as successful, the script checks the installed manifest name and version and every
  hook target that points into the plugin directory. For this plugin it also checks every required hook target,
  the Claude Code mod files, and the instruction digest. A failed plugin does not hide another plugin's or host's
  successful result.
- The Codex gate reads only Codex rollout files modified in the last 30 minutes and counts a session as idle
  only when its last complete line ends a turn. A partial or unreadable last line defers. It reads no prompt text. It names every busy rollout, each matched to an Orca
  terminal through the Codex session markers' transcript path or reported as `outside_orca`, and the script asks one
  `codex_install` question per busy session; it presses Esc in a Codex session only after an `interrupt` answer, once, after
  every `wait` session is idle, and types nothing else into a busy Codex session.
- A command goes only to a connected, writable terminal whose input line is empty or was cleared as below, and that
  is idle or is a Claude Code session in a turn in progress other than the one running the skill. For such a busy
  session the script types `/reload-plugins`, and `/compact` when stale, as queued commands after the same input
  checks, a draft recheck, and a recheck that the turn is still running, types held text back at once, and sends
  nothing more to it while a queued command has not run and its turn is busy. It types nothing, deletes nothing, and
  asks the user (`awaiting_answer`) when a dialog is open, the input cannot be restored exactly, a plugin changed in
  this run may need `--force`, orchestration mail is pending, or the turn record or input line cannot be read. No
  answer authorizes `--force`; `references/busy-sessions.md` holds the reasons and options.
  The host's own turn record decides idle or busy first and is read again right before each send, where an
  undecided record needs `tui-idle` too; a Claude Code transcript whose newest turn has ended with no background
  task, subagent, or scheduled wakeup owing a notification, also anywhere earlier in the file, or that ends with a
  finished slash command and either nothing active before it or, when the file is unchanged for 300 seconds, an
  earlier turn with no end record, means idle, even when no record follows the handoff, except that a turn ended
  with only a background task, subagent, or wakeup owing a notification means idle only for the session's next action
  when that is `/reload-plugins`, which keeps the process and its tasks, and `/compact` or `/clear` remaining after it
  waits. When the next action is `/compact` or `/clear`, or the step is `resume`, which ends the tasks, the session is
  not ready (`background_task`), and Orca's `tui-idle` never overrides that; it is sent once a turn ends with nothing
  owed. A session still waiting for that reason at the one-hour deadline ends as `not_idle_before_deadline`. A turn
  in progress means busy, and a Codex rollout's last complete line decides the same way. When the record is missing,
  partial, or not decisive, Orca's `tui-idle` decides. A short race remains.
- Orca delivers an orchestration mail notice by typing it into an idle agent's input line and pressing Enter,
  which submits whatever is already on the line. Before it probes, sends, or types held input back, the script
  reads Orca's orchestration inbox and leaves a session alone while mail Orca will announce to it is unread or the
  inbox cannot be read. Held input is typed back after two minutes even then, so it is not lost. Mail that arrives
  during the probe or the send itself remains a race.
- Orca hides the Claude Code input line from the screen and reports it as a draft, which also carries Claude
  Code's grey prompt suggestion. When a draft stays unchanged for five seconds, the script types one character
  and deletes it only when the draft shows exactly that character: a suggestion is replaced and typed text is
  extended, and both come back unchanged. When the probe shows typed text of one line without a paste or image
  placeholder or a leading `-`, the script keeps it only in memory, clears it with backspaces, sends the commands,
  and types it back without Enter once the last action is confirmed or fails, or before the session is handed to
  the helper, completing a line that a failed clear left partly cleared; a crash between the clear and the restore
  loses it. Input that cannot be restored exactly is cleared the same way before the refresh is applied, the
  report says `cleared`, and the cleared input is not kept anywhere.
  When a check is interrupted but the draft then returns to its earlier state or empties, no character of the
  script's remains, so it checks again later, up to three more times. The script checks the draft again just before
  each send.
- `/clear` runs only after Claude Code refuses to compact and the transcript, read again right before the send,
  holds no prompt.
- Each result is confirmed from transcript records appended after the send, or from a marker rewritten after it,
  and from the screen only when no transcript is available.
- One lock covers every process that sends commands. The detached helper holds it only while it sends to a session
  and confirms the command, never while it waits for a session to become idle, so `apply` can run meanwhile.
- Each run starts at most one helper, which also carries a pending Codex install job for at most one hour. Sessions a later `apply` defers join the running helper. It ends every Orca wait it started before it exits, and its deferred
  sessions and this session wait at most one hour; a queued command still unconfirmed then ends `queued_unconfirmed`.
- When the Orca idle wait fails for a session, the helper checks that session by polling until its deadline.
- `/compact` summarizes the conversation, so it runs only for sessions whose instructions are stale.
- A Codex session that was compacted loads the new instructions at its next turn; the report says so.
- Only Orca-managed terminals are reached. Codex sessions outside Orca still count in the install gate when they
  wrote a rollout file in the last 30 minutes, and are asked about with `wait` and `skip` only.
- Manual updates outside this workflow and another process deleting a loaded plugin directory remain outside
  this skill's enforcement boundary.
- Run state lives under `~/.local/state/hei5enbug-agent-setup/orca-plugin-refresh/`, or under
  `$XDG_STATE_HOME` when it is set, and markers live under Orca's user-data directory. Neither stores prompts
  or transcripts.
