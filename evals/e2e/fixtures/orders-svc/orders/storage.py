"""A small storage client that keeps objects as files under a root folder."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent / "data" / "export"


class StorageError(OSError):
    """An object could not be stored."""


class StorageClient:
    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)

    def put(self, key: str, data: bytes) -> None:
        try:
            target = self.root / key
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        except OSError as exc:
            raise StorageError(f"cannot store {key}: {exc}") from exc


def default_client() -> StorageClient:
    return StorageClient(os.environ.get("ORDERS_STORAGE_DIR") or DEFAULT_ROOT)
