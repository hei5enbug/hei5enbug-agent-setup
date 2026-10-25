"""Settings loaded from config/settings.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parent.parent / "config" / "settings.toml"


class SettingsError(Exception):
    """The settings file is missing or holds an unusable value."""


@dataclass(frozen=True)
class Settings:
    page_size: int


def load_settings(path: str | Path = DEFAULT_SETTINGS_PATH) -> Settings:
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SettingsError(f"cannot read settings from {path}: {exc}") from exc
    page_size = data.get("page_size")
    if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1:
        raise SettingsError("page_size must be a positive integer")
    return Settings(page_size=page_size)
