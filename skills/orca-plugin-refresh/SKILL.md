---
name: orca-plugin-refresh
description: >-
  Update hei5enbug-agent-setup and any plugins the user names in Claude Code and Codex, then apply the installed
  versions to running Orca agent sessions: reload or compact idle ones, queue commands into busy Claude Code ones
  and ask where applying could disturb work, resume ones on an older Claude Code release or a replaced Codex plugin
  folder, and ask about busy Codex sessions that hold back the Codex update. Use for requests to refresh or restart
  running Orca sessions on a newer Claude Code release or to apply an installed update to them, even without the
  skill's name; use apply-installed when installation is already done. Not for creating worktrees, reading
  terminals, or Orca browser work.
compatibility: >-
  Requires macOS or Linux, Python 3.12+, and the user-scope hei5enbug-agent-setup plugin from the hei5enbug
  marketplace. The claude and codex CLIs read installed versions and update the installs. Applying to
  sessions requires an Orca terminal and the Orca CLI.
---

# Orca Plugin Refresh

Use this English `SKILL.md` as the only executable source.

This skill updates `hei5enbug-agent-setup` and the other plugins the user chose, then applies the installed
versions to running Orca sessions without ending them. It never restarts a session or replaces a conversation,
except that `apply` first resumes, without asking, a Claude Code session on an older release or an idle Codex session on
a replaced plugin folder that passes every resume check (step 3), and the user can approve one a check held back (step 6).

## How an update reaches a running session

| Part | Claude Code | Codex |
|---|---|---|
| Skills, agents, and hooks | `/reload-plugins` reloads every plugin | A session with a replaced plugin folder is resumed |
| Session instructions | `/compact` | `/compact`; the session loads them on its next turn |

The plugin's session-start hook writes one marker per Orca terminal with the host, plugin directory, transcript
path, and a digest of the executable instructions. Only the terminal's interactive session writes it; a child
`claude -p` or `codex exec` started inside that terminal does not. When Orca's terminal record names no agent, the
script treats the terminal as the marker's host only while that host's input line ends the screen, so a shell left
behind with an old marker is never targeted. The script compacts only a session whose marker
is missing, holds another digest, points a Codex session at a replaced plugin directory, or points a Claude Code
session at a removed one. A Codex process that predates a replacement follows the resume rule instead.
Only this plugin's instruction digest decides compaction, not the other plugins. When Claude
Code answers that a session has too few messages to compact and its transcript holds no prompt, the script sends
`/clear` instead, because an empty session has nothing to lose. A Codex session that never ran a turn needs
nothing: its first turn loads the new instructions.

## Workflow

Let `<script>` be `scripts/orca_plugin_refresh.py` in the directory that holds this `SKILL.md`.

Before updating Codex plugins or reporting their hook-trust warnings, read `references/codex-releases.md`.
Before asking a question the script returns in `questions`, or running `decide`, read `references/busy-sessions.md`.

1. **Choose the install path.** To install a new version, run `python3 <script> refresh --json` once: it runs the
   update, then step 3's `apply` and step 7's `orphans` on the returned run id, and prints one JSON object with the
   sections `update`, `apply`, and `orphans`. To refresh other plugins with it, pass each ID the user named as `--also <plugin@marketplace>`; the flag is repeatable and
   works with `--installed` too. Without `--also`, the script uses the `HEI5ENBUG_REFRESH_PLUGINS` environment
   variable (comma-separated IDs), then the saved `refresh_plugins` plugin option. The first non-empty source wins.
   Never invent an ID. An invalid ID returns `plugin_id_invalid` with its position and runs nothing; ask the user
   for the corrected ID. The script drops duplicates and this plugin's own ID and keeps at most 10 companions;
   `companions_dropped` reports any extras. If installation was already completed outside this skill, or the user
   asks to apply the installed version, run `python3 <script> refresh --installed --json`; it reads installed roots
   and runs no plugin marketplace or install commands. Both commands first run `claude update` once, so sessions
   compare against the newest Claude Code release, unless `DISABLE_UPDATES` turns updates off or `claude` is not
   on `PATH`; run them with a shell timeout of at least 600 seconds.
