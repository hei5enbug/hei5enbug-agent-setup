"""The local database."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from . import ROOT, features


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
        """Apply every migration of every feature that is not applied yet and return their names."""
        applied = []
        with self.connect() as connection:
            done = {row[0] for row in connection.execute("SELECT name FROM schema_migrations")}
            for name, statement in features.migrations():
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
