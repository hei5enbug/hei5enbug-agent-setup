from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .locks import FileLock


class Refresher:
    def __init__(self, root: Path, send: Callable[[str, str], bool]) -> None:
        self.root = Path(root)
        self.send = send

    @property
    def state_path(self) -> Path:
        return self.root / "state.json"

    def state(self) -> dict[str, str]:
        try:
            return json.loads(self.state_path.read_text())
        except FileNotFoundError:
            return {}

    def record(self, session: str, status: str) -> None:
        with FileLock(self.root / "sessions.lock"):
            state = self.state()
            state[session] = status
            self.state_path.write_text(json.dumps(state))

    def run(self, sessions: list[str]) -> dict[str, str]:
        results: dict[str, str] = {}
        with FileLock(self.root / "sessions.lock"):
            for session in sessions:
                try:
                    ok = self.send(session, "refresh")
                except Exception:
                    ok = False
                results[session] = "sent" if ok else "failed"
                state = self.state()
                state[session] = results[session]
                self.state_path.write_text(json.dumps(state))
        return results
