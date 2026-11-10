"""Run one prompt on a model through its host CLI with plugins and tools off and effort high."""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

EFFORT = "high"
PLUGIN_OFF_SETTINGS = {"enabledPlugins": {"hei5enbug-agent-setup@hei5enbug": False}}
HOSTS = ("codex", "claude")


def parse_spec(spec: str) -> tuple:
    host, _, model = spec.partition(":")
    if host not in HOSTS or not model:
        raise ValueError(f"model spec must look like codex:<model id> or claude:<model id>, got {spec!r}")
    return host, model


def slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", model).strip("-")


def settings_file(out: Path) -> Path:
    path = out / "settings.json"
    path.write_text(json.dumps(PLUGIN_OFF_SETTINGS), encoding="utf-8")
    return path


def run_codex(model: str, prompt: str, out: Path, tag: str, timeout: int) -> dict:
    answer, log = out / "raw" / f"{tag}.txt", out / "raw" / f"{tag}.log"
    answer.unlink(missing_ok=True)
    command = ["codex", "exec", "-m", model, "-c", f'model_reasoning_effort="{EFFORT}"', "-s", "read-only",
               "--skip-git-repo-check", "--ephemeral", "--ignore-user-config", "--ignore-rules",
               "-C", str(out / "work"), "--json", "-o", str(answer), "-"]
    started = time.time()
    try:
        done = subprocess.run(command, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=out / "work")
    except (subprocess.TimeoutExpired, OSError) as error:
        return {"ok": False, "err": repr(error), "secs": time.time() - started}
    secs = time.time() - started
    log.write_text(done.stdout + "\n" + done.stderr, encoding="utf-8")
    usage = None
    for line in done.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.completed":
            usage = event.get("usage")
    if done.returncode != 0 or not answer.exists():
        return {"ok": False, "err": f"rc={done.returncode} {done.stderr[-300:]}", "secs": secs}
    return {"ok": True, "text": answer.read_text(encoding="utf-8").strip(), "secs": secs,
            "usage": usage, "cost": None, "model_ok": True}


def run_claude(model: str, prompt: str, out: Path, tag: str, timeout: int) -> dict:
    command = ["claude", "-p", "--model", model, "--effort", EFFORT, "--output-format", "json",
               "--strict-mcp-config", "--tools", "", "--settings", str(settings_file(out))]
    started = time.time()
    try:
        done = subprocess.run(command, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=out / "work")
    except (subprocess.TimeoutExpired, OSError) as error:
        return {"ok": False, "err": repr(error), "secs": time.time() - started}
    secs = time.time() - started
    (out / "raw" / f"{tag}.json").write_text(done.stdout, encoding="utf-8")
    try:
        payload = json.loads(done.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "err": f"rc={done.returncode} unparsable {done.stderr[-300:]}", "secs": secs}
    if payload.get("is_error") or done.returncode != 0:
        return {"ok": False, "err": f"rc={done.returncode} {str(payload.get('result'))[:300]}", "secs": secs}
    used = list(payload.get("modelUsage", {}))
    return {"ok": True, "text": payload["result"].strip(), "secs": secs, "usage": payload.get("usage"),
            "cost": payload.get("total_cost_usd"), "model_ok": model in used, "model_usage_keys": used}


def run_model(spec: str, prompt: str, out: Path, tag: str, timeout: int = 900) -> dict:
    host, model = parse_spec(spec)
    runner = run_codex if host == "codex" else run_claude
    return runner(model, prompt, out, tag, timeout)
