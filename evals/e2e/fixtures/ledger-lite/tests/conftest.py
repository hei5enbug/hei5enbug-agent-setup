from __future__ import annotations

import os
from pathlib import Path

import pytest

from ledger.journal import Journal, load_entries


@pytest.fixture(scope="session", autouse=True)
def sample_dir() -> Path:
    value = os.environ.get("SAMPLE_DATA_DIR")
    if not value:
        raise RuntimeError("SAMPLE_DATA_DIR is not set. The tests read their sample files from it; see docs/testing.md.")
    path = Path(value)
    if not path.is_dir():
        raise RuntimeError(f"SAMPLE_DATA_DIR={value} is not a directory; see docs/testing.md.")
    return path


@pytest.fixture
def march_journal(sample_dir: Path) -> Journal:
    return load_entries(sample_dir / "march_entries.csv")
