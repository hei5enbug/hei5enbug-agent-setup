"""Settings read from the environment. Local values live in `.env`, which is loaded by `load_dotenv`."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8080
    debug: bool = False
    session_key: str = ""


def load_dotenv(path: str | Path = ".env") -> dict[str, str]:
    """Read KEY=VALUE lines from a file. A missing file gives an empty mapping."""
    values: dict[str, str] = {}
    file = Path(path)
    if not file.is_file():
        return values
    for raw in file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def load_settings(environ: dict[str, str] | None = None) -> Settings:
    env = dict(os.environ if environ is None else environ)
    return Settings(
        host=env.get("DEMO_HOST", "127.0.0.1"),
        port=int(env.get("DEMO_PORT", "8080")),
        debug=env.get("DEMO_DEBUG", "") == "1",
        session_key=env.get("DEMO_SESSION_KEY", ""),
    )
