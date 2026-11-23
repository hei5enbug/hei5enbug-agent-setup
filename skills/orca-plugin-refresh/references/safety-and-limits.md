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
  only when its last complete line ends a turn. A partial or unreadable last line defers. It reads no prompt text.
- A command goes only to a connected, writable, idle terminal whose input line is empty or was cleared as below.
  The host's own turn record decides idle or busy first and is read again right before each send, where an
  undecided record needs `tui-idle` too; a Claude Code transcript whose newest turn has ended with no background
  task, subagent, or scheduled wakeup owing a notification, also anywhere earlier in the file, or that ends with a
  finished slash command and either nothing active before it or, when the file is unchanged for 300 seconds, an
  earlier turn with no end record, means idle, even when no record follows the handoff, except that a turn ended
  with only a background task, subagent, or wakeup owing a notification means idle only while the session's remaining
  actions are just `/reload-plugins`, which keeps the process and its tasks; with `/compact` or `/clear` still to send,
  or for `resume`, which ends them, it is not ready. A turn
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
- Each run starts at most one helper. Sessions a later `apply` defers join the running helper. It ends every Orca wait it started before it exits, and its deferred
  sessions and this session wait at most one hour.
- When the Orca idle wait fails for a session, the helper checks that session by polling until its deadline.
- `/compact` summarizes the conversation, so it runs only for sessions whose instructions are stale.
- A Codex session that was compacted loads the new instructions at its next turn; the report says so.
- Only Orca-managed terminals are reached. Codex sessions outside Orca still count in the install gate when they
  wrote a rollout file in the last 30 minutes.
- Manual updates outside this workflow and another process deleting a loaded plugin directory remain outside
  this skill's enforcement boundary.
- Run state lives under `~/.local/state/hei5enbug-agent-setup/orca-plugin-refresh/`, or under
  `$XDG_STATE_HOME` when it is set, and markers live under Orca's user-data directory. Neither stores prompts
  or transcripts.
