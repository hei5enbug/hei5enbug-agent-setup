"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys
from typing import Any, TextIO

from . import store, summary
from .dates import DateError, parse_date
from .exporter import export_entries
from .settings import load_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="timesheet")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add")
    add.add_argument("date")
    add.add_argument("project")
    add.add_argument("minutes", type=int)
    listing = sub.add_parser("list")
    listing.add_argument("--on")
    sub.add_parser("totals")
    sub.add_parser("report")
    export = sub.add_parser("export")
    export.add_argument("--from", dest="start")
    export.add_argument("--to", dest="end")
    return parser


def entry_line(entry: dict[str, Any]) -> str:
    return f"{entry['id']} {entry['date']} {entry['project']} {entry['minutes']}"


def list_lines(entries: list[dict[str, Any]], on: str | None = None) -> list[str]:
    wanted = parse_date(on).isoformat() if on else None
    chosen = [entry for entry in entries if wanted is None or entry["date"] == wanted]
    return [entry_line(entry) for entry in sorted(chosen, key=lambda entry: entry["date"])]


def total_lines() -> list[str]:
    return [f"{project} {minutes}" for project, minutes in summary.project_totals(store.load()).items()]


def run(args: argparse.Namespace, out: TextIO) -> int:
    if args.command == "add":
        entry = store.add(parse_date(args.date), args.project, args.minutes)
        out.write(entry_line(entry) + "\n")
    elif args.command == "list":
        out.writelines(line + "\n" for line in list_lines(store.load_cached(), args.on))
    elif args.command == "totals":
        out.writelines(line + "\n" for line in total_lines())
    elif args.command == "report":
        out.writelines(line + "\n" for line in [*list_lines(store.load_cached()), "--", *total_lines()])
    else:
        entries = store.load()
        start = parse_date(args.start).isoformat() if args.start else None
        end = parse_date(args.end).isoformat() if args.end else None
        chosen = [e for e in entries if (start is None or e["date"] >= start) and (end is None or e["date"] <= end)]
        out.write(f"{export_entries(chosen, load_settings().export_dir)}\n")
    return 0


def main(argv: list[str] | None = None, stdout: TextIO | None = None) -> int:
    args = build_parser().parse_args(argv)
    out = stdout or sys.stdout
    try:
        return run(args, out)
    except (DateError, store.StoreError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
