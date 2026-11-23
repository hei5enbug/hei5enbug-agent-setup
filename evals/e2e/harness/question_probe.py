"""Probe whether a Codex `PreToolUse` hook receives a `request_user_input` call.

The probe builds an isolated CODEX_HOME the way a Codex run of the harness does (own home, credential symlink, `.zprofile`
ZDOTDIR) but installs no plugin. Its `hooks.json` holds two probe hooks: a guard hook with the plugin's own matcher that
logs the event and denies it with a sentinel reason, and a control hook for every tool that only logs. Then it starts one
minimal `codex exec` session that asks the model to call `request_user_input` once, and reads the evidence from the hook
log and the rollout. `--dry-run` prints the commands and starts nothing."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, TextIO

from . import codex_host, environment, question_probe_evidence as evidence
from .config import EXIT_FAILURE
from .matrix import write_json

PROBE_FOLDER = "probes"
HOOK_SCRIPT = Path(__file__).resolve().with_name("question_probe_hook.py")
LOG_NAME = "hook-log.jsonl"
EVIDENCE_NAME = "evidence.json"
STREAM_NAME = "stream.jsonl"
GUARD_MATCHER = "^(AskUserQuestion|request_user_input)$"
CONTROL_MATCHER = "*"
SENTINEL = "PROBE-DENIED-REQUEST-USER-INPUT"
HOOK_TIMEOUT_SECONDS = 10
DEFAULT_EFFORT = "low"
DEFAULT_TIMEOUT_SECONDS = 300.0
INCONCLUSIVE_EXIT = 3
PROMPT = (
    "Call the request_user_input tool exactly once. Ask whether the demo should use option A or option B, with one "
    "question and the two options A and B. Do not choose for me and do not call any other tool. If the call is "
    "refused, say so in one line and stop."
)


def hooks_json(python: str, log: Path) -> dict[str, Any]:
    """The probe's Codex hooks file: the denying guard hook and the logging control hook."""
    def command(label: str, *extra: str) -> str:
        return shlex.join([python, str(HOOK_SCRIPT), str(log), label, *extra])

    def entry(matcher: str, label: str, *extra: str) -> dict[str, Any]:
        return {"matcher": matcher, "hooks": [{"type": "command", "command": command(label, *extra),
                                              "timeout": HOOK_TIMEOUT_SECONDS}]}

    return {"hooks": {"PreToolUse": [
        entry(GUARD_MATCHER, evidence.GUARD_LABEL, "--deny", SENTINEL),
        entry(CONTROL_MATCHER, evidence.CONTROL_LABEL),
    ]}}


def exec_command(codex_bin: str, model: str, effort: str, repo: Path) -> list[str]:
    return [
        codex_bin, "exec", "--json", "-m", model, "-c", f'model_reasoning_effort="{effort}"',
        "-c", "features.default_mode_request_user_input=true", "--dangerously-bypass-hook-trust",
        "-s", "danger-full-access", "--skip-git-repo-check", "-C", str(repo), "--", PROMPT,
    ]


def trial_plan(trial: Path, codex_bin: str, model: str, effort: str, python: str) -> dict[str, Any]:
    """Everything the probe will write and run, as data, so a dry run and a real run use the same values."""
    home = trial / codex_host.CODEX_HOME_NAME
    repo = trial / "repo"
    return {
        "trial": str(trial), "repo": str(repo), "codex_home": str(home), "hooks_file": str(home / "hooks.json"),
        "hook_log": str(trial / LOG_NAME), "env": codex_host.host_env(trial),
        "hooks": hooks_json(python, trial / LOG_NAME), "argv": exec_command(codex_bin, model, effort, repo),
        "auth_link": f"{home / codex_host.AUTH_NAME} -> <credential file in {codex_host.AUTH_HOME_VAR} or ~/.codex>",
    }


def print_plan(plan: Mapping[str, Any], out: TextIO) -> None:
    out.write("dry run: nothing is started\n")
    out.write(f"trial folder: {plan['trial']}\n")
    out.write(f"write {plan['hooks_file']}:\n{json.dumps(plan['hooks'], indent=2)}\n")
    out.write(f"link {plan['auth_link']}\n")
    out.write("env: " + " ".join(f"{name}={shlex.quote(value)}" for name, value in plan["env"].items()) + "\n")
    out.write("run: " + shlex.join(plan["argv"]) + "\n")
    out.write(f"then read {plan['hook_log']} and the rollouts below {plan['codex_home']}/sessions\n")


def prepare_trial(plan: Mapping[str, Any], source_home: Path, path_value: str | None) -> None:
    """Create the trial folders, the hooks file, the ZDOTDIR, and the credential link. The credential file is only linked."""
    trial = Path(plan["trial"])
    Path(plan["repo"]).mkdir(parents=True, exist_ok=True)
    Path(plan["codex_home"]).mkdir(parents=True, exist_ok=True)
    codex_host.write_zprofile(trial / codex_host.ZDOTDIR_NAME, path_value)
    codex_host.link_auth(trial, source_home)
    Path(plan["hooks_file"]).write_text(json.dumps(plan["hooks"], indent=2) + "\n", encoding="utf-8")


def start_session(plan: Mapping[str, Any], timeout: float) -> dict[str, Any]:
    """Run the `codex exec` command with the probe's environment; return its exit code and whether it timed out."""
    env, _ = environment.child_environment(os.environ, plan["env"])
    trial = Path(plan["trial"])
    try:
        with open(trial / STREAM_NAME, "w", encoding="utf-8") as stream:
            done = subprocess.run(plan["argv"], env=env, cwd=plan["repo"], stdin=subprocess.DEVNULL, stdout=stream,
                                  stderr=subprocess.STDOUT, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return {"returncode": None, "timed_out": True}
    except OSError as error:
        return {"returncode": None, "timed_out": False, "error": str(error)}
    return {"returncode": done.returncode, "timed_out": False}


def default_trial(run_root: Path, now: datetime | None = None) -> Path:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return run_root / PROBE_FOLDER / f"question-hook-{stamp}"


def probe(
    trial: Path, codex_bin: str, model: str, effort: str, timeout: float, dry_run: bool, out: TextIO,
    python: str | None = None, source_home: Path | None = None,
) -> int:
    """Plan, or run, one probe trial. Returns 0 for a conclusive result, 3 for an inconclusive one, 1 for a failure."""
    plan = trial_plan(trial, codex_bin, model, effort, python or sys.executable)
    if dry_run:
        print_plan(plan, out)
        return 0
    if trial.exists() and any(trial.iterdir()):
        sys.stderr.write(f"error: {trial} is not empty; pass a new --dir\n")
        return EXIT_FAILURE
    try:
        prepare_trial(plan, source_home or codex_host.auth_home(), os.environ.get("PATH"))
    except codex_host.CodexSetupError as error:
        sys.stderr.write(f"error: {error}\n")
        return EXIT_FAILURE
    session = start_session(plan, timeout)
    found = {**evidence.collect_evidence(trial, LOG_NAME, Path(plan["codex_home"]) / "sessions", SENTINEL), "session": session,
             "argv": plan["argv"]}
    write_json(trial / EVIDENCE_NAME, found)
    out.write(json.dumps(found, indent=2, ensure_ascii=False) + "\n")
    out.write(f"verdict: {found['verdict']}\nevidence written: {trial / EVIDENCE_NAME}\n")
    return 0 if found["verdict"] in evidence.CONCLUSIVE else INCONCLUSIVE_EXIT
