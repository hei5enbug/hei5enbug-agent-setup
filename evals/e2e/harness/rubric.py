"""Blind rubric grading: the artifact is scored by a reviewer model that never sees the variant, ref, or model under test."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from .config import (
    REPO_ROOT, RUBRIC_EFFORT, RUBRIC_FALLBACK_EFFORT, RUBRIC_FALLBACK_MODEL, RUBRIC_MODEL, RUBRIC_RETRY_EXITS,
)
from .matrix import read_json, write_json

Runner = Callable[..., subprocess.CompletedProcess]
RUBRIC_TIMEOUT_SECONDS = 1800
JSON_OBJECT = re.compile(r"\{.*\}", re.S)
OPAQUE_LENGTH = 16
_SALT_LOCK = threading.Lock()


def campaign_salt(base_dir: Path) -> str:
    """The random salt stored once in campaign.json; created on first use."""
    with _SALT_LOCK:
        path = base_dir / "campaign.json"
        data = read_json(path, {})
        salt = data.get("rubric_salt") if isinstance(data, dict) else None
        if not salt:
            salt = secrets.token_hex(16)
            write_json(path, {**(data if isinstance(data, dict) else {}), "rubric_salt": salt})
        return str(salt)


def opaque_dir(base_dir: Path, run_id: str) -> Path:
    """<campaign folder>/rubric/<opaque>: a name that does not reveal the task, variant, or repetition."""
    seed = f"{base_dir.name}\0{run_id}\0{campaign_salt(base_dir)}"
    return base_dir / "rubric" / hashlib.sha256(seed.encode("utf-8")).hexdigest()[:OPAQUE_LENGTH]


def artifact_text(rubric: dict[str, Any], repo: Path, final_answer: str) -> str:
    artifact = rubric["artifact"]
    if artifact.get("kind") == "final_answer":
        return final_answer
    try:
        return (repo / artifact["path"]).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def assignment_for(task_prompt: str, rubric: dict[str, Any], artifact: str) -> str:
    low, high = rubric.get("scale", [1, 5])
    criteria = "\n".join(
        f"- `{item['id']}` (weight {item.get('weight', 1)}): {item['description']}" for item in rubric["criteria"]
    )
    return (
        "# Grading assignment\n\nScore one deliverable against a rubric. Judge only what is in the deliverable. "
        "Do not edit any file.\n\n"
        f"## Task the author was given\n\n{task_prompt.strip()}\n\n"
        f"## Rubric\n\nScore every criterion with an integer from {low} (poor) to {high} (excellent):\n\n{criteria}\n\n"
        f"## Deliverable\n\n{artifact}\n\n"
        "## Answer format\n\nReply with one JSON object and nothing else: "
        '{"scores": {"<criterion id>": <integer>}, "rationale": {"<criterion id>": "<one sentence>"}}\n'
    )


def parse_scores(text: str, rubric: dict[str, Any]) -> dict[str, Any] | None:
    """Parse and validate the reviewer's JSON; None when it is malformed or misses a criterion."""
    match = JSON_OBJECT.search(text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except ValueError:
        return None
    scores = parsed.get("scores") if isinstance(parsed, dict) else None
    low, high = rubric.get("scale", [1, 5])
    ids = [item["id"] for item in rubric["criteria"]]
    if not isinstance(scores, dict) or any(not isinstance(scores.get(i), int) or not low <= scores[i] <= high for i in ids):
        return None
    rationale = parsed.get("rationale") if isinstance(parsed.get("rationale"), dict) else {}
    return {"scores": {i: scores[i] for i in ids}, "rationale": {str(k): str(v) for k, v in rationale.items()}}


def weighted_mean(scores: dict[str, int], rubric: dict[str, Any]) -> float:
    weights = {item["id"]: float(item.get("weight", 1)) for item in rubric["criteria"]}
    total = sum(weights.values())
    return sum(scores[i] * w for i, w in weights.items()) / total if total else 0.0


def finish(parsed: dict[str, Any], rubric: dict[str, Any], **extra: Any) -> dict[str, Any]:
    mean = weighted_mean(parsed["scores"], rubric)
    return {**parsed, "mean": mean, "passed": mean >= float(rubric.get("pass_mean", 0)), **extra}


def prepare_work_dir(work_dir: Path) -> None:
    """Codex refuses to run outside a git repository, so the grading folder becomes an empty one."""
    work_dir.mkdir(parents=True, exist_ok=True)
    if not (work_dir / ".git").exists():
        subprocess.run(["git", "init", "-q", str(work_dir)], capture_output=True, check=False)


def runner_status(completed: subprocess.CompletedProcess) -> dict[str, Any]:
    """The role runner's final JSON status line, or the tail of its output when there is none."""
    for line in reversed(str(completed.stdout or "").strip().splitlines()):
        try:
            status = json.loads(line)
        except ValueError:
            continue
        if isinstance(status, dict):
            return status
    return {"exit": completed.returncode, "output_tail": (str(completed.stdout or "") + str(completed.stderr or ""))[-800:]}


def run_primary(work_dir: Path, assignment: Path, result: Path, run: Runner, repo_root: Path) -> subprocess.CompletedProcess:
    command = [
        sys.executable, str(repo_root / "scripts/role_runner.py"), "reviewer", "--model", RUBRIC_MODEL,
        "--effort", RUBRIC_EFFORT, "--assignment", str(assignment), "--result", str(result),
    ]
    return run(command, cwd=work_dir, capture_output=True, text=True, timeout=RUBRIC_TIMEOUT_SECONDS, check=False)


def run_fallback(work_dir: Path, text: str, run: Runner) -> subprocess.CompletedProcess:
    command = [
        "claude", "-p", "--model", RUBRIC_FALLBACK_MODEL, "--effort", RUBRIC_FALLBACK_EFFORT, "--output-format", "json",
        "--permission-mode", "dontAsk", "--tools", "Read", "--strict-mcp-config",
    ]
    return run(command, cwd=work_dir, input=text, capture_output=True, text=True, timeout=RUBRIC_TIMEOUT_SECONDS, check=False)


def _fallback_answer(completed: subprocess.CompletedProcess) -> str:
    try:
        return str(json.loads(completed.stdout).get("result") or "")
    except (ValueError, AttributeError):
        return ""


def grade(
    task: dict[str, Any], artifact: str, task_prompt: str, work_dir: Path, run: Runner = subprocess.run,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Score the artifact blind. Uses the reviewer role first and the Claude fallback only after exit 3 or 4."""
    rubric = task["rubric"]
    low = rubric.get("scale", [1, 5])[0]
    if not artifact.strip():
        empty = {"scores": dict.fromkeys((i["id"] for i in rubric["criteria"]), low), "rationale": {}}
        return finish(empty, rubric, grader=None, fallback=False, empty_artifact=True)
    prepare_work_dir(work_dir)
    text = assignment_for(task_prompt, rubric, artifact)
    assignment, result = work_dir / "assignment.md", work_dir / "result.md"
    assignment.write_text(text, encoding="utf-8")
    result.unlink(missing_ok=True)
    primary = run_primary(work_dir, assignment, result, run, repo_root)
    status = runner_status(primary)
    if primary.returncode == 0:
        answer = result.read_text(encoding="utf-8", errors="replace") if result.is_file() else ""
        parsed = parse_scores(answer, rubric)
        if parsed:
            return finish(parsed, rubric, grader=RUBRIC_MODEL, fallback=False, runner_status=status)
        return {**_failed("primary result was not a valid score object", primary.returncode, RUBRIC_MODEL, False),
                "runner_status": status}
    if primary.returncode not in RUBRIC_RETRY_EXITS:
        return {**_failed(f"role_runner exit {primary.returncode}", primary.returncode, RUBRIC_MODEL, False),
                "runner_status": status}
    fallback = run_fallback(work_dir, text, run)
    parsed = parse_scores(_fallback_answer(fallback), rubric) if fallback.returncode == 0 else None
    if parsed:
        return finish(parsed, rubric, grader=RUBRIC_FALLBACK_MODEL, fallback=True, runner_status=status)
    return {**_failed("fallback result was not a valid score object", fallback.returncode, RUBRIC_FALLBACK_MODEL, True),
            "runner_status": status}


def _failed(error: str, code: int, grader: str, fallback: bool) -> dict[str, Any]:
    return {"scores": {}, "rationale": {}, "mean": None, "passed": False, "error": error, "exit": code,
            "grader": grader, "fallback": fallback}
