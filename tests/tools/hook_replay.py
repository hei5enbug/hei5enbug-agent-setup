"""Replay the recorded Bash and Edit calls of finished e2e runs through the hooks of two plugin trees and print each tree's
median and 90th-percentile hook time per call.

Usage: python3 tests/tools/hook_replay.py --before <plugin tree> --after <plugin tree> <run folder> [<run folder> ...]

A run folder holds a `view.json` with the run's recorded tool calls, as the e2e harness writes it. Each call is sent
again to the PreToolUse and PostToolUse hooks of each tree on Claude Code, in a temporary home with the approval guard
off, and the wall time of the hook processes of that call is summed. Run it outside an Orca terminal so the Orca skip is
measured. It is not collected by pytest.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
from pathlib import Path

E2E_ROOT = Path(__file__).resolve().parents[2] / "evals" / "e2e"
sys.path.insert(0, str(E2E_ROOT))

from harness import hook_facts  # noqa: E402

TOOLS = ("Bash", "Edit")


def call_times(tree: Path, runs: list[Path]) -> list[float]:
    times = []
    for run in runs:
        view = json.loads((run / "view.json").read_text(encoding="utf-8"))
        for call in (item for item in view.get("tool_calls", []) if item.get("name") in TOOLS):
            with tempfile.TemporaryDirectory() as home:
                env = {"HOME": home, "XDG_STATE_HOME": f"{home}/state", "CLAUDE_CONFIG_DIR": f"{home}/claude"}
                facts = hook_facts.replay(tree, "claude", [call], Path(home), env)
            times.append(facts["replay_total_seconds"])
    return times


def summary(times: list[float]) -> str:
    ordered = sorted(times)
    return f"calls {len(ordered)} median {statistics.median(ordered):.3f} p90 {ordered[max(0, int(len(ordered) * 0.9) - 1)]:.3f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("runs", nargs="+", type=Path)
    args = parser.parse_args()
    for label, tree in (("before", args.before), ("after", args.after)):
        times = call_times(tree, args.runs)
        if not times:
            print(f"{label}: the runs hold no Bash or Edit call")
            return 1
        print(f"{label} {summary(times)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
