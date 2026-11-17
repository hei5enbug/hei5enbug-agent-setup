"""The local database of visit counts."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from . import ROOT

MIGRATIONS = [
    ("create-visits", "CREATE TABLE visits (slug TEXT PRIMARY KEY, count INTEGER NOT NULL)"),
]


def default_path() -> Path:
    return Path(os.environ.get("DOCKIT_DB") or ROOT / "data" / "dockit.db")


class Store:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY)")
        return connection

    def migrate(self) -> list[str]:
        """Apply every migration that is not applied yet and return their names."""
        applied = []
        with self.connect() as connection:
            done = {row[0] for row in connection.execute("SELECT name FROM schema_migrations")}
            for name, statement in MIGRATIONS:
                if name not in done:
                    connection.execute(statement)
                    connection.execute("INSERT INTO schema_migrations (name) VALUES (?)", (name,))
                    applied.append(name)
        return applied

    @classmethod
    def open(cls, path: Path | str) -> "Store":
        store = cls(path)
        store.migrate()
        return store

    def record_visit(self, slug: str) -> int:
        """Add one visit to a page and return its new count."""
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO visits (slug, count) VALUES (?, 1) ON CONFLICT(slug) DO UPDATE SET count = count + 1", (slug,))
            return connection.execute("SELECT count FROM visits WHERE slug = ?", (slug,)).fetchone()[0]

    def visit_counts(self) -> dict[str, int]:
        with self.connect() as connection:
            return dict(connection.execute("SELECT slug, count FROM visits ORDER BY slug"))
