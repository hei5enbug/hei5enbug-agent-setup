import os
import sys

from patch_tools import replace, write

repo = sys.argv[1]
skipped = {name for name in os.environ.get("T56_SKIP_CHANGES", "").split(",") if name}


def pins_change() -> None:
    replace(repo, "dockit/store.py", '    ("create-visits", "CREATE TABLE visits (slug TEXT PRIMARY KEY, count INTEGER NOT NULL)"),\n',
            '    ("create-visits", "CREATE TABLE visits (slug TEXT PRIMARY KEY, count INTEGER NOT NULL)"),\n'
            '    ("create-pins", "CREATE TABLE pins (slug TEXT PRIMARY KEY)"),\n')
    replace(repo, "dockit/store.py", "    def visit_counts(self)", '''    def pin(self, slug: str) -> None:
        with self.connect() as connection:
            connection.execute("INSERT OR IGNORE INTO pins (slug) VALUES (?)", (slug,))

    def unpin(self, slug: str) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM pins WHERE slug = ?", (slug,))

    def pins(self) -> list[str]:
        with self.connect() as connection:
            return [row[0] for row in connection.execute("SELECT slug FROM pins ORDER BY slug")]

    def visit_counts(self)''')
    replace(repo, "dockit/cli.py", '    commands.add_parser("visits", help="print the visit counts")\n',
            '    commands.add_parser("visits", help="print the visit counts")\n'
            '    for name in ("pin", "unpin"):\n        commands.add_parser(name, help=f"{name} a page").add_argument("slug")\n'
            '    commands.add_parser("pins", help="print the pinned pages")\n')
    replace(repo, "dockit/cli.py", '    return 0\n\n\ndef main',
            '''    elif args.command == "pin":
        store.pin(args.slug)
        print(f"Pinned {args.slug}")
    elif args.command == "unpin":
        store.unpin(args.slug)
        print(f"Unpinned {args.slug}")
    elif args.command == "pins":
        for slug in store.pins():
            print(slug)
    return 0


def main''')
    replace(repo, "README.md", "\nA page is a Markdown file",
            "- `pin SLUG` and `unpin SLUG` mark and unmark a page; `pins` prints the pinned pages, one per line.\n\nA page is a Markdown file")
    replace(repo, "docs/ko/README.ko.md", "\n페이지는 선택 사항인",
            "- `pin SLUG`와 `unpin SLUG`는 페이지에 표시를 하고 지웁니다. `pins`는 표시한 페이지를 한 줄에 하나씩 출력합니다.\n\n페이지는 선택 사항인")
    write(repo, "tests/test_pins.py", '''from dockit.store import Store


def test_pin_and_unpin(shared_db):
    store = Store.open(shared_db)
    store.pin("guide")
    store.pin("guide")
    assert store.pins() == ["guide"]
    store.unpin("guide")
    assert store.pins() == []
''')


def notes_change() -> None:
    replace(repo, "dockit/store.py", '    ("create-visits", "CREATE TABLE visits (slug TEXT PRIMARY KEY, count INTEGER NOT NULL)"),\n',
            '    ("create-visits", "CREATE TABLE visits (slug TEXT PRIMARY KEY, count INTEGER NOT NULL)"),\n'
            '    ("create-notes", "CREATE TABLE notes (id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT NOT NULL, text TEXT NOT NULL)"),\n')
    replace(repo, "dockit/store.py", "    def visit_counts(self)", '''    def add_note(self, slug: str, text: str) -> int:
        with self.connect() as connection:
            return connection.execute("INSERT INTO notes (slug, text) VALUES (?, ?)", (slug, text)).lastrowid

    def notes(self, slug: str) -> list[str]:
        with self.connect() as connection:
            return [row[0] for row in connection.execute("SELECT text FROM notes WHERE slug = ? ORDER BY id", (slug,))]

    def visit_counts(self)''')
    replace(repo, "dockit/cli.py", '    commands.add_parser("visits", help="print the visit counts")\n',
            '    commands.add_parser("visits", help="print the visit counts")\n'
            '    note = commands.add_parser("note", help="save a note on a page")\n    note.add_argument("slug")\n    note.add_argument("text")\n'
            '    commands.add_parser("notes", help="print the notes of a page").add_argument("slug")\n')
    replace(repo, "dockit/cli.py", '    return 0\n\n\ndef main',
            '''    elif args.command == "note":
        print(f"Saved note {store.add_note(args.slug, args.text)} for {args.slug}")
    elif args.command == "notes":
        for number, text in enumerate(store.notes(args.slug), start=1):
            print(f"{number}: {text}")
    return 0


def main''')
    replace(repo, "README.md", "\nA page is a Markdown file",
            "- `note SLUG TEXT` saves a note on a page and prints its number; `notes SLUG` prints the notes of a page as `N: TEXT`.\n\nA page is a Markdown file")
    replace(repo, "docs/ko/README.ko.md", "\n페이지는 선택 사항인",
            "- `note SLUG TEXT`는 페이지에 메모를 저장하고 번호를 출력합니다. `notes SLUG`는 페이지의 메모를 `N: TEXT`로 출력합니다.\n\n페이지는 선택 사항인")
    write(repo, "tests/test_notes.py", '''from dockit.store import Store


def test_notes_come_back_in_order(shared_db):
    store = Store.open(shared_db)
    store.add_note("guide", "one")
    store.add_note("guide", "two")
    assert store.notes("guide") == ["one", "two"]
''')


if "pins" not in skipped:
    pins_change()
if "notes" not in skipped:
    notes_change()
