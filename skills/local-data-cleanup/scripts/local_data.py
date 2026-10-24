#!/usr/bin/env python3
"""Survey, merge, and delete the local data that Claude Code and Codex leave on this machine."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Any, NoReturn, Sequence

from data_common import HOST_CHOICES, HOSTS, InputError, parse_size, resolve_context
from data_inputs import load_json, validate_peer, validate_plan, validate_survey
from data_merge import merge, unavailable_peer
from data_removal import parse_selection, run_delete
from data_survey import run_survey

DEFAULT_AGE_DAYS = 30
DEFAULT_RECENT_HOURS = 24.0
DEFAULT_MIN_SIZE = "1M"
PATH_OPTIONS = ("claude-dir", "claude-plugin-cache", "claude-install-dir", "claude-launcher", "codex-dir")


class JsonParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise InputError(message)


def non_negative_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid whole number {text!r}") from None
    if value < 0:
        raise argparse.ArgumentTypeError(f"{text} must not be negative")
    return value


def non_negative_float(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid number {text!r}") from None
    if value < 0 or not math.isfinite(value):
        raise argparse.ArgumentTypeError(f"{text} must be a finite number that is not negative")
    return value


def size_argument(text: str) -> int:
    try:
        return parse_size(text)
    except InputError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def add_survey_parser(commands: Any) -> None:
    survey = commands.add_parser("survey", help="find reclaimable items and check them")
    survey.add_argument("--host", required=True, choices=HOST_CHOICES)
    survey.add_argument("--age-days", type=non_negative_int, default=DEFAULT_AGE_DAYS)
    survey.add_argument("--recent-hours", type=non_negative_float, default=DEFAULT_RECENT_HOURS)
    survey.add_argument("--min-size", type=size_argument, default=parse_size(DEFAULT_MIN_SIZE))
    for option in PATH_OPTIONS:
        survey.add_argument(f"--{option}")
    survey.add_argument("--temp-root", action="append", default=[])
    survey.add_argument("--protect", action="append", default=[])
    survey.add_argument("--out", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=JsonParser)
    add_survey_parser(commands)
    merging = commands.add_parser("merge", help="combine a survey with the other host's verdicts")
    merging.add_argument("--survey", required=True)
    source = merging.add_mutually_exclusive_group(required=True)
    source.add_argument("--peer")
    source.add_argument("--peer-unavailable", metavar="REASON")
    merging.add_argument("--self-host", required=True, choices=HOSTS)
    merging.add_argument("--out", required=True)
    deleting = commands.add_parser("delete", help="delete the selected offered items")
    deleting.add_argument("--plan", required=True)
    deleting.add_argument("--select", action="append", default=[])
    return parser


def write_json(path: str, data: dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
    except OSError as error:
        raise InputError(f"cannot write {path}: {error.strerror or error}") from None


def emit(data: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")


def command_survey(args: argparse.Namespace) -> int:
    result = run_survey(resolve_context(args, os.environ))
    write_json(args.out, result)
    emit(result)
    return 0


def command_merge(args: argparse.Namespace) -> int:
    survey = validate_survey(load_json(args.survey, "survey"))
    if args.peer_unavailable is not None:
        peer = unavailable_peer(args.peer_unavailable)
    else:
        peer = validate_peer(load_json(args.peer, "peer"), args.self_host)
    result = merge(survey, peer, args.self_host)
    write_json(args.out, result)
    emit(result)
    return 0


def command_delete(args: argparse.Namespace) -> int:
    plan = validate_plan(load_json(args.plan, "plan"))
    result, code = run_delete(plan, parse_selection(args.select))
    emit(result)
    return code


COMMANDS = {"survey": command_survey, "merge": command_merge, "delete": command_delete}


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return COMMANDS[args.command](args)
    except InputError as error:
        emit({"error": str(error)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