2. **Handle the update result.** From the `update` section, report each host's version change, then every plugin in
   `hosts.<host>.plugins` with its status, versions, and warnings:
   - `updated` or `current`: the version changed or stayed, and the install validated.
   - `not_installed`: not installed and enabled exactly once on that host; nothing ran.
   - `local_source`: the plugin loads from a local folder, so the script never installs it and uncommitted code is
     never deployed. Claude Code reloads that folder with `/reload-plugins`.
   - `deferred`: the host's install gate held it back; see the Codex gate below.
   - `error`: report its `code` and `message`. It never blocks this plugin or the session apply.

   Also report `hosts.claude.claude_code`: its `status` (`updated`, `current`, `skipped`, or `failed`), `before` and
   `after` releases, the `reason` of a skip, and `exit_status` and `detail` of a failure with its
   `claude_update_failed` warning, which never blocks the plugin result or `apply`.

   When this plugin itself loads from a local source on a host, that host reports `local_source: true`, runs no
   install command, and stays usable for `apply`. When this plugin's host has an `error`, report its code and
   message; that host's sessions stay untouched.
   Claude Code installs at any time, because an update adds the new version beside the old one and running
   sessions keep their loaded directory until `/reload-plugins`. A Codex update deletes the old install, so the
   script defers it with `update_deferred_active_session` when the caller is inside a Codex turn,
   `codex_turn_in_progress` when a Codex session from the last 30 minutes has not ended its turn, or
   `update_deferred_unknown_session_state` when the Codex sessions cannot be read. Report a deferred Codex host
   with its `root`. For the first two codes `questions` holds one `codex_install` question per busy session: ask them
   as step 3 says, then run `decide`, which installs after the turns end with no rerun. For the third, give its
   `recovery_command` and tell the user to run `update` again; do not retry on your own. The gate is checked again right
   before each Codex install, so a turn that starts mid-run defers that plugin and every later Codex install; the
   companions it held back are `deferred`, and Claude Code is unaffected. Use the returned
   `script` path for every later command, because a Codex update deletes the installation this skill was loaded
   from. Report every warning:
   - `unreleased_same_version`: Claude Code keeps its installed copy because the version did not change. Tell
     the user these files reach Claude Code only after a version bump.
   - `unreleased_check_unavailable`: the script could not tell whether Claude Code missed same-version files.
     Report the reason.
   - `claude_home_project_record`: a session ran in the home folder, so Claude Code listed the user install a second
     time as a home-folder project install of the same copy. The script treated them as one install; nothing to do.
3. **Apply to the sessions.** When this plugin's host update succeeded, or the installed-only run returned that host
   without an error, `refresh` runs `apply` itself, in the foreground within the shell timeout of step 1, and its
   `apply` section holds the result; when every host has an error, the output holds only `update`. Do not ask the
   user to confirm this step; the script's checks decide which sessions receive commands. For about 20 seconds the script sends a command to an idle session whose input line is
   empty or cleared of typed text, or types it into a busy Claude Code session as a queued command, then keeps
   confirming the commands already sent and restoring any text it can restore exactly. It hands every session that is
   still busy or not ready to one detached helper as `deferred` instead of waiting. When the output holds `questions`, ask each unanswered one with
   the question tool as soon as the script returns, before any other report, then run `decide`. An `already_running` error means another run is sending at this moment; wait for it, then run `apply` again. A host with an update error stays blocked while successful hosts
   can proceed. Before it sends anything, `apply` resumes each other Claude Code session that reports
   `host_release_outdated` and each other Codex session on a replaced plugin folder that passes every resume check (the helper
   resumes a busy one after its turn); a resumed session gets no `/reload-plugins`, and `/compact` afterwards only when its
   instructions are stale. Before reporting a session that `apply` resumed or
   tried to resume, read `references/resume.md`.
4. **Report every session.** Show the terminal suffix, host, worktree, status, completed actions, and detail:
   - `done`: every needed action is confirmed. `already_current` means nothing was needed, and
     `fresh_session_loads_on_first_turn` marks a Codex session that never ran a turn. The note
     `empty_session_cleared` marks an empty Claude Code session that got `/clear`, and
     `instructions_load_on_next_turn` marks a compacted Codex session, and
     `applied_by_session` marks a session that ran `/reload-plugins` itself after the handoff, and
     `instructions_on_next_compaction` marks a Claude Code session with prompts whose `/compact` was refused as
     too short after the reload was confirmed; its instructions refresh at its next compaction or restart.
   - `skipped`: the session stayed busy, showed an unreadable input line, changed its input just before the send,
     reached the deadline, or closed. `terminal_orphaned` means an orphaned terminal (its Orca tab was closed) is not
     connected or not writable; a refreshed orphaned session reports `orphaned`. `input_clear_failed` means the line could not be cleared, so nothing was sent
     (`input` is `clear_failed`), or that the script typed the text back. `orchestration_mail_pending` means Orca
     still held unread orchestration mail for the session, or could not say, so nothing was typed or sent. `queued_unconfirmed` means queued commands were not confirmed within an hour and may still run.
   - Every session also reports `ready_signal` (`host_record` or `tui_idle`, the signal that allowed the send) and,
     when it held input, `input` (`restored`, or `cleared` for input that could not be restored exactly).
     A Claude Code session also reports its `release`, and `host_release_outdated` with both versions when it runs
     an older release than the installed one or its executable is gone.
   - `failed`: an action was sent but not confirmed, or Claude Code refused it. `plugin_load_error` means the
     reload answered with `N error(s) during load` or loaded fewer plugins than are enabled; `plugin_load` holds
     the reported counts. A reload refusal that asks for
     `--force` means a plugin's MCP tools changed; do not force it without the user's approval.
     `compact_dialog_open` means `/compact` opened a dialog other than the
     "acts on the main conversation, not this agent" one, which the script leaves open without sending a key; that
     one it answers by moving the selection to `Run /compact on the main conversation` and never confirming
     `Cancel`. `probe_interrupted_check_input` means the input line changed while the
     script checked it and did not return to its earlier state, or such checks kept being interrupted; tell the
     user to check that session's input line for a stray `x`, because the script never deletes input it did not
     type. `probe_character_left` means the same with the stray `x` at `probe_position` (1-based) in the line.
     `input_restore_unconfirmed` means the saved text was not confirmed back on the input line, and
     `input_not_restored_line_in_use` means the user typed new text, so the saved text was not typed back and is
     gone; tell the user to check that session's input line. `helper_start_failed` means this session's follow-up
     could not start; run `apply` again.
   - `blocked`: that host's plugin update failed or its installed manifest, hook targets, or instruction digest
     did not validate.
   - `deferred`: the session was busy or not ready, so the detached helper finishes it; see step 5; `commands_queued` means its commands are typed in and wait for the turn.
   - `awaiting_answer`: nothing was typed; the session waits for the user's answer to its question.
   - `queued_after_turn`: this session itself; see step 5.
