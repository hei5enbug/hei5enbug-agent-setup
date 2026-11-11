"""The one-line notice, at a user prompt, that the machine is short of CPU, memory, or storage.

Every counter comes from the operating system without starting a process. A reading that cannot be taken counts as
no shortage.
"""

from __future__ import annotations

import os
import sys
from collections import namedtuple

LOAD_FACTOR = 2
MEMORY_FRACTION = 0.10
STORAGE_FRACTION = 0.10
DARWIN_LEVEL = b"kern.memorystatus_level"
TEST_OVERRIDE = "HEI5ENBUG_MACHINE_COUNTERS_FOR_TESTS"

Counters = namedtuple("Counters", "load_average cpu_count memory_available_fraction storage_free_fraction")


def read_load_average() -> float | None:
    try:
        return os.getloadavg()[0]
    except (OSError, AttributeError):
        return None


def read_cpu_count() -> int | None:
    return os.cpu_count()


def meminfo_fraction(text: str) -> float | None:
    """The available share of physical memory from a /proc/meminfo text."""
    values = {}
    for line in text.splitlines():
        name, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            values[name] = int(parts[0])
    total, available = values.get("MemTotal"), values.get("MemAvailable")
    return available / total if total and available is not None else None


def read_memory_fraction() -> float | None:
    """The share of physical memory that is available, or None when this platform does not say."""
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/meminfo", encoding="utf-8") as handle:
                return meminfo_fraction(handle.read())
        if sys.platform == "darwin":
            import ctypes

            level = ctypes.c_int(0)
            size = ctypes.c_size_t(ctypes.sizeof(level))
            libc = ctypes.CDLL(None)
            if libc.sysctlbyname(DARWIN_LEVEL, ctypes.byref(level), ctypes.byref(size), None, 0) == 0:
                return level.value / 100 if 0 <= level.value <= 100 else None
    except (OSError, ValueError, AttributeError):
        return None
    return None


def read_storage_fraction(path: str) -> float | None:
    """The free share of the volume that holds `path`."""
    try:
        stats = os.statvfs(path)
    except OSError:
        return None
    return stats.f_bavail / stats.f_blocks if stats.f_blocks else None


def override_counters() -> Counters | None:
    """Counters from `load,cpus,memory_fraction,storage_fraction` in the test variable; None when it is unset or malformed."""
    text = os.environ.get(TEST_OVERRIDE)
    if text is None:
        return None
    try:
        load, cpus, memory, storage = text.split(",")
        return Counters(float(load), int(cpus), float(memory), float(storage))
    except ValueError:
        return None


def system_counters(cwd: str) -> Counters:
    override = override_counters()
    if override is not None:
        return override
    return Counters(read_load_average(), read_cpu_count(), read_memory_fraction(), read_storage_fraction(cwd))


def shortages(counters: Counters) -> list[tuple[str, str]]:
    """Each short resource as (kind, text with its current value and its threshold)."""
    found = []
    load, cpus = counters.load_average, counters.cpu_count
    if load is not None and cpus and load >= LOAD_FACTOR * cpus:
        found.append((
            "cpu",
            f"CPU load average {load:.1f} on {cpus} logical CPUs (notice at {LOAD_FACTOR * cpus:.1f})",
        ))
    memory = counters.memory_available_fraction
    if memory is not None and memory < MEMORY_FRACTION:
        found.append(("memory", f"{memory:.0%} of memory available (notice below {MEMORY_FRACTION:.0%})"))
    storage = counters.storage_free_fraction
    if storage is not None and storage < STORAGE_FRACTION:
        found.append((
            "storage", f"{storage:.0%} of storage free on the working directory's volume (notice below {STORAGE_FRACTION:.0%})",
        ))
    return found


def notice_line(found: list[tuple[str, str]]) -> str | None:
    """The prompt-context line for the short resources, or None when none is short."""
    if not found:
        return None
    kinds = {kind for kind, _ in found}
    advice = ["Before heavy work, such as a build, a full test suite, or several parallel agents, tell the user."]
    if kinds & {"cpu", "memory"}:
        advice.append(
            "Name the running processes or Orca sessions using most of the "
            + " and ".join(name for name in ("CPU", "memory") if name.lower() in kinds)
            + ", or say that none stands out, and recommend checking those sessions and waiting until the load drops."
        )
    if "storage" in kinds:
        advice.append("For storage, recommend freeing space, because waiting does not help.")
    advice.append("Do not block or delay light work.")
    return "Machine load: " + "; ".join(text for _, text in found) + ". " + " ".join(advice)
