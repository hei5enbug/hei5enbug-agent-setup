"""Shared pieces of the GPT role comparison: the candidate sets, the plugin copy that lets the role runner start every
candidate, the list-price cost and wall time of a Codex run read from its rollout, and the result files."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tarfile
import time
from io import BytesIO
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(REPO_ROOT / "evals" / "e2e"))

from harness import pricing, usage  # noqa: E402

SOL_CANDIDATES = ("gpt-6.1-sol", "gpt-6.2-sol", "gpt-6.1-terra", "gpt-6-luna")
LUNA_CANDIDATES = ("gpt-5.6-luna", "gpt-6-luna")
ALL_CANDIDATES = tuple(dict.fromkeys(SOL_CANDIDATES + LUNA_CANDIDATES))
EXTRA_RUNNER_MODELS = ("gpt-6.2-sol", "gpt-6-luna")
RESULT_KEYS = ("role", "case", "model", "effort", "rep", "passed", "failures", "cost_usd", "wall_seconds", "rollout")


def plugin_copy(out: Path, ref: str = "HEAD", extra_models: tuple[str, ...] = EXTRA_RUNNER_MODELS) -> Path:
    """Export `ref` of this repository into `out` (git archive, as the harness does) and let its role runner start the
    extra candidate models. The copy changes only `runner.review_models`; nothing in the repository itself changes."""
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    packed = subprocess.run(["git", "-C", str(REPO_ROOT), "archive", ref], capture_output=True, check=True).stdout
    with tarfile.open(fileobj=BytesIO(packed)) as archive:
        archive.extractall(out, filter="data")
    registry_path = out / "config" / "model-registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    listed = registry["runner"]["review_models"]
    registry["runner"]["review_models"] = [*listed, *(model for model in extra_models if model not in listed)]
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    return out


def last_json_line(text: str) -> dict[str, Any] | None:
    for line in reversed(text.strip().splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def verified_status(stdout: str, model: str, effort: str) -> dict[str, Any]:
    """The role runner's last status line, required to show a verified run of exactly this model and effort."""
    status = last_json_line(stdout)
    if status is None:
        raise ValueError("the runner printed no status line")
    if status.get("exit") != 0 or status.get("verified") is not True:
        raise ValueError(f"the runner did not verify the run: {json.dumps(status)[:300]}")
    if status.get("model") != model or status.get("effort") != effort:
        raise ValueError(f"the runner ran {status.get('model')} at {status.get('effort')}, expected {model} at {effort}")
    return status


def read_events(path: Path) -> list[dict[str, Any]]:
    events = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def rollout_cost(path: Path, model: str) -> float:
    """List-price cost of every request in a Codex rollout. A request the rollout labels with another model, or a model
    without a listed price, is an error: the comparison never records a cost it cannot price."""
    total = 0.0
    requests = usage.codex_requests(read_events(path))
    if not requests:
        raise ValueError(f"{path} holds no token_count request")
    for request in requests:
        if request["model"] != model:
            raise ValueError(f"{path} answered with {request['model']}, expected {model}")
        price = pricing.codex_cost(model, request)
        if price is None:
            raise ValueError(f"{model} has no listed price in harness/pricing.py")
        total += price
    return round(total, 6)


def rollouts_since(started: float, cwd_prefix: str, model: str, home: Path | None = None) -> list[Path]:
    """Codex rollouts written since `started` (epoch seconds) by `model`, whose session folder name starts with `cwd_prefix`.
    Another Codex session on the machine may write a rollout of its own at the same time, so the model filters it."""
    found = []
    for path in sorted(((home or Path.home() / ".codex") / "sessions").glob("**/rollout-*.jsonl")):
        if path.stat().st_mtime < started - 2:
            continue
        events = read_events(path)
        meta = next((e.get("payload") for e in events if e.get("type") == "session_meta" and isinstance(e.get("payload"), dict)), {})
        turn = next((e.get("payload") for e in events if e.get("type") == "turn_context" and isinstance(e.get("payload"), dict)), {})
        if Path(str(meta.get("cwd", ""))).name.startswith(cwd_prefix) and turn.get("model") == model:
            found.append(path)
    return found


def usage_cost(model: str, tokens: dict[str, Any]) -> float:
    """List-price cost of one `codex exec --json` turn.completed usage record (input, cached input, output tokens)."""
    cached = int(tokens.get("cached_input_tokens") or 0)
    written = int(tokens.get("cache_write_input_tokens") or 0)
    request = {"input": max(int(tokens.get("input_tokens") or 0) - cached - written, 0), "cache_read": cached, "cache_write": written,
               "output": int(tokens.get("output_tokens") or 0)}
    price = pricing.codex_cost(model, request)
    if price is None:
        raise ValueError(f"{model} has no listed price in harness/pricing.py")
    return round(price, 6)


def run_timed(argv: list[str], cwd: Path, stdin: str | None = None, env: dict[str, str] | None = None) -> tuple[subprocess.CompletedProcess, float]:
    started = time.monotonic()
    done = subprocess.run(argv, cwd=cwd, input=stdin, capture_output=True, text=True, env=env)
    return done, round(time.monotonic() - started, 3)


def result_path(out: Path, role: str, case: str, model: str, rep: int) -> Path:
    return out / "results" / f"{role}__{case}__{model}__r{rep}.json"


def write_result(out: Path, result: dict[str, Any]) -> Path:
    path = result_path(out, result["role"], result["case"], result["model"], result["rep"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def load_results(out: Path) -> list[dict[str, Any]]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted((out / "results").glob("*.json"))]
