"""Run bounded native Codex comparisons in disposable read-only workspaces."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import statistics
import subprocess
import time
from pathlib import Path


CASES = {
    "frontier": (
        "decision-navigator",
        "Inspect .decision-navigator/retries/map.md and its tickets. Report which ticket is eligible "
        "and which is blocked, with evidence. This is an explicitly read-only metadata inspection: "
        "do not claim, resolve, edit, or implement anything, and do not start an interview.",
    ),
    "missing-scoring": (
        "deep-interview",
        "Run a rigorous requirements interview for an execution-ready invoice specification. "
        "The scoring-and-state.md reference is intentionally unavailable in this disposable skill copy. "
        "Respect the missing-resource contract before scoring or asking; report the limitation.",
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--case", choices=CASES, required=True)
    parser.add_argument("--pairs", type=int, choices=(1, 2, 3), default=3)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    repository = Path(__file__).resolve().parents[2]
    if output.is_relative_to(repository):
        parser.error("output-dir must be outside the source repository")
    if output.exists() and any(output.iterdir()):
        parser.error("output-dir must be empty")
    output.mkdir(parents=True, exist_ok=True)
    old_name, task = CASES[args.case]
    frozen = output / "_sources"
    for version, source in (("old", args.baseline_root / "skills" / old_name), ("new", args.candidate)):
        shutil.copytree(source, frozen / version, ignore=shutil.ignore_patterns("__pycache__", "tests", "evals"))
    hashes = {
        side: {str(p.relative_to(frozen / side)): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted((frozen / side).rglob("*")) if p.is_file()}
        for side in ("old", "new")
    }
    results = []
    for pair in range(1, args.pairs + 1):
        order = ("old", "new") if pair % 2 else ("new", "old")
        for version in order:
            run = output / f"pair-{pair}-{version}"
            run.mkdir()
            shutil.copytree(frozen / version, run / "skill")
            if args.case == "frontier":
                fixture = args.baseline_root / "skills/decision-navigator/evals/files/frontier-race"
                shutil.copytree(fixture, run / ".decision-navigator/retries")
            else:
                (run / "skill/references/scoring-and-state.md").unlink()
            prompt = (f"Use the skill at {run / 'skill/SKILL.md'}. "
                      "Read that entrypoint alone before any task-dependent file access.\n"
                      f"{task}\n")
            (run / "prompt.txt").write_text(prompt)
            command = [
                "codex", "exec", "--ignore-user-config", "--strict-config", "--ephemeral",
                "--skip-git-repo-check", "--sandbox", "read-only", "--model", "gpt-5.6-luna",
                "-c", 'model_reasoning_effort="xhigh"', "--json", "-C", str(run),
                "--output-last-message", str(run / "answer.txt"), "-",
            ]
            started = time.monotonic()
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, start_new_session=True)
            try:
                stdout, stderr = process.communicate(input=prompt, timeout=240)
                code = process.returncode
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    stdout, stderr = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    stdout, stderr = process.communicate()
                code = 124
            elapsed = round(time.monotonic() - started, 3)
            (run / "events.jsonl").write_text(stdout)
            (run / "stderr.txt").write_text(stderr)
            events = []
            for line in stdout.splitlines():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            usage = [e.get("usage") for e in events if e.get("type") == "turn.completed"]
            commands = [e["item"] for e in events if e.get("type") == "item.completed"
                        and e.get("item", {}).get("type") == "command_execution"]
            record = {
                "pair": pair, "version": version, "returncode": code, "elapsed_seconds": elapsed,
                "requested_model": "gpt-5.6-luna", "requested_effort": "xhigh",
                "reported_model": None, "usage": usage or None,
                "completed_commands": len(commands), "workspace": str(run),
            }
            results.append(record)
            (run / "receipt.json").write_text(json.dumps(record, indent=2) + "\n")
            print(json.dumps(record), flush=True)
            stats = {}
            for side in ("old", "new"):
                values = [r["elapsed_seconds"] for r in results if r["version"] == side and not r["returncode"]]
                if values:
                    stats[side] = {"median_seconds": statistics.median(values), "max_seconds": max(values)}
            report = {"case": args.case, "native_ui_coverage": False,
                      "source_sha256": hashes, "results": results, "stats": stats}
            (output / "comparison.json").write_text(json.dumps(report, indent=2) + "\n")
            if code:
                return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
