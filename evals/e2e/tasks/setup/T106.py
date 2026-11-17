"""Seed T106: three documents that state the retry limit of demo-a as 5, and a decision that sets it to 3.

The review script's first run flags only the limit in docs/setup.md. Any later run flags each file that does not state
3, so a fix that stays in docs/setup.md fails the second run.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from repeated_review_common import install  # noqa: E402

SETUP = """# demo-a setup

Install `demo-a` with `pip install demo-a` and run `demo-a init` in the project folder.

Set the retry limit of `demo-a` to 5 attempts in `demo-a.toml` before the first deploy.

Run `demo-a doctor` to check the connection to the shared folder.
"""

GUIDE = """# demo-a guide

## Sync

Run `demo-a sync` to copy new and changed notes to the shared folder.

When a call to the shared folder fails, `demo-a` retries it up to 5 times, which is the retry limit.

A conflict keeps both versions and marks the newer one.

## Export

Export notes with `demo-a export`; the files are written to `out/` in the project folder.
"""

FAQ = """# demo-a FAQ

## How many times does demo-a retry a failed sync?

It retries up to 5 times. This retry limit applies to every sync.

## Where are the logs?

Logs are in `.demo-a-logs/` in the project folder.
"""

DECISIONS = """# Decisions

## D-7: retry limit of demo-a

Confirmed: the retry limit of `demo-a` is 3.
"""

FILES = {"docs/setup.md": SETUP, "docs/guide.md": GUIDE, "docs/faq.md": FAQ, "docs/decisions.md": DECISIONS}

SCENARIO = {
    "mode": "decision", "decision": 3, "files": ["docs/setup.md", "docs/guide.md", "docs/faq.md"],
    "first_run_path": "docs/setup.md",
    "first_run_reason": "states 5, but docs/decisions.md sets the retry limit to 3",
}


def main(repo: str) -> None:
    install(Path(repo), SCENARIO, FILES)


if __name__ == "__main__":
    main(sys.argv[1])
