"""Command line interface: `tally totals | rate TEAM | cost TEAM`."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence, TextIO

from .costs import team_cost
from .errors import TallyError
from .rates import rate_for
from .report import format_row, team_hours
from .store import load_entries

EXIT_USER_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tally", description="Hours per team")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("totals", help="hours per team, all dates together")
    rate = commands.add_parser("rate", help="the hourly rate of a team")
    rate.add_argument("team")
    cost = commands.add_parser("cost", help="the cost of a team's hours")
    cost.add_argument("team")
    return parser


def main(argv: Sequence[str] | None = None, stdout: TextIO | None = None, stderr: TextIO | None = None) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    args = build_parser().parse_args(argv)
    try:
        if args.command == "totals":
            for team, hours in team_hours(load_entries()).items():
                print(format_row(team, hours), file=out)
        elif args.command == "rate":
            print(rate_for(args.team), file=out)
        else:
            print(team_cost(args.team), file=out)
    except TallyError as exc:
        print(f"error: {exc}", file=err)
        return EXIT_USER_ERROR
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
