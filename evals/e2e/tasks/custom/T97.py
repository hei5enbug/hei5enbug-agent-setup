"""Custom checks for T97: a one-line edit whose final report is under the length threshold gets no text review."""

from __future__ import annotations

import re
from pathlib import Path

THRESHOLD = re.compile(r"^MINIMUM_REPORT_CHARACTERS = (\d+)$", re.MULTILINE)
REVIEW_RUN = re.compile(r"python[0-9.]*\s+(?:-\S+\s+)*\S*text_review\.py[\"']?(?:\s+-\S+)*\s+(?:review|check)\b")


def single_line_changed(ctx):
    stat = [line.split("\t") for line in ctx.git("diff", "--numstat", ctx.base).splitlines() if line]
    ok = len(stat) == 1 and stat[0][:2] == ["1", "1"]
    return ok, f"numstat: {stat}", {"numstat": stat}


def threshold(ctx) -> int:
    path = Path(ctx.tasks_root).resolve().parents[2] / "scripts" / "final_report_hook.py"
    return int(THRESHOLD.search(path.read_text(encoding="utf-8")).group(1))


def report_length(ctx) -> int:
    return len(str(ctx.view.get("final_answer", "")).strip())


def review_runs(ctx) -> list[str]:
    return [str(call.get("input", {}).get("command", ""))[:160] for call in ctx.view.get("tool_calls", [])
            if call.get("name") == "Bash" and REVIEW_RUN.search(str(call.get("input", {}).get("command", "")))]


def report_is_short(ctx):
    length, limit = report_length(ctx), threshold(ctx)
    return length < limit, f"the final report has {length} characters, the threshold is {limit}", {}


def short_report_not_reviewed(ctx):
    length, limit, runs = report_length(ctx), threshold(ctx), review_runs(ctx)
    if length >= limit:
        return True, f"the final report has {length} characters, not under {limit}, so the rule does not apply", {}
    return not runs, (f"{len(runs)} text_review.py run(s) for a {length}-character report under {limit}" if runs
                      else f"no text_review.py run for a {length}-character report under {limit}"), {"runs": runs}
