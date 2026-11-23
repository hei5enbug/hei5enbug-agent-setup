"""A client for the file storage that holds exports."""

from __future__ import annotations

from pathlib import Path


class StorageError(OSError):
    """The storage did not accept an upload."""


class StorageClient:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def upload(self, name: str, data: bytes) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_bytes(data)
        except OSError as exc:
            raise StorageError(f"upload of {name} failed: {exc}") from exc
