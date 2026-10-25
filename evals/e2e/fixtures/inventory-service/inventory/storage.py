"""JSON file storage. One file holds the whole database and is replaced atomically on every save."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .errors import StorageError
from .models import Database
from .serialization import SCHEMA_VERSION, database_from_dict, database_to_dict


class JsonStore:
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def load(self) -> Database:
        """Return the stored database, or an empty one when the file does not exist yet."""
        if not self.path.exists():
            return Database()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StorageError(f"cannot read {self.path}: {exc}") from exc
        if not isinstance(data, dict):
            raise StorageError(f"{self.path} does not contain a JSON object")
        schema = data.get("schema", SCHEMA_VERSION)
        if schema > SCHEMA_VERSION:
            raise StorageError(f"{self.path} uses schema {schema}, newer than {SCHEMA_VERSION}")
        try:
            return database_from_dict(data)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(f"{self.path} is corrupt: {exc!r}") from exc

    def save(self, db: Database) -> None:
        payload = json.dumps(database_to_dict(db), indent=2, sort_keys=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(dir=self.path.parent, prefix=".inventory-", suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.write("\n")
            os.replace(temp_name, self.path)
        except OSError as exc:
            Path(temp_name).unlink(missing_ok=True)
            raise StorageError(f"cannot write {self.path}: {exc}") from exc
