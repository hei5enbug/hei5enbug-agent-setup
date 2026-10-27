---
name: orca-plugin-refresh
description: >-
  Refresh hei5enbug-agent-setup and any other plugins the user names in Claude Code and Codex, then apply the
  installed versions to idle Orca-managed sessions, waiting up to one hour for busy ones. Claude Code installs
  at any time; a Codex install waits until no Codex turn is running. Use apply-installed when installation is
  already complete and the user asks to refresh running sessions.
compatibility: >-
  Requires macOS or Linux, Python 3.12+, and the user-scope hei5enbug-agent-setup plugin from the hei5enbug
  marketplace. The claude and codex CLIs read installed versions and update the installs. Applying to
  sessions requires an Orca terminal and the Orca CLI.
---

# Orca Plugin Refresh

Use this English `SKILL.md` as the only executable source.

This skill updates `hei5enbug-agent-setup` and the other plugins the user chose, then applies the installed
versions to running Orca sessions without ending them. It never restarts a session or replaces a conversation.

## How an update reaches a running session

| Part | Claude Code | Codex |
|---|---|---|
| Skills, agents, and hooks | `/reload-plugins` reloads every plugin | The next turn picks up the new install automatically |
| Session instructions | `/compact` | `/compact`; the session loads them on its next turn |

The plugin's session-start hook writes one marker per Orca terminal with the host, plugin directory, transcript
path, and a digest of the executable instructions. Only the terminal's interactive session writes it; a child
`claude -p` or `codex exec` started inside that terminal does not. When Orca's terminal record names no agent, the
script treats the terminal as the marker's host only while that host's input line ends the screen, so a shell left
behind with an old marker is never targeted. The script compacts only a session whose marker
is missing, holds another digest, points a Codex session at a replaced plugin directory, or points a Claude Code
session at a removed one. Only this plugin's instruction digest decides this, not the other plugins. When Claude
Code answers that a session has too few messages to compact and its transcript holds no prompt, the script sends
`/clear` instead, because an empty session has nothing to lose. A Codex session that never ran a turn needs
nothing: its first turn loads the new instructions.

## Workflow

Let `<script>` be `scripts/orca_plugin_refresh.py` in the directory that holds this `SKILL.md`.

1. **Choose the install path.** To install a new version, run `python3 <script> update --json`. To refresh other
   plugins with it, pass each ID the user named as `--also <plugin@marketplace>`; the flag is repeatable and
   works on `apply-installed` too. Without `--also`, the script uses the `HEI5ENBUG_REFRESH_PLUGINS` environment
   variable (comma-separated IDs), then the saved `refresh_plugins` plugin option. The first non-empty source wins.
   Never invent an ID. An invalid ID returns `plugin_id_invalid` with its position and runs nothing; ask the user
   for the corrected ID. The script drops duplicates and this plugin's own ID and keeps at most 10 companions;
   `companions_dropped` reports any extras. If installation was already completed outside this skill, or the user
   asks to apply the installed version, run `python3 <script> apply-installed --json`; it reads installed roots
   and runs no marketplace or install commands.
2. **Handle the update result.** Report each host's version change, then every plugin in
   `hosts.<host>.plugins` with its status, versions, and warnings:
   - `updated` or `current`: the version changed or stayed, and the install validated.
   - `not_installed`: not installed and enabled exactly once on that host; nothing ran.
   - `local_source`: the plugin loads from a local folder, so the script never installs it and uncommitted code is
     never deployed. Claude Code reloads that folder with `/reload-plugins`.
   - `deferred`: the host's install gate held it back; see the Codex gate below.
   - `error`: report its `code` and `message`. It never blocks this plugin or the session apply.

   When this plugin itself loads from a local source on a host, that host reports `local_source: true`, runs no
   install command, and stays usable for `apply`. When this plugin's host has an `error`, report its code and
   message; that host's sessions stay untouched.
   Claude Code installs at any time, because an update adds the new version beside the old one and running
   sessions keep their loaded directory until `/reload-plugins`. A Codex update deletes the old install, so the
   script defers it with `update_deferred_active_session` when the caller is inside a Codex turn,
   `codex_turn_in_progress` when a Codex session from the last 30 minutes has not ended its turn, or
   `update_deferred_unknown_session_state` when the Codex sessions cannot be read. Report a deferred Codex host
   with its `root` and `recovery_command` (which repeats the resolved companions as `--also`), and tell the user
   to run `update` again after the Codex turn ends. Do not retry on your own. The gate is checked again right
   before each Codex install, so a turn that starts mid-run defers that plugin and every later Codex install; the
   companions it held back are `deferred`, and Claude Code is unaffected. Use the returned
   `script` path for every later command, because a Codex update deletes the installation this skill was loaded
   from. Report every warning:
   - `unreleased_same_version`: Claude Code keeps its installed copy because the version did not change. Tell
     the user these files reach Claude Code only after a version bump.
   - `codex_hooks_need_trust`: the plugin's hook definitions changed, appeared, or disappeared, or a plugin with
     hooks changed any file, because Codex ties hook trust to every plugin file. Ask the user to trust that
     plugin's hooks in Codex `/hooks`; Codex skips untrusted hooks.
   - `unreleased_check_unavailable`: the script could not tell whether Claude Code missed same-version files.
     Report the reason.
