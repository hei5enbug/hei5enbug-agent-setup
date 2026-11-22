"""Hourly rates per team."""

from __future__ import annotations

import json
from pathlib import Path

from .cache import ttl_cached
from .errors import UnknownTeam

RATES_FILE = Path("data/rates.json")
RATE_TTL_SECONDS = 3600


def load_rates() -> dict[str, int]:
    with RATES_FILE.open(encoding="utf-8") as stream:
        return dict(json.load(stream))


@ttl_cached(RATE_TTL_SECONDS)
def rate_for(team: str) -> int:
    """The hourly rate of a team, kept for one hour."""
    rates = load_rates()
    if team not in rates:
        raise UnknownTeam(team)
    return rates[team]
