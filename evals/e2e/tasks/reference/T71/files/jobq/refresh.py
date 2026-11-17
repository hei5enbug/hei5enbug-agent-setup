from __future__ import annotations

import json
import os
import threading
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
        with FileLock(self.root / "state.lock"):
            state = self.state()
            state[session] = status
            temporary = self.state_path.with_name(f"state.json.{os.getpid()}.{threading.get_ident()}.tmp")
            temporary.write_text(json.dumps(state))
            os.replace(temporary, self.state_path)

    def run(self, sessions: list[str]) -> dict[str, str]:
        results: dict[str, str] = {}
        for session in sessions:
            with FileLock(self.root / "sessions.lock"):
                try:
                    ok = self.send(session, "refresh")
                except Exception:
                    ok = False
            results[session] = "sent" if ok else "failed"
            self.record(session, results[session])
        return results
