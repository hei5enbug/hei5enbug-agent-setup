import os
import sys

from patch_tools import write

repo = sys.argv[1]
skipped = {name for name in os.environ.get("T56_SKIP_CHANGES", "").split(",") if name}


def pins_change() -> None:
    write(repo, "dockit/features/pins.py", '''"""Pinned pages."""

from __future__ import annotations

MIGRATIONS = [("create-pins", "CREATE TABLE pins (slug TEXT PRIMARY KEY)")]


def pin(store, slug: str) -> None:
    with store.connect() as connection:
        connection.execute("INSERT OR IGNORE INTO pins (slug) VALUES (?)", (slug,))


def unpin(store, slug: str) -> None:
    with store.connect() as connection:
        connection.execute("DELETE FROM pins WHERE slug = ?", (slug,))


def pinned(store) -> list[str]:
    with store.connect() as connection:
        return [row[0] for row in connection.execute("SELECT slug FROM pins ORDER BY slug")]


def register(commands) -> None:
    for name in ("pin", "unpin"):
        commands.add_parser(name, help=f"{name} a page").add_argument("slug")
    commands.add_parser("pins", help="print the pinned pages")


def handle(args, store) -> bool:
    if args.command == "pin":
        pin(store, args.slug)
        print(f"Pinned {args.slug}")
    elif args.command == "unpin":
        unpin(store, args.slug)
        print(f"Unpinned {args.slug}")
    elif args.command == "pins":
        for slug in pinned(store):
            print(slug)
    else:
        return False
    return True
''')
    write(repo, "docs/features/pins.md",
          "# Pins\n\n- `pin SLUG` and `unpin SLUG` mark and unmark a page and print `Pinned SLUG` or `Unpinned SLUG`.\n"
          "- `pins` prints the pinned pages, one per line.\n")
    write(repo, "docs/ko/docs/features/pins.ko.md",
          "# 고정\n\n> 영어 원본: [pins.md](../../../features/pins.md). 이 문서는 번역본이며 원본보다 우선하지 않습니다.\n\n"
          "- `pin SLUG`와 `unpin SLUG`는 페이지에 표시를 하고 지우며 `Pinned SLUG` 또는 `Unpinned SLUG`를 출력합니다.\n"
          "- `pins`는 표시한 페이지를 한 줄에 하나씩 출력합니다.\n")
    write(repo, "tests/test_pins.py", '''from dockit.features import pins
from dockit.store import Store


def test_pin_and_unpin(shared_db):
    store = Store.open(shared_db)
    pins.pin(store, "guide")
    pins.pin(store, "guide")
    assert pins.pinned(store) == ["guide"]
    pins.unpin(store, "guide")
    assert pins.pinned(store) == []
''')


def notes_change() -> None:
    write(repo, "dockit/features/notes.py", '''"""Notes on pages."""

from __future__ import annotations

MIGRATIONS = [
    ("create-notes", "CREATE TABLE notes (id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT NOT NULL, text TEXT NOT NULL)"),
]


def add_note(store, slug: str, text: str) -> int:
    with store.connect() as connection:
        return connection.execute("INSERT INTO notes (slug, text) VALUES (?, ?)", (slug, text)).lastrowid


def notes_of(store, slug: str) -> list[str]:
    with store.connect() as connection:
        return [row[0] for row in connection.execute("SELECT text FROM notes WHERE slug = ? ORDER BY id", (slug,))]


def register(commands) -> None:
    note = commands.add_parser("note", help="save a note on a page")
    note.add_argument("slug")
    note.add_argument("text")
    commands.add_parser("notes", help="print the notes of a page").add_argument("slug")


def handle(args, store) -> bool:
    if args.command == "note":
        print(f"Saved note {add_note(store, args.slug, args.text)} for {args.slug}")
    elif args.command == "notes":
        for number, text in enumerate(notes_of(store, args.slug), start=1):
            print(f"{number}: {text}")
    else:
        return False
    return True
''')
    write(repo, "docs/features/notes.md",
          "# Notes\n\n- `note SLUG TEXT` saves a note on a page and prints `Saved note N for SLUG`.\n"
          "- `notes SLUG` prints the notes of a page as `K: TEXT`, in the order they were saved.\n")
    write(repo, "docs/ko/docs/features/notes.ko.md",
          "# 메모\n\n> 영어 원본: [notes.md](../../../features/notes.md). 이 문서는 번역본이며 원본보다 우선하지 않습니다.\n\n"
          "- `note SLUG TEXT`는 페이지에 메모를 저장하고 `Saved note N for SLUG`를 출력합니다.\n"
          "- `notes SLUG`는 페이지의 메모를 저장한 순서대로 `K: TEXT`로 출력합니다.\n")
    write(repo, "tests/test_notes.py", '''from dockit.features import notes
from dockit.store import Store


def test_notes_come_back_in_order(shared_db):
    store = Store.open(shared_db)
    notes.add_note(store, "guide", "one")
    notes.add_note(store, "guide", "two")
    assert notes.notes_of(store, "guide") == ["one", "two"]
''')


if "pins" not in skipped:
    pins_change()
if "notes" not in skipped:
    notes_change()
