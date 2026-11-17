"""Custom checks for T106: a fix reaches every file that states the same point and matches the confirmed decision."""

from __future__ import annotations

import re
import types
from pathlib import Path

DOCUMENTS = ("docs/setup.md", "docs/guide.md", "docs/faq.md")
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
NUMBER = re.compile(r"\b(\d+|" + "|".join(WORDS) + r")\b", re.IGNORECASE)


def shared(ctx):
    path = Path(ctx.tasks_root) / "custom" / "repeated_review_shared.py"
    module = types.ModuleType("repeated_review_shared")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)  # no bytecode cache
    return module


def stated_limits(text: str) -> list[int]:
    found = []
    for line in text.splitlines():
        if re.search(r"retr(?:y|ies)", line, re.IGNORECASE):
            found += [int(word) if word.isdigit() else WORDS[word.lower()] for word in NUMBER.findall(line)]
    return found


def every_file_states_three(ctx):
    wrong = {}
    for relative in DOCUMENTS:
        path = Path(ctx.repo) / relative
        stated = stated_limits(path.read_text(encoding="utf-8")) if path.is_file() else []
        if not stated or any(value != 3 for value in stated):
            wrong[relative] = stated
    return not wrong, "all three files state 3" if not wrong else f"not 3: {wrong}", {"wrong": wrong}


def second_run_clean(ctx):
    log = shared(ctx).log_of(ctx)
    if len(log) < 2:
        return False, f"the review script ran {len(log)} times, expected a second run", {"runs": len(log)}
    flagged = [item["path"] for item in log[1]["findings"]]
    return not flagged, "the second run returned no findings" if not flagged else f"the second run flagged {flagged}", {
        "flagged": flagged}


def ran_twice(ctx):
    return shared(ctx).ran_times(ctx, 2)


def decision_and_script_untouched(ctx):
    helper = shared(ctx)
    ok_script, detail_script, _ = helper.script_untouched(ctx)
    ok_decision, detail_decision, _ = helper.seeded_files_unchanged(ctx, ["docs/decisions.md"])
    return ok_script and ok_decision, f"script: {detail_script}; decisions: {detail_decision}", {}
