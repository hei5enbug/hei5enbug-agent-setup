# Claude Code mod

This page explains Claude Code mod compatibility, role pinning, transcript views, and secret redaction.

On Claude Code, `config/claude-mod.json` loads the mod `hooks/mod/register.js`, which holds the Claude-only guards: the
built-in subagent block, role pinning, the GPT refusal, and the zsh equals-word block. The [Approval
guard](approval-guard.md#approval-guard) holds approvals on both hosts. The mod is verified on Claude Code 2.1.307 and
later, the oldest version whose `claude plugin test` run passes. That run fails on 2.1.306 and earlier, and 2.1.292 also
refuses to load a hook module that passes `$` into a function imported from another file. The plugin manifest has no
field that declares a minimum Claude Code version. When the mod does not load, such as on an older Claude Code, with
`disableAllHooks`, or under a managed policy, these guards are absent and the host's normal permission flow applies.

The zsh equals-word block applies when the Bash tool runs zsh: `CLAUDE_CODE_SHELL` names a zsh binary or, when it does
not name bash or zsh, `$SHELL` does; when neither names bash or zsh, the mod assumes zsh. In zsh, an unquoted word that
starts with `=` becomes a command path, so `echo =====` fails before the rest of the command runs. The mod's
`tool.check` hook denies such a command with a hint to quote the word, and it ignores quoted text, `[[ ... ]]`, `(( ...
))`, here-documents, and comments. A command the check cannot parse is allowed. A word counts as a declaration builtin
such as `export` or a keyword such as `if` only where a command may start, so `printf '%s\n' export x==foo` is allowed.

Role pinning pins each plugin role's model and effort on every request: `scout` uses `claude-sonnet-5-5` with `medium`,
`worker` uses `worker_model` with `worker_effort` (default `claude-haiku-5-5` with `high`), `sonnet-worker` uses
`claude-sonnet-5-5` with `high`, `designer` uses `claude-opus-5-5` with `xhigh`, and `reviewer` uses `claude-opus-5-5`
with `high`. A subagent that answers on another model is stopped: its later requests end with a refusal, its tool calls
are denied, and its result is replaced with a warning. The one exception is a model or effort the user names in their
own latest main-session prompt for delegated work: the mod runs an Agent call that carries that model on it, or an Agent
call that carries the role's own pinned model when only an effort is named, with the named effort when exactly one is
named and the model allows it, and checks the run against those values. Text in a pasted block or a fenced code block
(opened by three or more backticks or tildes) does not count, and the next prompt without a request returns to the pins.
Only when role pinning is active, the registered mod `prompt.submit` hook adds the line `hei5enbug-agent-setup mod: role
pinning active` as context to the first main-session prompt of each conversation, again after `/clear` or `/resume`.
This line lets the main session send assignments directly and skip per-delegation settings and subagent record checks.
The mod uses no `prompt.context` or `classic.*` hook, because Claude Code's built-in guard `cc-plugin-sec-default`,
which loads with managed settings or a Team or Enterprise login, skips those hooks in every mod a user installs.

The mod also draws two views; neither adds anything to the model's context. With `risk_highlight` on, each tool call row
in the transcript gets a colored label from the approval guard's own decision for that call: red for an irreversible or
every-time call and yellow for a write. When it can be read safely within a few seconds, a line under a red call's label
also shows what the call would change, such as the files and lines `git reset --hard` would discard, the files `git
clean` would delete, or the resources `kubectl delete` would remove. The preview appears on the collapsed row of the
normal transcript too, follows the response language, and is cut at the row's edge instead of wrapping, as the label is.
The decision stays in the permission prompt. With `work_board` on, a one-line summary above the prompt shows context
use, the prompt-cache hit rate, the Claude 5-hour and weekly use, and the Codex weekly use, with a limit colored when it
would run out before it resets, plus the running subagents and edit conflicts when there are any. `/work-board` opens a
pane, 40 columns wide unless you resized it, with each subagent's status, elapsed time, and edited files, marks a file
red when two of them edit it, and shows the full usage rows with a pace forecast.

With `secret_redaction` on, the mod masks well-known secret formats in Bash, Read, Grep, and MCP results before Claude
reads them, such as cloud and service API keys, private key blocks, JWTs, and passwords in URLs, and leaves variable
names and placeholders alone. Each match becomes `[REDACTED:<kind>:<id>]`, where the id is issued in that session. An
edit or write whose new text contains an issued marker is denied, for a new file and an existing one, because it would
save the marker instead of the secret; the denial follows the response language. Text that merely mentions such a
marker, as documentation and tests do, is allowed. `config/secret-patterns.json` holds the formats, which the approval
guard also uses when it shows a command, and only the first 4 MB of a result is scanned.
