"""Seed the ops-notes repository with four documents that must agree on one decision and a scripted review for T132."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from review_loop_install import install  # noqa: E402

import review_loop_common as common  # noqa: E402

if __name__ == "__main__":
    install(Path(sys.argv[1]), common.SPREAD_DOCS)
