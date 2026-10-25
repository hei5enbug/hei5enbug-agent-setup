"""Plain-text rendering."""

from __future__ import annotations

from typing import Sequence

from .memo import Memo


def format_memo_line(memo: Memo) -> str:
    tags = f"  [{', '.join(memo.tags)}]" if memo.tags else ""
    return f"{memo.id:>4}  {memo.title}{tags}"


def format_memo_detail(memo: Memo) -> str:
    lines = [f"Memo #{memo.id}: {memo.title}"]
    if memo.tags:
        lines.append(f"Tags: {', '.join(memo.tags)}")
    lines.append(f"Created: {memo.created_at}")
    if memo.body:
        lines.extend(["", memo.body])
    return "\n".join(lines)


def format_page(memos: Sequence[Memo], page: int, page_size: int) -> str:
    pages = max(1, -(-len(memos) // page_size))
    page = min(max(page, 1), pages)
    start = (page - 1) * page_size
    lines = [format_memo_line(memo) for memo in memos[start:start + page_size]]
    if not lines:
        return "No memos."
    lines.append(f"-- page {page}/{pages}, {len(memos)} memos --")
    return "\n".join(lines)
