# Delegation and final review

These repository development rules extend `AGENTS.md`. They override the plugin's model and effort routes for the roles
below and assign mechanical documentation work to `writer`; the final review table chooses each final reviewer. All
other plugin ownership, permission, and verification rules still apply.

## Roles

For repository implementation, use a Claude Code plugin worker subagent by default. Codex project roles in
`.codex/agents/` cover the other routes:

| Role | Primary name | Model / effort | Fallback name | Model / effort |
|---|---|---|---|---|
| Bounded implementation and debugging, easy work | `haiku_worker` | `claude-haiku-5-5` / `xhigh` | `worker` | `gpt-6.2-sol` / `high` |
| Bounded local, read-only evidence | `scout` | `gpt-6-luna` / `xhigh` | `haiku_scout` | `claude-haiku-5-5` / `xhigh` |
| Mechanical documentation edits with approved content | `writer` | `gpt-6.1-sol` / `high` | `haiku_writer` | `claude-haiku-5-5` / `xhigh` |
| One read-only final review, when the final review table below chooses `gpt-6.1-terra` at `high` | `code_reviewer` | `gpt-6.1-terra` / `high` | `opus_code_reviewer` | `claude-opus-5-5` / `high` |

- `haiku_worker` and `sonnet_worker` name the plugin's `hei5enbug-agent-setup:worker` and
  `hei5enbug-agent-setup:sonnet-worker` subagents. The other `haiku_*` names and `opus_code_reviewer` are assignment
  labels for separate Claude Code CLI processes, not registered `--agent` names. `worker`, `scout`, `writer`, and
  `code_reviewer` are Codex project roles, which take effect in a fresh Codex session.
- Route easy work to `scout` for bounded, local, read-only evidence and to `writer` for coordinator-approved mechanical
  Markdown and mirror edits. In Claude Code, run `writer` as `role_runner.py language` with its role definition as
  `--instructions`.
- Keep problem definition, complex root-cause reasoning, plans, designs and RFCs, and acceptance decisions in the main
  session. The `designer` and `reviewer` roles keep their existing host routes.
- Request the listed model and effort explicitly when the host supports it, and verify the actual host rollout before
  relying on either a primary or a fallback role. Do not override a plugin agent definition or put an Anthropic model
  in a Codex role.

## Implementation worker

Before assigning implementation, the main session defines the cause, allowed edit paths, change requirements, and
runnable acceptance checks. It chooses the worker by difficulty and usage:

| Work | Worker |
|---|---|
| Easy: one cohesive change with a stated edit and checks that cover it fully | `haiku_worker`: the `hei5enbug-agent-setup:worker` subagent while the session line "Worker agent model" shows `claude-haiku-5-5` at `xhigh`; otherwise `sonnet_worker` |
| Normal or hard: a behavioral change, several files, parsing, security, or concurrency | `sonnet_worker`: the `hei5enbug-agent-setup:sonnet-worker` subagent (`claude-sonnet-5-5` / `high`) |
| Claude usage limit reached or a Claude worker unavailable | `worker` (`gpt-6.2-sol` / `high`): in Claude Code, `role_runner.py implementation --fallback --instructions <worker role definition>` run from the folder that holds the allowed paths; in Codex, the `worker` role |

- The GPT `worker` is a fallback, and this repository's work is normal or hard, so `.codex/agents/worker.toml` pins
  `gpt-6.2-sol`. The plugin's GPT workers follow [GPT worker model by difficulty](../../instructions/model-routing.md#gpt-worker-model-by-difficulty).
- Spawn these plugin subagents instead of `claude -p` processes.
- Follow the existing readiness and actual host-record checks before relying on a worker's result. A worker reports
  new causes or missing decisions to the main session instead of widening scope.
- When comparing explicitly requested alternatives to the selected implementation route, prioritize fully solved
  tasks, then compare cost per solved task against the additional code quality when completion is comparable. Include
  failed attempts in the cost; do not collapse quality and cost into an arbitrary ratio or ignore the reports'
  measurement limits.

## Fallbacks

- Each role has exactly one fallback in the other model family: Claude to GPT or GPT to Claude. A named fallback is
  preauthorized only when the primary executable, authentication, quota, role, requested settings, or reliable
  settings evidence is unavailable.
- Announce the reason and selected route. Stop any started primary, inspect its partial work, and transfer only
  verified unfinished work with the same scope, permissions, and checks.
- Try the one listed fallback at most once per assignment; if it is also unavailable, continue in the main session.
  Skip a fallback that shares a confirmed authentication, quota, or capability blocker with the primary.
- A fallback never resolves a missing user decision or bypasses a permission or failed acceptance check.
- Do not override a pinned primary role's model to invoke its fallback; use the named route on its own host.
- These are recovery choices, not measured claims of fallback quality or cost superiority.

