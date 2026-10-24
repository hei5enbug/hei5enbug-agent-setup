"""Shared constants, path helpers, value parsing, and the resolved run context."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

HOSTS = ("claude", "codex")
HOST_CHOICES = ("claude", "codex", "both")
SIZE_PATTERN = re.compile(r"([0-9]+)([KMG]?)", re.IGNORECASE)
SIZE_UNITS = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3}
VERSION_PREFIX = re.compile(r"[0-9]+(?:\.[0-9]+)*")
RECORDS_CONSEQUENCE = "These sessions can no longer be resumed or reviewed."
DAY_SECONDS = 86400
HOUR_SECONDS = 3600
NS_PER_SECOND = 1_000_000_000

CONFIG_STRING_KEYS = (
    "claude_dir",
    "claude_plugin_cache",
    "claude_install_dir",
    "claude_launcher",
    "codex_dir",
)


class InputError(Exception):
    """An argument value or input file is invalid."""


def reason(check: str, detail: str) -> dict[str, str]:
    return {"check": check, "detail": detail}


def reason_of(error: OSError) -> str:
    return error.strerror or type(error).__name__


def parse_size(text: str) -> int:
    match = SIZE_PATTERN.fullmatch(text.strip())
    if match is None:
        raise InputError(f"invalid size {text!r}: use bytes or a K, M, or G suffix, such as 1M")
    return int(match.group(1)) * SIZE_UNITS[match.group(2).upper()]


def parse_version(name: str) -> tuple[int, ...] | None:
    match = VERSION_PREFIX.match(name)
    if match is None:
        return None
    return tuple(int(part) for part in match.group(0).split("."))


def within(path: str, parent: str) -> bool:
    return path == parent or path.startswith(parent.rstrip(os.sep) + os.sep)


def inside(path: str, parent: str) -> bool:
    return path != parent and within(path, parent)


def real(path: str) -> str:
    return os.path.realpath(path)


def absolute(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def iso_from_ns(nanoseconds: int) -> str:
    moment = datetime.fromtimestamp(nanoseconds / NS_PER_SECOND, tz=timezone.utc)
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def iso_from_datetime(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class Context:
    host: str
    age_days: int
    recent_hours: float
    min_size: int
    claude_dir: str
    claude_plugin_cache: str
    claude_install_dir: str
    claude_launcher: str
    codex_dir: str
    temp_roots: tuple[str, ...]
    protect: tuple[str, ...]

    def uses(self, host: str) -> bool:
        return self.host in (host, "both")

    def roots(self) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        if self.uses("claude"):
            found += [
                ("claude", self.claude_dir),
                ("claude-plugin-cache", self.claude_plugin_cache),
                ("claude-install", self.claude_install_dir),
            ]
            found += [("claude-temp", path) for path in self.temp_roots]
        if self.uses("codex"):
            found.append(("codex", self.codex_dir))
        return found

    def root_records(self) -> list[dict[str, Any]]:
        return [
            {"name": name, "path": path, "exists": os.path.isdir(path)}
            for name, path in self.roots()
        ]

    def real_roots(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(real(path) for _, path in self.roots() if os.path.isdir(path)))

    def display(self, path: str) -> str:
        for name, root in sorted(self.roots(), key=lambda pair: -len(pair[1])):
            if path == root:
                return f"<{name}>"
            if path.startswith(root.rstrip(os.sep) + os.sep):
                return f"<{name}>" + path[len(root.rstrip(os.sep)) :]
        return path

    def display_group(self, paths: Sequence[str]) -> str:
        shown = self.display(paths[0])
        return shown if len(paths) == 1 else f"{shown} (+{len(paths) - 1} more)"

    def to_config(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "age_days": self.age_days,
            "recent_hours": self.recent_hours,
            "min_size": self.min_size,
            "claude_dir": self.claude_dir,
            "claude_plugin_cache": self.claude_plugin_cache,
            "claude_install_dir": self.claude_install_dir,
            "claude_launcher": self.claude_launcher,
            "codex_dir": self.codex_dir,
            "temp_roots": list(self.temp_roots),
            "protect": list(self.protect),
        }

    @classmethod
    def from_config(cls, config: Any) -> "Context":
        if not isinstance(config, dict):
            raise InputError("the plan has no config object")
        for key in CONFIG_STRING_KEYS:
            if not isinstance(config.get(key), str) or not os.path.isabs(config[key]):
                raise InputError(f"the plan config needs an absolute path for {key}")
        for key in ("temp_roots", "protect"):
            if not string_list(config.get(key)):
                raise InputError(f"the plan config needs a list of paths for {key}")
        numbers_valid = (
            isinstance(config.get("age_days"), int)
            and not isinstance(config.get("age_days"), bool)
            and finite_number(config.get("recent_hours"))
            and isinstance(config.get("min_size"), int)
        )
        if config.get("host") not in HOST_CHOICES or not numbers_valid:
            raise InputError("the plan config has an invalid host, age_days, recent_hours, or min_size")
        return cls(
            host=config["host"],
            age_days=config["age_days"],
            recent_hours=float(config["recent_hours"]),
            min_size=config["min_size"],
            claude_dir=config["claude_dir"],
            claude_plugin_cache=config["claude_plugin_cache"],
            claude_install_dir=config["claude_install_dir"],
            claude_launcher=config["claude_launcher"],
            codex_dir=config["codex_dir"],
            temp_roots=tuple(config["temp_roots"]),
            protect=tuple(config["protect"]),
        )


def string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and os.path.isabs(item) for item in value)


def temp_bases(environ: Mapping[str, str]) -> list[str]:
    bases = [environ.get("CLAUDE_CODE_TMPDIR", ""), "/tmp", environ.get("TMPDIR", "")]
    return [base for base in bases if base]


def default_temp_roots(bases: Iterable[str], uid: int) -> tuple[str, ...]:
    found: dict[str, str] = {}
    for base in bases:
        candidate = os.path.join(absolute(base), f"claude-{uid}")
        if os.path.isdir(candidate):
            found.setdefault(real(candidate), candidate)
    return tuple(found.values())


def resolve_context(args: Any, environ: Mapping[str, str]) -> Context:
    home = absolute("~")
    claude_dir = absolute(args.claude_dir or environ.get("CLAUDE_CONFIG_DIR") or os.path.join(home, ".claude"))
    default_cache = environ.get("CLAUDE_CODE_PLUGIN_CACHE_DIR") or os.path.join(claude_dir, "plugins", "cache")
    temp_roots = args.temp_root or list(default_temp_roots(temp_bases(environ), os.getuid()))
    return Context(
        host=args.host,
        age_days=args.age_days,
        recent_hours=args.recent_hours,
        min_size=args.min_size,
        claude_dir=claude_dir,
        claude_plugin_cache=absolute(args.claude_plugin_cache or default_cache),
        claude_install_dir=absolute(args.claude_install_dir or os.path.join(home, ".local", "share", "claude")),
        claude_launcher=absolute(args.claude_launcher or os.path.join(home, ".local", "bin", "claude")),
        codex_dir=absolute(args.codex_dir or environ.get("CODEX_HOME") or os.path.join(home, ".codex")),
        temp_roots=tuple(dict.fromkeys(absolute(path) for path in temp_roots)),
        protect=tuple(dict.fromkeys(absolute(path) for path in args.protect)),
    )
