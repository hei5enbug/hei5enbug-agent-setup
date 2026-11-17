"""The model rule of an Orca session start: name a model, and never Fable or Astra unless the user's latest prompt names it.

`orca_placement_hook.py` finds the model each session start names and asks `denial` whether the start may run. The
user's latest prompt comes from the transcript of the event, in Claude Code or Codex format; when it cannot be read,
no model counts as named by the user.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import language_guard
import plugin_toggles

REGISTRY = json.loads((Path(__file__).resolve().parents[1] / "config" / "model-registry.json").read_text(encoding="utf-8"))
RESERVED = ("fable", "astra")
NOT_A_PROMPT = (
    "<task-notification", "<local-command-", "<system-reminder", "<environment_context", "<user_instructions",
    "<turn_aborted", "# AGENTS.md instructions",
)
REASON = (
    "Blocked: this session start {problem}. A session an agent starts names its model and effort by its role and "
    "never runs on Fable or Astra unless the user names that model in their latest prompt. Implementation worker, a "
    "bounded change it is told to make and report back: `{claude_worker}` at `high` in Claude Code, and `{codex_worker}` "
    "at `{codex_effort}` in Codex (the `codex_worker_model` and `codex_worker_effort` settings). Any other session, one "
    "that takes over or coordinates work, files an issue, reviews, or whose role is unclear: `{claude_other}` at `high` "
    "in Claude Code, and `{codex_other}` at `high` in Codex. Pass `--model <id> --effort <level>` to `orca worktree "
    "create --agent`, `orca agent launch`, and `orca orchestration worker-start`. Inside an `orca terminal create "
    "--command`, pass `--model <id> --effort <level>` to the `claude` command, and `-m <id> -c "
    "model_reasoning_effort=\"<level>\"` to the `codex` command."
)


def reserved_family(model: str) -> str | None:
    """Return `fable` or `astra` when the model value, an alias or a full ID, names that family, else None."""
    text = model.casefold()
    return next((family for family in RESERVED if family in text), None)


def prompt_names(prompt: str | None, family: str) -> bool:
    return bool(prompt) and re.search(rf"(?<![a-z]){family}(?![a-z])", prompt, re.IGNORECASE) is not None


def prompt_text(content: object) -> str:
    if isinstance(content, str):
        return content
    blocks = [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []
    return "".join(block["text"] for block in blocks if block.get("type") in ("text", "input_text") and isinstance(block.get("text"), str))


def real_prompt(text: str) -> bool:
    return bool(text.strip()) and not text.lstrip().startswith(NOT_A_PROMPT)


def latest_prompt_of(entries: list[dict]) -> tuple[str | None, bool]:
    """Return the newest real user prompt in the entries, in either transcript format, and whether it was found."""
    for entry in reversed(entries):
        if entry.get("type") == "user" and isinstance(entry.get("message"), dict):
            blocks = entry["message"].get("content")
            hidden = entry.get("isMeta") or entry.get("isSidechain") or entry.get("isCompactSummary")
            if hidden or (isinstance(blocks, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks)):
                continue
            text = prompt_text(blocks)
        elif entry.get("type") == "response_item" and isinstance(entry.get("payload"), dict):
            payload = entry["payload"]
            if payload.get("type") != "message" or payload.get("role") != "user":
                continue
            text = prompt_text(payload.get("content"))
        else:
            continue
        if real_prompt(text):
            return text, True
    return None, False


def latest_prompt(event: dict) -> str | None:
    """Return the user's latest prompt from the event's transcript, or None when it cannot be read."""
    try:
        return language_guard.resolve_from_tail(event.get("transcript_path"), latest_prompt_of)
    except OSError:
        return None


def reason(problem: str) -> str:
    pins = REGISTRY["pins"]
    model, effort, _ = plugin_toggles.worker_setting("codex")
    return REASON.format(
        problem=problem, claude_worker=pins["claude-sonnet"], codex_worker=model, codex_effort=effort,
        claude_other=pins["claude-opus"], codex_other=pins["gpt-sol"],
    )


def denial(models: list[str | None], event: dict) -> str | None:
    """Return why a session start may not run, given the model each start names (None for none), or None when it may."""
    prompt: list[str | None] = []
    for model in models:
        if model is None:
            return reason("names no model")
        family = reserved_family(model)
        if family is None:
            continue
        if not prompt:
            prompt.append(latest_prompt(event))
        if not prompt_names(prompt[0], family):
            return reason(f"names `{model}`, which the user's latest prompt does not name")
    return None
