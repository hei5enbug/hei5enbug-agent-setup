import sys

from patch_tools import append, replace, write

repo = sys.argv[1]
write(repo, "notes_cli/export.py", '''"""Text export of memos."""

from __future__ import annotations

import csv
import io
from typing import Sequence

from .memo import Memo

FORMATS = ("csv", "markdown")


def export_memos(memos: Sequence[Memo], fmt: str) -> str:
    if fmt == "csv":
        return _csv(memos)
    if fmt == "markdown":
        return _markdown(memos)
    raise ValueError(f"unknown export format: {fmt}")


def _csv(memos: Sequence[Memo]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\\n")
    writer.writerow(["id", "title", "tags", "created_at"])
    for memo in memos:
        writer.writerow([memo.id, memo.title, ";".join(memo.tags), memo.created_at])
    return buffer.getvalue()


def _markdown(memos: Sequence[Memo]) -> str:
    blocks = []
    for memo in memos:
        lines = [f"## {memo.id}. {memo.title}"]
        if memo.tags:
            lines.append(f"Tags: {', '.join(memo.tags)}")
        if memo.body:
            lines.extend(["", memo.body])
        blocks.append("\\n".join(lines))
    return "\\n\\n".join(blocks) + "\\n" if blocks else ""
''')
replace(repo, "notes_cli/cli.py", "from .formatting import", "from .export import FORMATS, export_memos\nfrom .formatting import")
replace(repo, "notes_cli/cli.py", '    search.add_argument("query")\n',
        '    search.add_argument("query")\n    export = memo.add_parser("export", help="print memos as csv or markdown")\n'
        '    export.add_argument("--format", choices=FORMATS, default="csv")\n    export.add_argument("--tag")\n')
replace(repo, "notes_cli/cli.py", '    else:\n        found = store.search(args.query)',
        '    elif args.action == "export":\n        memos = [memo for memo in store.all() if args.tag is None or memo.has_tag(args.tag)]\n'
        '        out.write(export_memos(memos, args.format))\n    else:\n        found = store.search(args.query)')
write(repo, "tests/test_export.py", '''from notes_cli.export import export_memos
from notes_cli.memo import make_memo


def test_export_csv_has_header_and_rows():
    text = export_memos([make_memo(1, "Plan", "", ("a", "b"))], "csv")
    assert text.splitlines()[0] == "id,title,tags,created_at"
    assert text.splitlines()[1].startswith("1,Plan,a;b,")


def test_export_markdown_lists_the_title_and_tags():
    assert export_memos([make_memo(1, "Plan", "", ("a",))], "markdown") == "## 1. Plan\\nTags: a\\n"
''')
replace(repo, "README.md", "python3 -m notes_cli memo remove 1\n```", "python3 -m notes_cli memo remove 1\npython3 -m notes_cli memo export --format markdown\n```")
replace(repo, "README.md", "- `memo remove ID` deletes a memo.\n",
        "- `memo remove ID` deletes a memo.\n- `memo export [--format csv|markdown] [--tag TAG]` prints the memos as csv (the default) or markdown.\n")
replace(repo, "docs/ko/README.ko.md", "python3 -m notes_cli memo remove 1\n```", "python3 -m notes_cli memo remove 1\npython3 -m notes_cli memo export --format markdown\n```")
replace(repo, "docs/ko/README.ko.md", "- `memo remove ID`는 메모를 삭제합니다.\n",
        "- `memo remove ID`는 메모를 삭제합니다.\n- `memo export [--format csv|markdown] [--tag TAG]`는 메모를 csv(기본) 또는 markdown으로 출력합니다.\n")
