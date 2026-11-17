from __future__ import annotations

import json
from pathlib import Path


class GrantStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _load(self) -> dict[str, list[str]]:
        try:
            return json.loads(self.path.read_text())
        except FileNotFoundError:
            return {}

    def grant(self, session: str, key: str) -> None:
        data = self._load()
        keys = data.setdefault(session, [])
        if key not in keys:
            keys.append(key)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data))

    def has(self, session: str, key: str) -> bool:
        return key in self._load().get(session, [])

    def revoke_session(self, session: str) -> None:
        data = self._load()
        data.pop(session, None)
        self.path.write_text(json.dumps(data))
