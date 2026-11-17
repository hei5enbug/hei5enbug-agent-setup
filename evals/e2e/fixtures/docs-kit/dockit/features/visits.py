"""Visit counts per page."""

from __future__ import annotations

MIGRATIONS = [
    ("create-visits", "CREATE TABLE visits (slug TEXT PRIMARY KEY, count INTEGER NOT NULL)"),
]


def record_visit(store, slug: str) -> int:
    """Add one visit to a page and return its new count."""
    with store.connect() as connection:
        connection.execute(
            "INSERT INTO visits (slug, count) VALUES (?, 1) ON CONFLICT(slug) DO UPDATE SET count = count + 1", (slug,))
        return connection.execute("SELECT count FROM visits WHERE slug = ?", (slug,)).fetchone()[0]


def visit_counts(store) -> dict[str, int]:
    with store.connect() as connection:
        return dict(connection.execute("SELECT slug, count FROM visits ORDER BY slug"))


def register(commands) -> None:
    commands.add_parser("visit", help="add one visit to a page").add_argument("slug")
    commands.add_parser("visits", help="print the visit counts")


def handle(args, store) -> bool:
    if args.command == "visit":
        print(f"{args.slug} {record_visit(store, args.slug)}")
    elif args.command == "visits":
        for slug, count in visit_counts(store).items():
            print(f"{slug} {count}")
    else:
        return False
    return True
