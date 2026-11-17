"""Seed T105: the T104 guide and a review script whose counts rise and then reach zero: 2, 3, and then no findings."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from repeated_review_common import guide_files, guide_pool, install  # noqa: E402

COUNTS = [2, 3, 0]


def main(repo: str) -> None:
    install(Path(repo), {"mode": "pool", "counts": COUNTS, "pool": guide_pool()}, guide_files())


if __name__ == "__main__":
    main(sys.argv[1])
