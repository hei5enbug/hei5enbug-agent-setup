# GPT connection components for Claude Code

## Current compatibility

Claude Code `2.1.291` exposes native text/tool streams and visible history, but its Mod tool list omits input
schemas. Access to the previously frozen system prompt after resume is also unverified. The module therefore
refuses GPT main requests before reading profiles or making network requests. `launch` refuses before creating
picker settings. Updating Claude Code does not automatically enable this adapter.

Both pinned GPT IDs, `gpt-6.1-sol` and `gpt-6-luna`, are recognized. They are not advertised as working picker
rows. A supported adapter, session-bound profile selection, merged session-only picker, and live conversation,
resume, cancellation, permission, and quota checks remain required. Ordinary Claude and subagent requests pass
through. No Codex loop, gateway, automatic fallback, or user-setting change replaces the blocked route.

The [validation record](model-routing-validation.md) contains the latest no-request host probe, development
checks, recurring-token measurements, and remaining live requirements.

## Explicit helper setup

The helper uses Python 3.12 or later. Subscription identity verification needs PyJWT with cryptography.
The optional `claude-gpt` extra and resolved versions are in `pyproject.toml` and `uv.lock`. In a source checkout,
prepare a private runtime explicitly; do not modify an installed plugin cache:

```bash
claude_gpt_runtime="${XDG_STATE_HOME:-$HOME/.local/state}/hei5enbug-agent-setup/claude-gpt-runtime"
UV_PROJECT_ENVIRONMENT="$claude_gpt_runtime" uv sync --extra claude-gpt --no-dev
"$claude_gpt_runtime/bin/python" scripts/claude_gpt.py launch
```

The final command currently returns `unsupported_host` without changing authentication, settings, or sessions.
Ordinary startup and requests never install dependencies or start login. A new runtime does not fix missing
host inputs; authentication is unnecessary to diagnose this blocker.

## Authentication commands

These helper components have offline coverage. Live app authorization and account eligibility are unverified.
Run authentication only after explicitly choosing the mode; existing Codex login is not a plugin credential.

| Command after `scripts/claude_gpt.py` | Effect |
|---|---|
| `auth subscription` | Open the public ChatGPT app authorization flow with a fresh loopback callback, PKCE, state, and nonce; save only a successful grant. Recommended mode when eligible. |
| `auth subscription --profile <profile-id>` | Reuse that profile's issued client ID and account mapping; reject another subject. A signed-out profile can reauthorize without a saved token. |
| `auth api-key` | Confirm API usage billing, then read a key through masked terminal input. |
| `auth api-key --from-env OPENAI_API_KEY` | Confirm usage billing and explicitly import only the named variable. Its presence never selects API billing automatically. |
| `status [--profile <profile-id>]` | Return profile ID, mode, and status; no credentials. This explicit command may create protected configuration directories. |
| `logout --profile <profile-id>` | Remove only that profile's credentials and provider state; attempt subscription revocation. Preserve app/account mapping and the stable host ID. Report unconfirmed remote revocation. |

An authentication command updates the helper's selected profile only after successful setup. It does not bind
a profile to a Claude session on this unsupported host. A future supported launcher must freeze the explicit
profile in session state and preserve it on resume; changing the global helper selection cannot switch an
existing conversation's billing.

## Credential and request boundaries

Profiles live in `~/.config/hei5enbug-agent-setup/claude-gpt/`. Directories are owner-only; atomic credential
writes use `0600`. Unsafe ownership, symlinks, and broad permissions are rejected. Subscription login validates
the ID-token signature, issuer, audience, expiry, nonce, subject, and granted direct-use scope. Refresh is
serialized and stores rotating credentials atomically. Claude and Codex credentials are never read or changed.

The version-1 helper request travels through stdin, including explicit session/turn/step IDs, profile reference,
full model ID, supported effort, system/developer content, visible history, and offered tool schemas. Secrets
never enter the request protocol, model prompts, arguments, settings, fixtures, or usage receipts. Errors expose
only sanitized codes. No authentication, model, provider, billing, or partial-output retry occurs automatically.

Responses requests use public `https://api.openai.com/v1/responses`, `store=false`, streaming, and explicit
history. Only offered tools with supported schemas are mapped. Signed Claude thinking is dropped; unsupported
history or schemas fail explicitly. Private provider state is scoped to the profile and session and contains
only required reasoning/tool-call state, not a second full transcript or server conversation ID.

Text deltas can appear before completion. Executable calls stay buffered until a valid completed response and
successful helper exit. Unknown tools, malformed inputs, duplicate historical/current IDs, truncated streams,
quota failure, and observed model/effort mismatches cannot produce accepted tool calls. Unreported effort is
recorded as unknown. Python never executes tools or grants permission. Actual host cancellation and permission
ordering remain unverified while the native route is disabled.

## Registration and rollback

The Claude manifest adds `config/claude-gpt-hooks.json`; Claude also loads the default `hooks/hooks.json` once.
Codex's manifest and existing security guards are unchanged. The Mod handles only `turn.step`, not permission
approval hooks. Disable the module by removing the extra Claude hook-file reference in a source checkout;
preserve default hooks, researcher registration, user-owned roles, and profiles. No session picker or model
default has been written by the current launcher.

Offline tests cover authentication and protocol failures with fake profiles and signed synthetic JWTs. Native
Mod tests verify refusal and pass-through, not a working GPT backend. Output quality and provider token receipts
must be assessed separately before any cost optimization or live-compatibility claim.

Sources: [Claude Mods](https://code.claude.com/docs/en/plugins/mods/reference),
[subscription sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in), and
[subscription inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference).
