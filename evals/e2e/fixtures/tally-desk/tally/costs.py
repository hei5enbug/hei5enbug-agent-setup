"""What a team's hours cost."""

from __future__ import annotations

from .errors import UnknownTeam
from .rates import load_rates
from .report import team_hours
from .store import load_entries


def team_cost(team: str) -> int:
    """Total hours of the team times its hourly rate, in whole currency units."""
    rates = load_rates()
    if team not in rates:
        raise UnknownTeam(team)
    return round(team_hours(load_entries()).get(team, 0.0) * rates[team])
