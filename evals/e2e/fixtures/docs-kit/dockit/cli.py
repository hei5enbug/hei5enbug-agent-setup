"""Command line of docs-kit."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .build import DEFAULT_OUT, build
from .lockfile import Busy, held
from .store import Store, default_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dockit")
    parser.add_argument("--db", type=Path, default=None, help="database file (default: DOCKIT_DB or data/dockit.db)")
    commands = parser.add_subparsers(dest="command", required=True)
    build_command = commands.add_parser("build", help="build the site")
    build_command.add_argument("--out", type=Path, default=DEFAULT_OUT)
    visit = commands.add_parser("visit", help="add one visit to a page")
    visit.add_argument("slug")
    commands.add_parser("visits", help="print the visit counts")
    return parser


def run(args: argparse.Namespace, store: Store) -> int:
    if args.command == "visit":
        print(f"{args.slug} {store.record_visit(args.slug)}")
    elif args.command == "visits":
        for slug, count in store.visit_counts().items():
            print(f"{slug} {count}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            written = build(out_dir=args.out)
            print(f"Built {len(written)} files into {args.out}")
            return 0
        path = args.db or default_path()
        with held(path.with_name(path.name + ".lock"), f"the database {path.name}"):
            return run(args, Store.open(path))
    except Busy as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
