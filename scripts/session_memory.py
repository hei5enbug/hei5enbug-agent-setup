"""Available memory of this machine, for the gate on starting another agent session."""

from __future__ import annotations

import os
import re
import subprocess
import sys

TEST_OVERRIDE = "HEI5ENBUG_AVAILABLE_MEMORY_MB_FOR_TESTS"
TIMEOUT_SECONDS = 0.8
MEBIBYTE = 1024 * 1024
MEMINFO_AVAILABLE = re.compile(r"^MemAvailable:\s+(\d+)\s+kB\b", re.MULTILINE)


def parse_meminfo(text: str) -> int | None:
    """Return MemAvailable of a /proc/meminfo text in MB, or None when it has none."""
    match = MEMINFO_AVAILABLE.search(text)
    return int(match[1]) // 1024 if match else None


def parse_darwin(output: str) -> int | None:
    """Return available MB from `sysctl -n kern.memorystatus_level hw.memsize` output: free percentage of total."""
    lines = output.split()
    if len(lines) != 2 or not all(line.isdigit() for line in lines):
        return None
    percent, total = int(lines[0]), int(lines[1])
    return total * percent // 100 // MEBIBYTE if percent <= 100 else None


def available_mb() -> int | None:
    """Return available memory in MB, or None when it cannot be read within the time limit on this platform."""
    override = os.environ.get(TEST_OVERRIDE)
    if override is not None:
        return int(override) if override.isdigit() else None
    try:
        if sys.platform == "darwin":
            result = subprocess.run(
                ["sysctl", "-n", "kern.memorystatus_level", "hw.memsize"],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                check=False,
            )
            return parse_darwin(result.stdout) if result.returncode == 0 else None
        if sys.platform.startswith("linux"):
            with open("/proc/meminfo", encoding="utf-8") as handle:
                return parse_meminfo(handle.read())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return None
