from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from .locks import FileLock


class GrantStoreError(ValueError):
    """The grant file cannot be read."""


class GrantStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _load(self) -> dict[str, list[str]]:
        try:
            text = self.path.read_text()
        except FileNotFoundError:
            return {}
        try:
            data = json.loads(text)
        except ValueError as error:
            raise GrantStoreError(f"{self.path} is not valid JSON") from error
        if not isinstance(data, dict):
            raise GrantStoreError(f"{self.path} does not hold an object")
        return data

    def _save(self, data: dict[str, list[str]]) -> None:
        temporary = self.path.with_name(f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        temporary.write_text(json.dumps(data))
        os.replace(temporary, self.path)

    def _lock(self) -> FileLock:
        return FileLock(self.path.with_name(self.path.name + ".lock"))

    def grant(self, session: str, key: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock():
            data = self._load()
            keys = data.setdefault(session, [])
            if key not in keys:
                keys.append(key)
            self._save(data)

    def has(self, session: str, key: str) -> bool:
        return key in self._load().get(session, [])

    def revoke_session(self, session: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock():
            data = self._load()
            data.pop(session, None)
            self._save(data)
