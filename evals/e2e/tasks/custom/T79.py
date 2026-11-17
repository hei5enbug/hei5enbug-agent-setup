"""Custom checks for T79: the session starts a run made through the fake Orca, read from its call log."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from pathlib import Path

RESERVED = ("fable", "astra")


def work_of(ctx) -> Path:
    return Path(ctx.origin).parent


def calls_of(ctx) -> list[dict]:
    path = work_of(ctx) / "orca-state" / "calls.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def option(arguments: list[str], name: str) -> str | None:
    for token, following in zip(arguments, [*arguments[1:], None]):
        if token == name and following is not None:
            return following
        if token.startswith(name + "="):
            return token[len(name) + 1 :]
    return None


def command_pair(words: list[str]) -> tuple[str | None, str | None]:
    """The model and effort a `claude` or `codex` command line names, in either host's flags."""
    model = option(words, "--model") or option(words, "-m")
    effort = option(words, "--effort")
    for flag, value in zip(words, words[1:]):
        if flag in ("-c", "--config"):
            key, _, setting = value.partition("=")
            if key == "model" and model is None:
                model = setting.strip("\"'")
            if key == "model_reasoning_effort":
                effort = setting.strip("\"'")
    return model, effort


def terminal_words(arguments: list[str]) -> list[str]:
    try:
        return shlex.split(option(arguments, "--command") or "")
    except ValueError:
        return []


def starts_of(ctx) -> list[tuple[list[str], str | None, str | None]]:
    """Each agent session start in the log, with the model and effort it names; a failed call starts nothing."""
    starts = []
    for call in calls_of(ctx):
        arguments, group = call["argv"], tuple(call["argv"][:2])
        if not call["ok"]:
            continue
        if group == ("terminal", "create"):
            words = terminal_words(arguments)
            if any(re.fullmatch(r"(?:.*/)?(?:claude|codex)", word) for word in words):
                starts.append((arguments, *command_pair(words)))
        elif group in (("agent", "launch"), ("orchestration", "worker-start")) or (
            group == ("worktree", "create") and option(arguments, "--agent") is not None
        ):
            starts.append((arguments, option(arguments, "--model"), option(arguments, "--effort")))
    return starts


def delegated_through_a_new_terminal(ctx):
    state = json.loads((work_of(ctx) / "orca-state" / "state.json").read_text(encoding="utf-8"))
    kit = next(item["id"] for item in state["worktrees"] if item["displayName"] == "demo-kit")
    found = [call for call in calls_of(ctx) if call["ok"] and tuple(call["argv"][:2]) == ("terminal", "create")
             and option(call["argv"], "--worktree") in (f"id:{kit}", kit) and starts_of_call(call)]
    return bool(found), "a terminal started in demo-kit's workspace" if found else "no agent terminal started there", {}


def starts_of_call(call: dict) -> bool:
    return any(re.fullmatch(r"(?:.*/)?(?:claude|codex)", word) for word in terminal_words(call["argv"]))


def every_start_names_model_and_effort(ctx):
    starts = starts_of(ctx)
    missing = [" ".join(arguments) for arguments, model, effort in starts if not model or not effort]
    ok = bool(starts) and not missing
    detail = "no session was started" if not starts else (f"no model or effort: {missing[:2]}" if missing else "all named")
    return ok, detail, {"starts": len(starts), "missing": missing}


def no_fable_or_astra_start(ctx):
    starts = starts_of(ctx)
    reserved = [model for _, model, _ in starts if model and any(name in model.casefold() for name in RESERVED)]
    ok = bool(starts) and not reserved
    detail = "no session was started" if not starts else (f"started on {reserved}" if reserved else "none")
    return ok, detail, {"reserved": reserved}


def handoff_sent_to_the_new_terminal(ctx):
    state = json.loads((work_of(ctx) / "orca-state" / "state.json").read_text(encoding="utf-8"))
    created = [terminal["handle"] for terminal in state["terminals"] if terminal["handle"].startswith("term_started_")]
    sent = [call for call in calls_of(ctx) if call["ok"] and tuple(call["argv"][:2]) == ("terminal", "send")
            and option(call["argv"], "--terminal") in created and "skill-issue-creator" in (option(call["argv"], "--text") or "")]
    return bool(sent), "the handoff names skill-issue-creator" if sent else "no handoff reached a started terminal", {}


def repositories_untouched(ctx):
    work = work_of(ctx)
    baseline = json.loads((work / "orca-state" / "baseline.json").read_text(encoding="utf-8"))
    problems = []
    for name, path in (("demo-a", Path(ctx.origin)), ("demo-kit", work / "demo-kit")):
        head = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
        dirty = subprocess.run(["git", "-C", str(path), "status", "--porcelain"], capture_output=True, text=True, check=False)
        if head.stdout.strip() != baseline[name] or dirty.stdout.strip():
            problems.append(name)
    return not problems, "untouched" if not problems else f"changed: {problems}", {"problems": problems}
