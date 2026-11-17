"""Optional features, one module each, found automatically.

A module may define MIGRATIONS (pairs of a name and an SQL statement), register(commands) to add its subcommands, and
handle(args, store) to run them and return whether it did."""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType


def modules() -> list[ModuleType]:
    names = sorted(info.name for info in pkgutil.iter_modules(__path__))
    return [importlib.import_module(f"{__name__}.{name}") for name in names]


def migrations() -> list[tuple[str, str]]:
    return [pair for module in modules() for pair in getattr(module, "MIGRATIONS", [])]
