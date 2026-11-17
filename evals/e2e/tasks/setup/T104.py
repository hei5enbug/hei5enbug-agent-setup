"""Seed T104: docs/guide.md with many vague sentences and a review script that keeps finding new ones.

The script returns 5, 4, 6, 5, 5, 4, and 3 low-severity findings on its first seven runs, each in a sentence no earlier
run flagged. Its run count and log live in `review-state/` beside the repository.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from repeated_review_common import guide_files, guide_pool, install  # noqa: E402

COUNTS = [5, 4, 6, 5, 5, 4, 3]


def main(repo: str) -> None:
    install(Path(repo), {"mode": "pool", "counts": COUNTS, "pool": guide_pool()}, guide_files())


if __name__ == "__main__":
    main(sys.argv[1])
