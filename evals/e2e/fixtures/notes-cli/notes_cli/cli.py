"""Command line interface: `notes-cli memo add|list|show|remove|search`."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Sequence, TextIO

from .formatting import format_memo_detail, format_memo_line, format_page
from .settings import Settings, SettingsError, load_settings
from .storage import MemoNotFound, MemoStore

DEFAULT_STORE = "memos.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="notes-cli", description="Command-line memo manager")
    parser.add_argument("--store", help="path of the memo file (default: $NOTES_CLI_STORE or memos.json)")
    commands = parser.add_subparsers(dest="command", required=True)
    memo = commands.add_parser("memo", help="work with memos").add_subparsers(dest="action", required=True)
    add = memo.add_parser("add", help="add a memo")
    add.add_argument("title")
    add.add_argument("--body", default="")
    add.add_argument("--tag", action="append", default=[], dest="tags")
    listing = memo.add_parser("list", help="list memos page by page")
    listing.add_argument("--tag")
    listing.add_argument("--page", type=int, default=1)
    show = memo.add_parser("show", help="show one memo")
    show.add_argument("memo_id", type=int)
    remove = memo.add_parser("remove", help="remove one memo")
    remove.add_argument("memo_id", type=int)
    search = memo.add_parser("search", help="find memos containing text")
    search.add_argument("query")
    return parser


def run_action(args: argparse.Namespace, store: MemoStore, settings: Settings, out: TextIO) -> None:
    if args.action == "add":
        memo = store.add(args.title, args.body, tuple(args.tags))
        print(f"Saved memo #{memo.id}", file=out)
    elif args.action == "list":
        memos = [memo for memo in store.all() if args.tag is None or memo.has_tag(args.tag)]
        print(format_page(memos, args.page, settings.page_size), file=out)
    elif args.action == "show":
        print(format_memo_detail(store.get(args.memo_id)), file=out)
    elif args.action == "remove":
        memo = store.remove(args.memo_id)
        print(f"Removed memo #{memo.id}", file=out)
    else:
        found = store.search(args.query)
        print("\n".join(format_memo_line(memo) for memo in found) or "No memos.", file=out)


def main(
    argv: Sequence[str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    settings: Settings | None = None,
) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    args = build_parser().parse_args(argv)
    path = args.store or os.environ.get("NOTES_CLI_STORE") or DEFAULT_STORE
    try:
        run_action(args, MemoStore(path), settings or load_settings(), out)
    except (MemoNotFound, ValueError, SettingsError) as exc:
        print(f"error: {exc.args[0] if exc.args else exc}", file=err)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
