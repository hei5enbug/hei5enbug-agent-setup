"""The Codex host: an isolated CODEX_HOME that holds only the exported plugin, the `codex exec` command, and run records.

A run never reads or loads the user's own Codex configuration or installed plugins. It gets an empty CODEX_HOME
inside the run's result folder, a symlink to the credential file (never opened), and the plugin installed from the
exported revision through a marketplace entry that points at the export."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping

from . import caps, codex_calls, collect, environment, transcript, usage
from .command import main_model
from .config import CODEX_EFFORT, HOST_CODEX, PLUGIN_NAME, USAGE_LIMIT_PATTERN, HarnessConfig
from .matrix import RunSpec, read_json, write_json

AUTH_HOME_VAR = "HARNESS_CODEX_AUTH_HOME"
AUTH_NAME = "auth.json"
CODEX_HOME_NAME = "codex-home"
ZDOTDIR_NAME = "zdotdir"
SETUP_RECORD = "codex-setup.json"
DEFAULT_MARKETPLACE = "hei5enbug"
SETUP_TIMEOUT_SECONDS = 180.0
SETUP_TAIL = 400
APPROVAL_HANDLING = (
    "codex exec runs with approval_policy never in a workspace-write sandbox without network; "
    "no approver stands in, and the plugin's own guard hooks still run"
)


class CodexSetupError(RuntimeError):
    pass


def auth_home(env: Mapping[str, str] | None = None) -> Path:
    source = os.environ if env is None else env
    return Path(source.get(AUTH_HOME_VAR) or environment.codex_home(source))


def marketplace_name(plugin_dir: str) -> str:
    data = read_json(Path(plugin_dir) / ".agents" / "plugins" / "marketplace.json", {})
    return str(data.get("name") or DEFAULT_MARKETPLACE) if isinstance(data, dict) else DEFAULT_MARKETPLACE


def build_codex_command(cfg: HarnessConfig, variant: dict[str, Any], prompt: str, repo: Path) -> list[str]:
    """The agent command. The prompt follows `--`, so a prompt that starts with a dash is not read as an option."""
    return [
        cfg.codex_bin, "exec", "--json", "-m", main_model(variant, HOST_CODEX), "-c", f'model_reasoning_effort="{CODEX_EFFORT}"',
        "--dangerously-bypass-hook-trust", "-s", "workspace-write", "-C", str(repo), "--", prompt,
    ]


def setup_commands(cfg: HarnessConfig, plugin_dir: str) -> list[list[str]]:
    return [
        [cfg.codex_bin, "plugin", "marketplace", "add", plugin_dir],
        [cfg.codex_bin, "plugin", "add", f"{PLUGIN_NAME}@{marketplace_name(plugin_dir)}"],
    ]


def host_env(result_dir: Path) -> dict[str, str]:
    """The two variables that isolate a Codex run: its own CODEX_HOME, and an empty ZDOTDIR so that the shell Codex starts
    reads none of the user's zsh startup files and keeps the PATH the run set."""
    return {"CODEX_HOME": str(result_dir / CODEX_HOME_NAME), "ZDOTDIR": str(result_dir / ZDOTDIR_NAME)}


def link_auth(result_dir: Path, source_home: Path) -> Path:
    """Symlink the credential file into the run's CODEX_HOME. The file is neither read nor copied nor printed."""
    target = source_home / AUTH_NAME
    if not os.path.lexists(target):
        raise CodexSetupError(f"no Codex credential file at {target}; set {AUTH_HOME_VAR} to the folder that holds {AUTH_NAME}")
    link = result_dir / CODEX_HOME_NAME / AUTH_NAME
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(link):
        link.unlink()
    os.symlink(target, link)
    return link


def tail(text: str | None) -> str:
    return (text or "")[-SETUP_TAIL:]


