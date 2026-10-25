"""JSON file storage for memos."""

from __future__ import annotations

import json
from pathlib import Path

from .memo import Memo, make_memo, memo_from_dict, memo_to_dict


class MemoNotFound(KeyError):
    def __init__(self, memo_id: int) -> None:
        super().__init__(f"no memo with id {memo_id}")
        self.memo_id = memo_id


class MemoStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def all(self) -> list[Memo]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return sorted((memo_from_dict(entry) for entry in raw), key=lambda memo: memo.id)

    def add(self, title: str, body: str = "", tags: tuple[str, ...] = ()) -> Memo:
        memos = self.all()
        next_id = max((memo.id for memo in memos), default=0) + 1
        memo = make_memo(next_id, title, body, tags)
        self._write([*memos, memo])
        return memo

    def get(self, memo_id: int) -> Memo:
        for memo in self.all():
            if memo.id == memo_id:
                return memo
        raise MemoNotFound(memo_id)

    def remove(self, memo_id: int) -> Memo:
        memos = self.all()
        removed = next((memo for memo in memos if memo.id == memo_id), None)
        if removed is None:
            raise MemoNotFound(memo_id)
        self._write([memo for memo in memos if memo.id != memo_id])
        return removed

    def search(self, query: str) -> list[Memo]:
        return [memo for memo in self.all() if memo.matches(query)]

    def _write(self, memos: list[Memo]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps([memo_to_dict(memo) for memo in memos], indent=2, ensure_ascii=False)
        self.path.write_text(payload + "\n", encoding="utf-8")
