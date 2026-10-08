# GPT models in Claude Code through a local gateway

Proposed implementation plan, 2026-10-08. Evidence was checked on 2026-10-08 against Claude Code `2.1.294` and the
official pages in [Evidence](#evidence).

Approving this plan for execution reverses two 2026-10-07 decisions: the local proxy that was not adopted, and the
"no gateway" clauses in [GPT connection work](claude-gpt-remaining.md) and [remaining work](model-routing-remaining.md).
Those clauses stay in force until the user approves execution. The native `turn.step` route stays blocked, because
the `2.1.294` Mods declarations still give `ToolInfo` only `name`, `description`, and `mcp`. The live observations
that [GPT connection work](claude-gpt-remaining.md#essential-live-evidence) requires still apply; AC1–AC10 map them
to this route.

## Intent and scope

- Goal: in a Claude Code session started by the plugin's GPT launcher, the user switches with `/model` at any time
  between Claude models and the pinned GPT models `gpt-6.1-sol` and `gpt-6-luna`. Claude models run on the user's
  own Claude login. GPT models run on the user's own ChatGPT plan through OpenAI's Sign in with ChatGPT.
- In scope:
  - A local gateway on `127.0.0.1` that speaks the Anthropic Messages format. It translates requests that name a
    pinned GPT ID to the OpenAI Responses API and forwards every other request to Anthropic unchanged.
  - `scripts/claude_gpt.py launch`, which starts the gateway, runs Claude Code against it, and stops it on exit.
  - Reuse of the existing helper on this branch: Sign in with ChatGPT profiles, the explicit API-key profile,
    Responses streaming, tool-call validation, and saved reasoning state.
  - A Mod change that lets pinned GPT IDs through only in a launcher session.
  - Offline tests, an offline end-to-end check with the real Claude Code binary, README sections, record updates,
    and one live acceptance batch.
- Non-goals:
  - The native `turn.step` route, third-party proxies, Codex credentials, the Codex OAuth client, and ChatGPT
    `backend-api` endpoints.
  - The Astra-family pin as a main model, gateway model discovery, and a picker row for `gpt-6-luna`.
  - Remote or multi-user access, and automatic fallback between providers, profiles, or billing modes.
  - Changes to subagent, worker, or reviewer pins, to user settings, or to the Claude Code binary.
- Constraints:
  - GPT requests follow the Sign in with ChatGPT contract: `POST https://api.openai.com/v1/responses` with
    `store: false` and `stream: true`, system text in `instructions`, function tools grouped in a namespace, no
    `previous_response_id`, and none of the unsupported fields or hosted tools that Preview limitations lists.
  - Claude requests follow the Claude Code gateway contract: forward `anthropic-*` headers and body fields as open
    lists, keep the OAuth capability in `anthropic-beta`, and stream every event in order without buffering.
  - The gateway never reads, stores, logs, or changes Claude credentials. They leave the gateway only inside
    unchanged requests to `https://api.anthropic.com`. The gateway never reads Codex credentials.
  - GPT credentials stay in the helper's protected profile store. No credential enters logs, errors, settings,
    model-visible text, or test fixtures.
  - Runtime files name models only by full pinned IDs.
- Protected surfaces: ordinary `claude` sessions; user, project, and managed settings; installed plugin caches;
  default hooks and guards; Codex isolation; role pins; and the native-route refusal in `hooks/claude-gpt/`.
- Known limitation: Claude Code saves a model as the default for new sessions when the user presses `Enter` in the
  `/model` picker or types `/model <name>`. Pressing `s` in the picker, or launching with `--model`, keeps the saved
  default. The plugin cannot change this, because Mods have no model setter and the plugin never edits user settings.
  The README and the picker row tell the user to press `s`. If a GPT default is saved anyway, an ordinary session
  refuses GPT turns before any request and says how to restore a Claude default.
- Acceptance criteria:
  - AC1 Eligibility: a Sign in with ChatGPT grant includes `chatgpt.tokens.use.direct`, and one `gpt-6.1-sol`
    request completes on plan usage. The response names the pinned model and the effort it ran with.
  - AC2 Ordinary sessions: without the launcher, behavior, settings, and hooks do not change. A pinned GPT ID, even
    one saved as the default under the known limitation, is refused before any network request with recovery steps.
  - AC3 Claude path: in a launcher session, Claude requests reach Anthropic with an identical body and forwarded
    headers on the user's Claude login, which the OAuth capability in `anthropic-beta` and `/status` both show. The
    Claude picker rows remain, and streams are not buffered.
  - AC4 GPT turns: text streams; a tool call is approved and another is denied through Claude Code's normal
    permission prompts and hooks; one bounded edit in a scratch folder succeeds; tool results, including errors and
    denials, return to the model; a multi-step tool loop completes; usage appears in the response.
  - AC5 Switching: in a launcher session, Claude to GPT to Claude with the `/model` picker keeps a synthetic fact and
    an earlier tool result, and a later `--resume` with `--model gpt-6.1-sol` keeps both. Resume replays no tool call.
  - AC6 Failures: usage-limit, authentication, unsupported-capability, and mid-stream failures appear once as
    Anthropic-format errors. Malformed, duplicate, unknown, and truncated tool calls are never executed. No provider,
    profile, or billing fallback happens, and nothing retries after partial output. Cancelling a turn closes the
    upstream request.
  - AC7 Isolation: the gateway binds only `127.0.0.1` behind a per-launch secret path. No credential appears in
    logs, errors, or model-visible text. Codex and Claude credential files are never read. GPT profile state stays in
    the helper's profile store.
  - AC8 Claude quota independence: when Anthropic rejects Claude requests with `429`, GPT turns still work.
  - AC9 Rollback: after the launcher exits, no gateway process or port remains, and no settings change remains except
    a default that the user saved under the known limitation.
  - AC10 Roles and usage: after a switch to GPT and after resume, subagents still run on their pinned Claude model and
    effort, and the batch reports usage for GPT turns, Claude turns, retries, and gateway overhead.
- Optional follow-ups: a status-line plan indicator, a picker row for `gpt-6-luna`, the Astra-family pin, a live
  check of the API-key profile, and a real exhausted-quota observation. Offline tests still cover the API-key profile.
- Stop conditions:
  - S3 returns `subscription_sharing_user_not_eligible`, a grant without `chatgpt.tokens.use.direct`, or a policy
    error. Stop the whole plan, discard the uncommitted S2 changes, and report it. Continue with API-key billing only
    if the user explicitly asks.
  - S1 shows that Claude Code drops the base-URL path, represents loaded deferred tools in a form the rule below
    cannot map, or retries after a stream `error` event that arrives before content. Stop and amend this plan.
  - A cited official contract changes before S7. Re-verify the affected rows before continuing.
  - The live allowance is used up, or any check shows a credential in output. Stop new requests.

## Evidence

Main-session fetches verified rows 1–5, 9–11, and 13. Researcher fetches, which return summaries, support the other
rows; S1 and S7 confirm the behavior that the plan depends on.

| # | Finding | Source |
|---|---|---|
| 1 | ChatGPT plan usage is documented "for open-source and locally hosted apps". Paid or hosted apps use an interest form. | [Plan usage overview](https://developers.openai.com/siwc/token-sharing-open-source) |
| 2 | "Eligible ChatGPT Plus and Pro users can use their ChatGPT plan"; plan usage "is available to all open-source partners and selected private clients". This repository is public under Apache-2.0. | [Quickstart](https://developers.openai.com/siwc/quickstart) |
| 3 | Registration starts with `client_id=dynamic_agent_client`; plan scopes are `offline_access resource.invoke chatgpt.tokens.use.direct`; the resource is `https://api.openai.com/v1`; the callback is HTTP on `127.0.0.1`. | [Registration and sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in) |
| 4 | Send the token to `POST https://api.openai.com/v1/responses`; "do not point it at ChatGPT's `backend-api` endpoints"; a usage-limit error can arrive as `response.failed`. | [Models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference) |
| 5 | Requires `store: false` and `stream: true`; rejects system-role items, `previous_response_id`, `max_output_tokens`, `metadata`, `temperature`, `top_p`, and other listed fields; tools go in namespaces or `additional_tools`; hosted tools and `tool_search` are unsupported. | [Preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations) |
| 6 | `subscription_sharing_usage_limit_exceeded` (429): pause plan requests; `subscription_sharing_user_not_eligible` (403): do not loop OAuth; `subscription_sharing_unsupported_capability` (400): do not resend the same body; 503 codes: bounded backoff. | [Errors and recovery](https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery) |
| 7 | Access tokens last one hour and refresh tokens 30 days with rotation; serialize refreshes. The Plus five-hour limit is shared across apps; Pro has none. | [Token reference](https://developers.openai.com/siwc/token-sharing-open-source/token-reference), [Accounts and sessions](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions) |
| 8 | Pass back reasoning items returned with function calls; reasoning items carry `encrypted_content` by default. | [Reasoning guide](https://developers.openai.com/api/docs/guides/reasoning) |
| 9 | Setting only `ANTHROPIC_BASE_URL` keeps the claude.ai login active; a gateway credential variable or `apiKeyHelper` replaces it; gateways that pass traffic to Anthropic "must forward the OAuth capability in `anthropic-beta`". Anthropic "doesn't support routing Claude Code to non-Claude models through any gateway". | [Other LLM gateways](https://code.claude.com/docs/en/llm-gateway) |
| 10 | Third-party developers may not route requests through users' plan credentials or intermediate them; this does not prevent "an end user from signing in to the unmodified Claude Code binary with their own Claude subscription". | [Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance) |
| 11 | LiteLLM's ChatGPT provider and CLIProxyAPI use the Codex CLI client `app_EMoamEEZ73f0CkXaXp7hrann`; LiteLLM calls `https://chatgpt.com/backend-api/codex`. | [LiteLLM constants](https://github.com/BerriAI/litellm/blob/main/litellm/llms/chatgpt/common_utils.py), [CLIProxyAPI auth](https://github.com/router-for-me/CLIProxyAPI/blob/main/internal/auth/codex/openai_auth.go) |
| 12 | Claude Code calls `POST /v1/messages?beta=true`, optional `/v1/messages/count_tokens`, and `HEAD /api/hello`; it expects every stream event in order through `message_stop`; unknown model IDs get a 200K window; `CLAUDE_CODE_ALWAYS_ENABLE_EFFORT=1` sends effort on every request. | [Gateway compatibility guide](https://code.claude.com/docs/en/llm-gateway-protocol), [Environment variables](https://code.claude.com/docs/en/env-vars) |
| 13 | `/model <name>` and `Enter` in the picker save the default in `~/.claude/settings.json`; `s` in the picker, `--model`, and `/model` under `-p` keep it; `ANTHROPIC_CUSTOM_MODEL_OPTION` skips ID validation. | [Model configuration](https://code.claude.com/docs/en/model-config) |
| 14 | Mods `2.1.294` can read environment variables with `$.env.get` and have no model setter; `ToolInfo` still lacks input schemas; `claude plugin list --json` lists installed plugins. | Installed Claude Code `2.1.294` |

Third-party proxies are excluded by row 11: they borrow another client's OAuth identity, and LiteLLM uses the
endpoint that row 4 forbids. The existing helper already uses the flow in rows 3 and 4.

## Implementation strategy

```text
claude (unmodified, with the installed plugin at the launcher's version)
   | ANTHROPIC_BASE_URL=http://127.0.0.1:<port>/<secret>
   v
local gateway ---- model is gpt-6.1-sol or gpt-6-luna ---> api.openai.com/v1/responses (ChatGPT plan)
   |
   +-------------- any other request, unchanged ----------> api.anthropic.com (user's Claude login)
```

### Routing

The gateway reads only the JSON `model` field of `POST /v1/messages` and `POST /v1/messages/count_tokens`. An exact
match with `gpt-6.1-sol` or `gpt-6-luna` takes the GPT path. Every other request, method, and path takes the
Claude path. A request without the secret path prefix gets `404` and is not forwarded.

### Claude path

The gateway strips the secret prefix and sends the method, path, query, headers, and body bytes unchanged to
`https://api.anthropic.com`. It drops only hop-by-hop headers and rewrites `Host`. It does not follow redirects. It
returns the status, headers, and body to Claude Code chunk by chunk and adds no read timeout to a stream. For AC3,
its log records only whether `anthropic-beta` carries the OAuth capability, never a header value.

### GPT path

The gateway turns the Anthropic request into the helper's version-1 request and runs it through the helper's
Responses code:

| Anthropic input | Helper or Responses input |
|---|---|
| `system` string or text blocks | `instructions`, joined with blank lines; `cache_control` dropped |
| User text and `image` blocks | User message text and `input_image` data URLs |
| `document` blocks with base64 PDF | `input_file` with `file_data` |
| Assistant text and `tool_use` | Assistant output text and `function_call` with the same `call_id` |
| `tool_result` text | `function_call_output` text |
| `tool_result` with `is_error: true`, including permission denials | `function_call_output` whose text starts with `Tool error:` followed by the result text |
| `tool_result` images | `function_call_output` text that names the attachment, then a user message with `input_image` |
| `thinking` and `redacted_thinking` | Dropped |
| `server_tool_use` and web search results | The results become plain text with each title and URL; the call is dropped |
| Client tools (`input_schema`) | Function tools in the helper's `claude` namespace |
| Tools with `defer_loading: true` | Sent only after a `tool_reference` block names them earlier in the conversation |
| Server tools such as web search | Dropped |
| `tool_choice` `auto`, `any`, `tool`, `none` | `auto`, `required`, the named function, `none` |
| `output_config.effort` | `reasoning.effort` with the same value; absent means the model default |
| `max_tokens`, `temperature`, `top_p`, `top_k`, `stop_sequences`, `metadata`, `thinking`, `context_management` | Ignored, because the plan-usage route rejects or lacks them |

The helper's schema check accepts any JSON Schema keyword. It validates tool arguments only against the keywords it
understands (`type`, `properties`, `required`, `items`, `enum`, `additionalProperties`) and leaves the rest to
Claude Code's own input validation. It keeps reasoning items keyed by `call_id` in the profile's state directory
under its existing size limit, dropping the oldest first. A later request that contains the same `call_id` gets
those items back. A lost entry only removes the recommended reasoning context; the request still runs.

The response becomes an Anthropic stream. Text streams as `text_delta`. Tool calls are held until the helper has
validated `response.completed` and finished reading the upstream stream without error. Only then are they sent as
`tool_use` blocks with one `input_json_delta` each. A failure after `response.completed` sends a stream `error`
event and no `tool_use` block.
`stop_reason` is `tool_use` when calls exist and `end_turn` otherwise. Usage maps `input_tokens` minus cached tokens
to `input_tokens`, cached tokens to `cache_read_input_tokens`, and `output_tokens` to `output_tokens`. A `call_id`
outside `^[A-Za-z0-9_-]{1,64}$` fails the turn with `unsupported_call_id`. `count_tokens` for a GPT ID returns `404`,
so Claude Code uses its own estimate.

### Errors

The HTTP status is fixed when the gateway sends response headers. The gateway sends `200` and `message_start` only
after OpenAI returns `200` and opens its stream, then sends `ping` every 10 seconds until the first content.

| Condition | Before headers: status and type | After headers | `x-should-retry` |
|---|---|---|---|
| `subscription_sharing_usage_limit_exceeded` | `429 rate_limit_error`, pointing to ChatGPT Settings > Usage | Stream `error` with `rate_limit_error` | `false` |
| Not eligible, missing scope, invalid user, or a terminal refresh error | `401 authentication_error` or `403 permission_error`, naming the `auth` command | Stream `error` with the same type | `false` |
| Unsupported capability or effort | `400 invalid_request_error` naming the GPT field, never `output_config` | Stream `error` with the same type | `false` |
| A 503 code | `503 api_error` | Stream `error` with `api_error` | `true` only before headers |
| Incomplete response, validation failure, or broken stream | Not applicable | Stream `error` with `api_error` | Not applicable |

The helper keeps the HTTP status and these allowlisted provider codes as structured fields instead of collapsing
them into `http_error` or `provider_failed`: `subscription_sharing_usage_limit_exceeded`,
`subscription_sharing_usage_unavailable`, `subscription_sharing_user_not_eligible`,
`subscription_sharing_unsupported_capability`, `subscription_sharing_route_not_supported`,
`subscription_sharing_invalid_user`, and `subscription_sharing_user_unavailable`. The `output_config` rule keeps
Claude Code from silently retrying without effort. If Claude Code closes the connection, the gateway closes the
upstream response and emits no tool call from the incomplete response.

### Launcher

`scripts/claude_gpt.py launch --profile <profile-id> [-- <claude arguments>]` replaces the current refusal:

1. Refuse when `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_USE_BEDROCK`,
   `CLAUDE_CODE_USE_VERTEX`, or `CLAUDE_CODE_USE_FOUNDRY` is set in the environment, or when a readable user,
   project, local, or managed settings file sets `apiKeyHelper` or one of those variables in its `env` block. Also
   refuse the Claude Code arguments `--settings`, `--setting-sources`, and `--bare`, because they can add or drop an
   authentication source. Check only whether a key or argument is present; never read a credential value.
2. Refuse unless `claude plugin list --json` shows `hei5enbug-agent-setup@hei5enbug` enabled with the same
   `<major>.<minor>.<patch>` as the launcher's `pyproject.toml`, ignoring any local cachebuster suffix, so the
   installed Mod lets GPT turns through.
3. Load the explicitly named profile and refresh its token if needed. Never start a login.
4. Start the gateway on `127.0.0.1` with an OS-assigned port and a 256-bit random path secret.
5. Run `claude` from `PATH` with the parent environment plus `ANTHROPIC_BASE_URL` and `HEI5ENBUG_GPT_GATEWAY_URL`
   (the same URL), `ANTHROPIC_CUSTOM_MODEL_OPTION=gpt-6.1-sol`, `ANTHROPIC_CUSTOM_MODEL_OPTION_NAME=gpt-6.1-sol`,
   `ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION` set to `ChatGPT plan via local gateway; press s to keep your default`
   or `OpenAI API key via local gateway; press s to keep your default`, and `CLAUDE_CODE_ALWAYS_ENABLE_EFFORT=1`.
   Pass the remaining arguments unchanged and inherit stdio.
6. When `claude` exits, stop the gateway and return its exit code.

The profile stays bound to the gateway for its lifetime; `--resume` through the launcher binds the profile named
again. The gateway writes nothing to the terminal. It appends sanitized codes, request IDs, and token counts to
`logs/gateway.log` in the helper's profile root, with mode `0600`, rotating one file at 1 MB.

### Mod

`hooks/mod/gpt.js` keeps intercepting `turn.step` for the two pinned IDs on the main loop. It calls `next(event)`
when `$.env.get("HEI5ENBUG_GPT_GATEWAY_URL")` and `$.env.get("ANTHROPIC_BASE_URL")` are both set and equal. Otherwise
it refuses as now, with a message that names the launcher command, names `/model claude-opus-5-5` to restore a
Claude default, and explains the known limitation.

### Code location

The implementation lands on `main`. It restores `scripts/claude_gpt.py`, `tests/test_claude_gpt.py`, and the
`claude-gpt` extra (`PyJWT[crypto]>=2.10`) with its `uv.lock` entries from this branch, then changes them. It adds
`scripts/claude_gpt_gateway.py` and `tests/test_claude_gpt_gateway.py`. `hooks/claude-gpt/` and
`config/claude-gpt-hooks.json` stay on this branch. Under the AGENTS.md table, a new user-facing launcher is an
external contract change, so the release level is minor. Users run the launcher from a source checkout with
`uv run --extra claude-gpt`, never from an installed plugin cache. S6 and S7 install the working tree as the plugin
with a cachebuster, as AGENTS.md describes for local reinstalls, so the launched Claude Code loads the new Mod.

## Execution slices

Worker model and effort: the host's implementation worker route under the implementation execution rules, as the
host's agent rules pin it. Main-owned slices keep the main session's model and effort. Every worker assignment says
that the worker is an assigned worker, that other workers may edit the workspace, and that it must preserve their
changes. S2 through S5 stay uncommitted until S7 ends.

| Slice | Result and changes | Owner | Allowed and protected paths | Depends on | Shared resources and parallel condition | Verification and completion evidence |
|---|---|---|---|---|---|---|
| S1 Request shape | Offline capture: a throwaway fake Anthropic server returns scripted streams to `claude -p` `2.1.294`, with the launcher's model environment and the secret base-URL path. Run A uses the real Claude config and `--model claude-opus-5-5` to record the OAuth request shape. Run B uses a scratch `CLAUDE_CONFIG_DIR` with no plugins and a dummy `ANTHROPIC_AUTH_TOKEN`, so the installed Mod cannot refuse, and `--model gpt-6.1-sol` and `gpt-6-luna` to record the GPT-ID shape. Record only structure: path with prefix, header names, body keys, block types, tool flags, `tool_reference` blocks, effort and thinking fields, `count_tokens`, background requests, and `--resume`. Scripted turns call ToolSearch, Read a PNG and a PDF, and get a denied tool. Run every captured tool schema through the helper's current schema check. Observe Claude Code after a `429` with `x-should-retry: false` and after a stream `error` before content. | Main | Scratch files only; header values are never written | None | No model request | A structure report that confirms or stops the routing, deferred-tool, schema, effort, and error rules |
| S2 Helper | Restore the helper, its tests, and packaging. Add image and file parts, nullable effort, `tool_choice`, `is_error` results, `call_id`-keyed reasoning state, the permissive schema check, structured HTTP status and provider codes, and a `launch` that calls `claude_gpt_gateway.launch(profile_id, claude_args)`. | Worker | Allowed: `scripts/claude_gpt.py`, `tests/test_claude_gpt.py`, `pyproject.toml`, `uv.lock`. Protected: all others | S1 | Lockfile | `uv run --extra claude-gpt --extra dev pytest tests/test_claude_gpt.py` |
| S3 Eligibility | The user runs `auth subscription` with the S2 helper; main runs `status` and one version-1 `request` to `gpt-6.1-sol` without tools. | Main with the user | No tracked path | S2 and user approval of execution and the live allowance | One GPT request from the live allowance | Granted scopes, sanitized status, response model and effort, and a usage receipt, or the eligibility error that stops the plan |
| S4 Gateway | Add the server, routing, Claude path, GPT translation, stream writer, error mapping, cancellation, private log, and launcher checks in `scripts/claude_gpt_gateway.py`. Tests use in-process fakes and no sockets, and include malformed, duplicate, unknown, and truncated tool calls. | Worker | Allowed: `scripts/claude_gpt_gateway.py`, `tests/test_claude_gpt_gateway.py`. Protected: all others | S3 | Imports the S2 helper API; may run beside S5 | `uv run --extra claude-gpt --extra dev pytest tests/test_claude_gpt_gateway.py tests/test_claude_gpt.py` |
| S5 Mod and README | Change `hooks/mod/gpt.js` as described and document auth, launch, switching with `s`, the known limitation, plan limits, and rollback in both READMEs. | Worker | Allowed: `hooks/mod/gpt.js`, `hooks/mod/gpt.test.ts`, `README.md`, `README.ko.md`. Protected: all others | S3 | No shared file with S4 | `claude plugin validate .`, `claude plugin test .`, `python3 -m pytest tests/test_korean_mirrors.py` |
| S6 Offline end to end | Install the working tree as the plugin with a cachebuster. A scratch harness starts the gateway through its Python API with fake Anthropic and OpenAI upstreams, then runs the real `claude -p` against it, including scripted subagent requests. | Main | Scratch files and the local plugin install only; header values are never written | S4 and S5 | Local ports owned by the harness | Evidence for AC2–AC10 except live-only parts |
| S7 Live acceptance | One batch of 2 cases in a scratch folder. Case 1, interactive through the launcher: on a Claude model the user states a synthetic fact and Claude reads a file; the user switches with the picker and `s` to `gpt-6.1-sol`; GPT reads a file, makes one bounded edit that the user approves, and attempts a write that the user denies; the user cancels one GPT turn with Esc; the user switches back with `s`, and Claude recalls the fact and the earlier tool result. Case 2: `--resume` of case 1 through the launcher with `--model gpt-6.1-sol` and `-p`, where GPT recalls both and starts one researcher subagent. | Main with the user | Scratch files only | S6 and approval of the live allowance | At most 2 cases, 4 Claude Code starts, 20 minutes, and 10 GPT requests including S3 | Pass, fail, or untested for each AC with build, model, effort, authentication mode, request counts, transcript role records, and usage receipts |
| S8 Integration and records | Set the planned version, run every development check in `README.md`, update this branch's records to the result, and commit through `suggest-commit`. Push only when the user asks. | Main | Version files on `main` and records on this branch | S7 | Runs after every worker has stopped | All development checks pass on `HEAD` |

## Integrated verification

| Criterion | Offline evidence | Live evidence |
|---|---|---|
| AC1 | S2 tests for scope checks, refresh, and structured provider codes | S3 |
| AC2 | S5 Mod tests for both environment states and a saved GPT default; S6 run without the launcher | Not required |
| AC3 | S4 byte-equality tests; S6 pass-through through a fake Anthropic server | S7 Claude turns and `/status` |
| AC4 | S4 translation and stream tests; S6 tool loop with approval, denial, error results, and an edit | S7 case 1 |
| AC5 | S6 `--resume` with `--model` and a replay check | S7 cases 1 and 2 |
| AC6 | S4 error-table, tool-call rejection, and cancellation tests; S1 retry observation; S6 partial failures and cancellation | S7 Esc cancellation; a live partial failure is recorded only if one occurs |
| AC7 | S4 bind, secret-path, and log tests; a check that output and logs contain no fixture secret | S7 log inspection |
| AC8 | S6 with the fake Anthropic server returning `429` | Optional real observation |
| AC9 | S6 process and port check after exit | S7 process check |
| AC10 | S6 subagent requests keep their pinned model after a switch and resume | S7 case 2 transcript record and usage report |

Offline success does not prove live behavior, account eligibility, or plan limits. Record live results separately.
The plan adds no fault switch to the runtime, so a live partial failure cannot be provoked. Unless one occurs in S7,
that observation stays untested live, and A11 stays open for it until the user accepts the S6 offline evidence.