For a Claude fallback:

- Pass the corresponding primary Codex role's `developer_instructions` and the bounded assignment on stdin, so each
  role's scope keeps one source.
- Run `claude -p` with the table's full model ID and effort,
  `--output-format json --permission-mode dontAsk --strict-mcp-config`.
- For `haiku_scout` and `opus_code_reviewer`, add `--tools Read Grep Glob --allowedTools Read Grep Glob`.
- For `haiku_writer`, add `--tools Read Grep Glob Edit Write --allowedTools Read Grep Glob` plus
  `Edit(//<absolute allowed path>)` for each assigned Markdown file and mirror; an Edit rule also covers Write, and
  `//` marks an absolute path.
- The main session runs its assigned checks. Never expose shell, network, or delegation tools to these fallbacks.
- Accept output only when JSON `modelUsage` names the requested model and the existing effective-settings checks
  confirm the effort.

On any CLI resume, reapply the model and effort, and for a Claude fallback also its tool limits and assignment scope.

## Final review

Run one read-only final review of the combined final diff, sized to the change and to its authoring family:

| Change | Final review |
|---|---|
| Trivial: a typo, wording, version, or metadata edit, a translation, or a mechanical edit its checks fully cover | None |
| Claude-authored, not trivial | `role_runner.py reviewer` with `--model gpt-6.1-terra` or `gpt-6-astra` and `--effort high` or `xhigh`, chosen per change by its scope and risk as the plugin's independent model validation describes |
| GPT-authored, including work drafted on `gpt-6.1-sol` | `role_runner.py reviewer --model claude-fable-5-2 --effort high` |

- It runs automatically once, after all work for the request is done and its checks pass, over the combined final
  diff; any earlier review needs the user's approval.
- Give the reviewer the final diff, requirements, and check evidence.
- When the chosen reviewer is unavailable on a Claude-authored change, use the other of the two models.
- The main session verifies findings and decides acceptance; do not start a second review round.

## Evidence

These records explain the routes above; they are not rules.

- The routing is this repository's policy, not a benchmark result or a claim of general model superiority. The user
  selected Haiku `xhigh` for bounded implementation and Sol `high` for bounded final reviews as a role preference,
  not a claim that Haiku wins completion or cost efficiency on Frontier v4, or that implementation scores establish
  review accuracy.
- Frontier v4 covers 23 challenging behavioral-reconstruction tasks with one attempt per model and effort. It defines
  no easy/normal/hard labels, evaluates no documentation, and did not measure final review accuracy. Its reports use
  different harness versions and cost bases, so costs are API/list-price estimates rather than subscription bills.
  See the [Haiku comparison](https://vulcanbench.com/benchmarks/swe-v4-haiku55-vs-frontier.html),
  [Luna comparison](https://vulcanbench.com/benchmarks/swe-v4-gpt55-luna-v35.html), and
  [VulcanBench methodology](https://vulcanbench.com/methodology.html).
- The `scout` pin `gpt-6-luna`/`xhigh` follows the owner's 2026-11-20 decision (4 of 4 cases against 2 of 4 for
  `gpt-5.6-luna`, in `evals/model-roles/gpt-roles-record.json`).
- 2026-10-17, `writer`: a blind comparison of three mirror-edit assignments moved `writer` to `gpt-6.1-sol`/`high`.
  Sol passed 17 of 18 expectations with one needed fix and fewer tokens; Luna passed 9 of 18 with 19 fixes.
- 2026-10-17, implementation: three real approval-guard tasks (classification, session state, a mod) ran once each on
  Sonnet `high` and Sol `high`. All six passed the coordinator's tests. A blind review needed 5 fixes in total for Sol
  and 10 for Sonnet, and Sol used 30 to 54 percent of Sonnet's output tokens and finished faster. Two easy tasks then
  ran once each on Haiku, Sonnet, and Sol at `high`. A settings edit needed no fix on any model, and Haiku cost about
  a ninth of Sonnet's API price ($0.018 against $0.159). A script that reads usage records, with file and parsing edge
  cases, needed 1 fix from Sol, 4 from Haiku, and 6 from Sonnet. One run per model and task is thin evidence, and
  Sol's price was not measured in dollars. The plugin's `implementation_worker` `auto` route applies the same rule at
  runtime.
- 2026-10-20: the user moved normal and hard work to Sonnet so that implementation stays on Claude while
  investigation and final review stay on GPT; Sol became the fallback.
- 2026-10-22: the auto-mode classifier blocked `claude -p` workers that edit the approval guard as self-modification,
  and `dontAsk` stopped them on commands the guard asks about, while the `sonnet-worker` subagent made the same kind
  of change unblocked and its subagent record showed `claude-sonnet-5-5` at `high`.
