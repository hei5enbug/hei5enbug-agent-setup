"""Line coverage of one module without third-party packages.

Usage: python3 tools/linecov.py MODULE [--min PERCENT] [-- PYTEST ARGS]

Runs pytest (default: `-q tests`) with a line tracer on MODULE, which is a path relative to the repository root,
and prints the percentage of executable lines that ran together with the line numbers that never did.
"""

from __future__ import annotations

import ast
import os
import sys
import threading
import types
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PYTEST_ARGS = ["-q", "-p", "no:cacheprovider", "tests"]


def statement_lines(tree: ast.AST) -> set[int]:
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt):
            lines.add(node.lineno)
            lines.update(decorator.lineno for decorator in getattr(node, "decorator_list", ()))
    return lines


def executable_lines(source: str, filename: str) -> set[int]:
    reported: set[int] = set()
    stack = [compile(source, filename, "exec")]
    while stack:
        code = stack.pop()
        if code.co_name == "__annotate__":
            continue
        reported.update(line for _start, _end, line in code.co_lines() if line is not None and line > 0)
        stack.extend(const for const in code.co_consts if isinstance(const, types.CodeType))
    return reported & statement_lines(ast.parse(source, filename))


def collapse_ranges(numbers: Sequence[int]) -> str:
    ranges: list[str] = []
    ordered = sorted(numbers)
    index = 0
    while index < len(ordered):
        end = index
        while end + 1 < len(ordered) and ordered[end + 1] == ordered[end] + 1:
            end += 1
        ranges.append(str(ordered[index]) if end == index else f"{ordered[index]}-{ordered[end]}")
        index = end + 1
    return ", ".join(ranges)


def run_traced(module: str, pytest_args: Sequence[str]) -> tuple[set[int], set[int], int]:
    import pytest

    target = os.path.realpath(ROOT / module)
    source = Path(target).read_text(encoding="utf-8")
    executed: set[int] = set()
    matches: dict[str, bool] = {}

    def is_target(filename: str) -> bool:
        if filename not in matches:
            matches[filename] = os.path.realpath(filename) == target
        return matches[filename]

    def local_trace(frame: types.FrameType, event: str, arg: Any) -> Any:
        if event == "line":
            executed.add(frame.f_lineno)
        return local_trace

    def global_trace(frame: types.FrameType, event: str, arg: Any) -> Any:
        return local_trace if is_target(frame.f_code.co_filename) else None

    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    threading.settrace(global_trace)
    sys.settrace(global_trace)
    try:
        returncode = int(pytest.main(list(pytest_args)))
    finally:
        sys.settrace(None)
        threading.settrace(None)  # type: ignore[arg-type]
    return executable_lines(source, target), executed, returncode


def parse_arguments(argv: Sequence[str]) -> tuple[str, float | None, list[str]]:
    arguments = list(argv)
    pytest_args = DEFAULT_PYTEST_ARGS
    if "--" in arguments:
        split = arguments.index("--")
        arguments, pytest_args = arguments[:split], arguments[split + 1:] or DEFAULT_PYTEST_ARGS
    minimum: float | None = None
    if "--min" in arguments:
        position = arguments.index("--min")
        minimum = float(arguments[position + 1])
        del arguments[position:position + 2]
    if len(arguments) != 1:
        raise SystemExit(__doc__)
    return arguments[0], minimum, list(pytest_args)


def main(argv: Sequence[str] | None = None) -> int:
    module, minimum, pytest_args = parse_arguments(sys.argv[1:] if argv is None else argv)
    executable, executed, returncode = run_traced(module, pytest_args)
    covered = executable & executed
    percent = 100.0 if not executable else 100.0 * len(covered) / len(executable)
    print(f"{module}: {percent:.1f}% ({len(covered)}/{len(executable)} lines)")
    missing = sorted(executable - executed)
    if missing:
        print(f"never executed: {collapse_ranges(missing)}")
    if returncode != 0:
        print(f"pytest exited with {returncode}")
        return 1
    if minimum is not None and percent < minimum:
        print(f"below the required {minimum:g}%")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
