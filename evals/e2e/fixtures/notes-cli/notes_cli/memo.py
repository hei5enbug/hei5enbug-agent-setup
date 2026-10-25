"""The memo record and its JSON conversion."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Memo:
    id: int
    title: str
    body: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    created_at: str = ""

    def matches(self, query: str) -> bool:
        needle = query.casefold()
        return needle in self.title.casefold() or needle in self.body.casefold()

    def has_tag(self, tag: str) -> bool:
        return tag.casefold() in (existing.casefold() for existing in self.tags)


def make_memo(memo_id: int, title: str, body: str = "", tags: tuple[str, ...] = ()) -> Memo:
    title = title.strip()
    if not title:
        raise ValueError("a memo needs a title")
    cleaned = tuple(dict.fromkeys(tag.strip().lower() for tag in tags if tag.strip()))
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return Memo(id=memo_id, title=title, body=body.strip(), tags=cleaned, created_at=created)


def memo_to_dict(memo: Memo) -> dict[str, Any]:
    return {
        "id": memo.id,
        "title": memo.title,
        "body": memo.body,
        "tags": list(memo.tags),
        "created_at": memo.created_at,
    }


def memo_from_dict(data: dict[str, Any]) -> Memo:
    return Memo(
        id=int(data["id"]),
        title=str(data["title"]),
        body=str(data.get("body", "")),
        tags=tuple(data.get("tags", [])),
        created_at=str(data.get("created_at", "")),
    )
