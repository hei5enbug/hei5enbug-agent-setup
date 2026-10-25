"""Stdlib line coverage for one module, measured with sys.settrace while pytest runs in a child process.

Executable lines come from the code objects of the module (`co_lines`), executed lines from `line` trace events.
The fixture tool `tools/linecov.py` uses the same algorithm so a run can measure what the grader measures.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import types
from pathlib import Path
from typing import Any, Mapping, Sequence

DEFAULT_PYTEST_ARGS = ("-q", "-p", "no:cacheprovider", "tests")
DEFAULT_TIMEOUT_SECONDS = 600


def executable_lines(source: str, filename: str) -> set[int]:
    lines: set[int] = set()
    stack = [compile(source, filename, "exec")]
    while stack:
        code = stack.pop()
        if code.co_name == "__annotate__":
            continue
        lines.update(line for _start, _end, line in code.co_lines() if line is not None and line > 0)
        stack.extend(const for const in code.co_consts if isinstance(const, types.CodeType))
    return lines


def percent_covered(executable: set[int], executed: set[int]) -> float:
    if not executable:
        return 100.0
    return round(100.0 * len(executable & executed) / len(executable), 2)


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


def run_traced(repo: Path, module: str, pytest_args: Sequence[str]) -> dict[str, Any]:
    """Run pytest in this process with a line tracer on `module` and return the coverage figures."""
    import pytest

    target = os.path.realpath(repo / module)
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

    os.chdir(repo)
    sys.path.insert(0, str(repo))
    threading.settrace(global_trace)
    sys.settrace(global_trace)
    try:
        returncode = int(pytest.main(list(pytest_args)))
    finally:
        sys.settrace(None)
        threading.settrace(None)  # type: ignore[arg-type]
    executable = executable_lines(source, target)
    missing = sorted(executable - executed)
    return {
        "module": module,
        "executable": len(executable),
        "executed": len(executable & executed),
        "percent": percent_covered(executable, executed),
        "missing": missing,
        "pytest_returncode": returncode,
    }


def measure(
    repo: Path,
    module: str,
    pytest_args: Sequence[str] = DEFAULT_PYTEST_ARGS,
    env: Mapping[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Measure `module` (a path relative to `repo`) while running pytest there. Never raises for a failed run."""
    if not (repo / module).is_file():
        return {"module": module, "error": f"{module} does not exist", "percent": 0.0}
    environment = dict(os.environ if env is None else env)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment.pop("PYTHONPATH", None)
    with tempfile.TemporaryDirectory() as scratch:
        output = Path(scratch) / "coverage.json"
        command = [sys.executable, str(Path(__file__).resolve()), "--repo", str(repo), "--module", module,
                   "--json", str(output), "--", *pytest_args]
        try:
            completed = subprocess.run(command, cwd=repo, env=environment, capture_output=True, text=True,
                                       timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"module": module, "error": f"timed out after {timeout}s", "percent": 0.0}
        if not output.is_file():
            return {"module": module, "error": (completed.stderr or completed.stdout)[-2000:], "percent": 0.0}
        result = json.loads(output.read_text(encoding="utf-8"))
    result["output_tail"] = completed.stdout[-2000:]
    return result


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if "--" in arguments:
        split = arguments.index("--")
        options, pytest_args = arguments[:split], arguments[split + 1:]
    else:
        options, pytest_args = arguments, list(DEFAULT_PYTEST_ARGS)
    values = dict(zip(options[::2], options[1::2]))
    result = run_traced(Path(values["--repo"]), values["--module"], pytest_args or DEFAULT_PYTEST_ARGS)
    Path(values["--json"]).write_text(json.dumps(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
