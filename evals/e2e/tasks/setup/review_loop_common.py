"""Shared by the setup scripts, the scripted review, and the checks of T67 to T69: the seeded documents and findings.

The review script keeps its run log beside the repository, so a check reads how often it ran. All data is fictional.
"""

from __future__ import annotations

import re
from pathlib import Path

GUIDE = "docs/guide.md"
SENTENCES = tuple(
    f"The demo-a service {topic}." for topic in (
        "reads the warehouse feed every hour", "keeps the last stock count of each shelf", "marks a shelf empty at zero",
        "sends one alert when a shelf is empty", "skips a feed line that has no shelf code", "logs each skipped feed line",
        "stores the log for a week", "rotates the log at midnight", "shows the shelf list on the dashboard",
        "sorts the shelf list by shelf code", "hides empty shelves unless asked", "refreshes the dashboard each minute",
        "exports the shelf list as a file on request", "names the export file after the date", "keeps ten exports",
        "deletes the oldest export first", "accepts a manual count from the dashboard", "records who gave the manual count",
        "overrides the feed count until the next feed run", "shows the override on the dashboard",
        "reports its own health at a fixed address", "answers the health check within a second",
        "restarts itself after three failed health checks", "writes the restart to the log",
    )
)
DIVERGE_RUNS = (tuple(range(0, 5)), tuple(range(5, 9)), tuple(range(9, 15)), tuple(range(15, 20)), tuple(range(20, 24)))
CONVERGE_RUNS = ((0, 1), (2, 3, 4), ())
REASON = "The sentence is vague about what the reader should do with it."
RETRY_FILES = ("docs/setup.md", "docs/guide.md", "docs/faq.md")
RETRY_WRONG = re.compile(r"retr(?:y|ies)[^.\n]*(?<![\w.])5(?!\w)", re.IGNORECASE)
RETRY_RIGHT = re.compile(r"retr(?:y|ies)[^.\n]*(?<![\w.])3(?!\w)", re.IGNORECASE)
SPREAD_DOCS = {
    "docs/setup.md": "# Setup\n\nInstall the feed reader first.\n\nThe retry limit of demo-a is 5.\n",
    "docs/guide.md": "# Guide\n\nUse the dashboard every day.\n\nThe retry limit of demo-a is 5.\n",
    "docs/faq.md": "# FAQ\n\nHow often does demo-a retry? It retries a failed call at most 5 times, which is its retry limit.\n",
    "docs/decisions.md": "# Decisions\n\n- demo-a retry limit: 3 (decided in the January review).\n",
}


def guide_text() -> str:
    return "# demo-a service guide\n\n" + "\n".join(SENTENCES) + "\n"


def quotes(indexes: tuple[int, ...]) -> list[str]:
    return [SENTENCES[index] for index in indexes]


def log_lines(state: Path) -> list[dict]:
    import json
    path = Path(state) / "runs.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
