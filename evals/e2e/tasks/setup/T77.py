"""Seed the notes-cli repository with the definition of a demo.orders table that has two columns nobody reads."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TABLE = """CREATE TABLE demo.orders (
    id           BIGINT PRIMARY KEY,
    customer_id  BIGINT NOT NULL,
    status       TEXT NOT NULL,
    legacy_code  TEXT,
    old_status   TEXT,
    created_at   TIMESTAMP NOT NULL
);

-- legacy_code: empty for every row since 2025.
-- old_status: a copy of status that nothing reads any more.
"""


def commit(root: Path, message: str) -> None:
    for command in (["git", "add", "-A"], ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
                                            "commit", "-q", "-m", message]):
        subprocess.run(command, cwd=root, check=True, capture_output=True)


def main(repo: str) -> None:
    root = Path(repo)
    path = root / "db" / "demo_orders.sql"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TABLE, encoding="utf-8")
    commit(root, "feat: add the demo orders table")


if __name__ == "__main__":
    main(sys.argv[1])