3. **Apply to the sessions.** When this plugin's host update succeeded, or `apply-installed` returned that host
   without an error, run `python3 <script> apply --run-id <run_id> --json` in the foreground with a shell timeout
   of at least 600 seconds. Do not ask the user to confirm this step; the script's checks decide which sessions
   receive commands. For about 20 seconds the script sends a command only to an idle session whose input line is
   empty, then keeps confirming the commands already sent. It hands every session that is still busy or not ready
   to one detached helper as `deferred` instead of waiting. An `already_running` error means another run is still
   sending; wait for it, then run `apply` again. A host with an update error stays blocked while successful hosts
   can proceed.
4. **Report every session.** Show the terminal suffix, host, worktree, status, completed actions, and detail:
   - `done`: every needed action is confirmed. `already_current` means nothing was needed, and
     `fresh_session_loads_on_first_turn` marks a Codex session that never ran a turn. The note
     `empty_session_cleared` marks an empty Claude Code session that got `/clear`, and
     `instructions_load_on_next_turn` marks a compacted Codex session.
   - `skipped`: the session stayed busy, kept unsent input, showed an unreadable input line, changed its input
     just before the send, reached the deadline, or closed.
   - `failed`: an action was sent but not confirmed, or Claude Code refused it. A reload refusal that asks for
     `--force` means a plugin's MCP tools changed; do not force it without the user's approval.
     `compact_needs_more_messages` means the conversation is too short to compact; its instructions refresh at
     its next compaction or restart. `probe_interrupted_check_input` means the input line changed while the
     script checked it and did not return to its earlier state, or such checks kept being interrupted; tell the user to check that session's input line for a stray `x`, because the script
     never deletes input it did not type. `helper_start_failed` means this session's follow-up could not start;
     run `apply` again.
   - `blocked`: that host's plugin update failed or its installed manifest, hook targets, or instruction digest
     did not validate.
   - `deferred`: the session was busy or not ready, so the detached helper finishes it; see step 5.
   - `queued_after_turn`: this session itself; see step 5.
5. **Let the helper finish.** When `apply` reports `deferred` or `queued_after_turn`, report the first results
   and end the turn. One detached helper waits on Orca's idle callback (`orca terminal wait --for tui-idle`) for
   every deferred session at once and for this session. When a session reports idle, the helper confirms it
   again after three seconds, checks that the installed plugin still matches the run and that the session has
   not already loaded the new instructions, and only then sends the remaining actions. A session deferred for
   another reason, such as an unreadable input line, is checked again on every poll. A deferred session that is
   not ready within one hour of the handoff stays unsent, as `not_idle_before_deadline` or with its last reason.
   A session whose terminal closes is skipped at once as `terminal_gone`, and its wait ends. The status shows each
   session's final result as soon as it is reached, so `status` reports progress while the helper runs.
   After every session finishes, the helper sends this session one prompt that asks to run
   `python3 <script> status --run-id <run_id> --json`, ends all of its Orca waits, and exits. When that prompt
   arrives, run it and report every session, with the companion statuses from `hosts`; `not_refreshed` lists the
   sessions that did not receive the update. When `self_notification` in the status is not `sent`, the prompt
   could not be delivered; the status still holds the result.

`--compact` defaults to `auto`, which compacts only stale sessions. Pass `--compact always` or `--compact never`
only when the user explicitly asks for it. `plan` and `self-apply` are internal subcommands that the script uses
itself; never run them by hand. Never send commands to Orca terminals by hand, never exit or restart a session,
and never pass `--force` on your own.

The script exits with `0` when every session is `done`, `deferred`, or `queued_after_turn`, or when the update or
`apply-installed` result is ok. It exits with `2` otherwise, and on a usage error. An update or `apply-installed`
result is not ok when this plugin has a host error or any companion has the status `error`.

## Safety and limits

- Commands are argument lists, never a shell. Each host updates a marketplace at most once per run, then the
  plugin: Claude Code runs `claude plugin marketplace update` and `claude plugin update`, and Codex runs
  `codex plugin marketplace upgrade` and `codex plugin add`.
- Before reporting an install as successful, the script checks the installed manifest name and version and every
  hook target that points into the plugin directory. For this plugin it also checks every required hook target,
  the Claude Code mod files, and the instruction digest. A failed plugin does not hide another plugin's or host's
  successful result.
- The Codex gate reads only Codex rollout files modified in the last 30 minutes and counts a session as idle
  only when its last complete line ends a turn. A partial or unreadable last line defers. It reads no prompt text.
- A command goes only to a connected, writable, idle terminal whose input line is empty. A short race between
  that check and the send remains.
- Orca hides the Claude Code input line from the screen and reports it as a draft, which also carries Claude
  Code's grey prompt suggestion. When a draft stays unchanged for five seconds, the script types one character
  and deletes it only when the draft shows exactly that character: a suggestion is replaced and typed text is
  extended, and both come back unchanged. A session with typed text is skipped, never sent to. When a check is interrupted but the draft then
  returns to its earlier state or empties, no character of the script's remains, so it checks again later, up to
  three more times. The script checks the draft again just before each send.
- `/clear` runs only after Claude Code refuses to compact and the transcript, read again right before the send,
  holds no prompt.
- Each result is confirmed from transcript records appended after the send, or from a marker rewritten after it,
  and from the screen only when no transcript is available.
- One lock covers every process that sends commands, including the detached helper.
- Each run starts at most one helper. It ends every Orca wait it started before it exits, and its deferred
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