5. **Let the helper finish.** When `apply` reports `deferred` or `queued_after_turn`, report the first results
   and end the turn. One detached helper watches every deferred session and this session. Each session's own turn
   record decides first, and Orca's idle callback (`orca terminal wait --for tui-idle`) decides only when the
   record cannot. When a session reports idle, the helper confirms it again after three seconds, checks that the
   installed plugin still matches the run and that the session has not already loaded the new instructions, and
   only then sends the remaining actions; while a background task, subagent, or wakeup still owes a notification, only
   `/reload-plugins` is sent, and `/compact` or `/clear` waits for the turn that leaves nothing owed. A session deferred for another reason, such as an unreadable input line,
   is checked again on every poll. A Claude Code session's reload stays owed until its transcript after the handoff
   holds a successful reload or its marker was rewritten after the handoff with source `startup` or `resume`; a marker
   rewritten by a compaction or a clear never settles it, whatever root it names, because only a new process loads
   every installed plugin. A deferred session that is not ready within one hour of the handoff stays
   unsent, as `not_idle_before_deadline` or with its last reason.
   A session whose terminal closes is skipped at once as `terminal_gone`, and its wait ends. The status shows each
   session's final result as soon as it is reached, so `status` reports progress while the helper runs.
   When `others_finished_at` is set and only this session is still `queued_after_turn`, every other session is final,
   so report them without waiting; this session's actions run after its turn ends, or count as done once the user
   runs `/reload-plugins` (and `/compact` when listed) in it.
   After every session finishes, the helper sends this session one prompt that asks to run
   `python3 <script> status --run-id <run_id> --json`, ends all of its Orca waits, and exits. When that prompt
   arrives, run it and report every session, with the companion statuses from `hosts`; `not_refreshed` lists the
   sessions that did not receive the update. When `self_notification` in the status is not `sent`, the prompt
   could not be delivered; the status still holds the result.
6. **Offer the resume.** Show once every session that reports `resume_approval_needed` (`plugin_load_error`, or
   `codex_plugin_folder_replaced` or `host_release_outdated` with the failed check in `resume_check`) and ask which the user approves; fixing one ends
   it and resumes the same conversation.
   Before running `resume`, read `references/resume.md`, and run it only for the approved terminals.
7. **Offer to close orphaned terminals.** From the `orphans` section, show each orphaned
   agent terminal with host, worktree, and idle time, and name the `failed_check` of each one not recommended. Ask the
   user once which `recommended` terminals to close. Before running `close`, read `references/orphaned-terminals.md`,
   and run it only for the approved terminals.

`--compact` defaults to `auto`, which compacts only stale sessions. Pass `--compact always` or `--compact never`
only when the user explicitly asks for it. `plan` and `self-apply` are internal subcommands that the script uses
itself; never run them by hand. Never send commands to Orca terminals by hand, except to finish a session the script
skipped: only with the user's approval for that session and after the checks in `references/manual-finish.md`
(read it first), and record every result with `record-manual`. Never end a session except through `resume`, for one
the user approved in this request, through the resume in `apply` or in the Codex install `decide` starts, through `decide` with the interrupt answer, or by hand as `references/manual-finish.md`
describes for a skipped session the user approved; never close a terminal except through `close`,
for one the user approved in this request; and never pass `--force` on your own.

The script exits with `0` when every session is `done`, `deferred`, `awaiting_answer`, or `queued_after_turn`, or when the update or
`apply-installed` result is ok. It exits with `2` otherwise, and on a usage error. An update or `apply-installed`
result is not ok when this plugin has a host error or any companion has the status `error`. `refresh` exits `0` only when its
update result is ok and every session is `done`, `deferred`, `awaiting_answer`, or `queued_after_turn`.

Before explaining to the user why the script skipped, deferred, or failed a session, and before a manual finish, read `references/safety-and-limits.md`.
