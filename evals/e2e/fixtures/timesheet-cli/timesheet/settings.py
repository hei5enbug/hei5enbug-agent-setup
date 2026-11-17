"""Settings loaded from config/settings.toml; the data and export folders live below the home folder."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS_PATH = ROOT / "config" / "settings.toml"
HOME_ENV = "TIMESHEET_HOME"


class SettingsError(Exception):
    """The settings file is missing or holds an unusable value."""


@dataclass(frozen=True)
class Settings:
    data_file: Path
    export_dir: Path


def load_settings(path: str | Path = DEFAULT_SETTINGS_PATH) -> Settings:
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SettingsError(f"cannot read settings from {path}: {exc}") from exc
    home = Path(os.environ.get(HOME_ENV) or ROOT)
    for key in ("data_file", "export_dir"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise SettingsError(f"{key} must be a non-empty string")
    return Settings(data_file=home / data["data_file"], export_dir=home / data["export_dir"])