def prepare_home(
    cfg: HarnessConfig, result_dir: Path, plugin_dir: str, env: Mapping[str, str], source_home: Path | None = None,
) -> dict[str, Any]:
    """Create CODEX_HOME and the empty ZDOTDIR, link the credentials, and install the exported plugin. Returns the record."""
    (result_dir / ZDOTDIR_NAME).mkdir(parents=True, exist_ok=True)
    link_auth(result_dir, source_home or auth_home(os.environ))
    steps: list[dict[str, Any]] = []
    for argv in setup_commands(cfg, plugin_dir):
        try:
            done = subprocess.run(argv, env=dict(env), cwd=result_dir, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                  timeout=SETUP_TIMEOUT_SECONDS, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CodexSetupError(f"{' '.join(argv[1:4])} did not run: {error}") from error
        steps.append({"argv": argv, "returncode": done.returncode, "stdout_tail": tail(done.stdout), "stderr_tail": tail(done.stderr)})
        if done.returncode != 0:
            write_json(result_dir / SETUP_RECORD, {"steps": steps})
            raise CodexSetupError(f"{' '.join(argv[1:4])} exited {done.returncode}: {tail(done.stderr).strip()}")
    record = {"steps": steps, "codex_home": CODEX_HOME_NAME, "auth": "symlink", "marketplace": marketplace_name(plugin_dir)}
    write_json(result_dir / SETUP_RECORD, record)
    return record


def copy_rollouts(result_dir: Path) -> list[str]:
    """Copy every rollout the run's CODEX_HOME holds (the main session and any child) into `codex/`."""
    copied: list[str] = []
    for rollout in sorted((result_dir / CODEX_HOME_NAME / "sessions").rglob("rollout-*.jsonl")):
        (result_dir / "codex").mkdir(parents=True, exist_ok=True)
        shutil.copy2(rollout, result_dir / "codex" / rollout.name)
        copied.append(rollout.name)
    return copied


def session_start(rollout: dict[str, Any]) -> str:
    for event in rollout.get("events", []):
        if event.get("type") == "session_meta":
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            return str(payload.get("timestamp") or event.get("timestamp") or "")
    return ""


def label_rollouts(rollouts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Name the main rollout (the earliest session) `main`; a child gets the role its status line in the main calls names.

    Returns the labelled rollouts and the tool calls, where the main session's calls have source `main`."""
    ordered = sorted(rollouts, key=session_start)
    if not ordered:
        return [], []
    main = {**ordered[0], "role": "main"}
    main_calls = [{**call, "source": "main"} for call in codex_calls.rollout_tool_calls(main["events"], "main", main["name"])]
    roles = collect.rollout_roles(main_calls)
    labelled, calls = [main], list(main_calls)
    for rollout in ordered[1:]:
        child = {**rollout, "role": roles.get(rollout["name"], "unknown")}
        labelled.append(child)
        calls += codex_calls.rollout_tool_calls(child["events"], child["role"], child["name"])
    return labelled, calls


def payload_of(event: dict[str, Any]) -> dict[str, Any]:
    return event.get("payload") if isinstance(event.get("payload"), dict) else {}


def session_facts(events: list[dict[str, Any]]) -> dict[str, Any]:
    """CLI version from `session_meta`; model, effort, approval policy, and sandbox from the first `turn_context`."""
    facts: dict[str, Any] = {"cli_version": None, "model": None, "effort": None, "approval_policy": None, "sandbox": None}
    for event in events:
        payload = payload_of(event)
        if event.get("type") == "session_meta" and not facts["cli_version"]:
            facts["cli_version"] = payload.get("cli_version")
        if event.get("type") == "turn_context" and not facts["model"]:
            sandbox = payload.get("sandbox_policy")
            facts.update(model=payload.get("model"), effort=payload.get("effort"), approval_policy=payload.get("approval_policy"),
                         sandbox=sandbox.get("type") if isinstance(sandbox, dict) else sandbox)
    return facts


def assistant_messages(events: list[dict[str, Any]]) -> list[str]:
    texts: list[str] = []
    for event in events:
        payload = payload_of(event)
        if event.get("type") == "response_item" and payload.get("type") == "message" and payload.get("role") == "assistant":
            text = "".join(str(part.get("text", "")) for part in payload.get("content") or [] if isinstance(part, dict)).strip()
            if text:
                texts.append(text)
    return texts


def final_answer(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        payload = payload_of(event)
        if event.get("type") == "event_msg" and payload.get("type") == "task_complete" and payload.get("last_agent_message"):
            return str(payload["last_agent_message"])
    texts = assistant_messages(events)
    return texts[-1] if texts else ""


def final_answer_order(events: list[dict[str, Any]]) -> int:
    """How many calls had started when the last assistant message began; later calls came after the answer."""
    started, at_last_text = 0, None
    for event in events:
        payload = payload_of(event)
        if event.get("type") != "response_item":
            continue
        if payload.get("type") in codex_calls.CALL_TYPES:
            started += 1
        elif payload.get("type") == "message" and payload.get("role") == "assistant" and assistant_messages([event]):
            at_last_text = started
    return started if at_last_text is None else at_last_text


def error_text(event: dict[str, Any]) -> str:
    detail = event.get("error")
    message = detail.get("message") if isinstance(detail, dict) else event.get("message")
    return str(message or "")


def stream_state(events: list[dict[str, Any]]) -> dict[str, Any]:
    """What the `codex exec --json` stream says: whether a turn completed, and why a failure stopped it."""
    completed = any(event.get("type") == "turn.completed" for event in events)
    errors = [error_text(event) for event in events if event.get("type") in ("turn.failed", "error")]
    limit = next((text[:200] for text in errors if USAGE_LIMIT_PATTERN.search(text)), None)
    return {"completed": completed, "errors": errors, "usage_limit": limit}


def load_records(spec: RunSpec, run: dict[str, Any], expected_model: str) -> dict[str, Any]:
    """The Codex counterpart of the Claude record loader: view, facts, token reports, checks, and cap violations."""
    directory = spec.result_dir
    stream = transcript.read_jsonl(directory / "stream.jsonl")
    rollouts, calls = label_rollouts(collect.load_rollouts(directory / "codex", {}))
    main = rollouts[0] if rollouts else {"events": []}
    session = session_facts(main["events"])
    main_calls = [call for call in calls if call["source"] == "main"]
    runners = collect.load_runner_transcripts(directory / "transcripts" / "runner")
    assignments = collect.load_assignments(directory / "assignments")
    view = {
        "final_answer": final_answer(main["events"]), "assistant_texts": assistant_messages(main["events"]),
        "tool_calls": calls, "delegations": transcript.build_delegations(main_calls, assignments),
        "final_answer_order": final_answer_order(main["events"]), "approvals": [], "permission_denials": [],
    }
    by_source, _ = usage.claude_requests_by_source(None, [], [], runners)
    state = stream_state(stream)
    finished = any(payload_of(event).get("type") == "task_complete" for event in main["events"]) or state["completed"]
    facts = {"session_id": None, "permission_mode": session["approval_policy"], "model": session["model"], "plugins": [],
             "has_result": finished, "total_cost_usd": None, "duration_api_ms": None,
             "num_turns": len(usage.codex_requests(main["events"])) or None, "usage_limit": state["usage_limit"]}
    checks = {
        "loaded_from_export": bool((read_json(directory / SETUP_RECORD, {}) or {}).get("steps")), "installed_absent": True,
        "mod_marker_present": None, "subagent_models": {}, "permission_mode": session["approval_policy"],
        "sandbox": session["sandbox"], "model_as_requested": session["model"] == expected_model,
    }
    violations = caps.scan_run(stream_events=[], by_source=by_source, tool_calls=calls, rollouts=rollouts)
    return {"view": view, "facts": facts, "claude_report": usage.claude_token_report(by_source),
            "codex_report": usage.codex_token_report(rollouts), "checks": checks, "usage_source": "rollouts",
            "violations": violations, "session": session, "rollouts": rollouts}


def host_metrics(records: dict[str, Any]) -> dict[str, Any]:
    session = records["session"]
    return {
        "host": HOST_CODEX, "approval_handling": APPROVAL_HANDLING,
        "session": {"model": session["model"], "effort": session["effort"], "approval_policy": session["approval_policy"],
                    "sandbox": session["sandbox"]},
    }


def write_env(spec: RunSpec, records: dict[str, Any], base: Mapping[str, Any] | None = None) -> None:
    """Add the Codex CLI version and the session model and effort, read from the rollout, to the run's env.json."""
    path = spec.result_dir / "env.json"
    current = read_json(path, {}) or {}
    session = records["session"]
    version = session["cli_version"] or str((base or current).get("codex_version") or "").replace("codex-cli", "").strip() or None
    write_json(path, {**current, "host": HOST_CODEX, "codex_cli_version": version, "codex_session_model": session["model"],
                      "codex_session_effort": session["effort"], "codex_home": CODEX_HOME_NAME, "codex_home_isolated": True,
                      "codex_config_sha256": None})
