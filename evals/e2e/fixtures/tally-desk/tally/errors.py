"""Errors a user can cause."""

from __future__ import annotations


class TallyError(Exception):
    """Base class of every failure the CLI turns into exit code 2."""


class UnknownTeam(TallyError):
    def __init__(self, team: str):
        super().__init__(f"unknown team: {team}")
