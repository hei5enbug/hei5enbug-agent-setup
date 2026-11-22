"""Exception hierarchy. Every error raised on purpose derives from ParcelError."""

from __future__ import annotations


class ParcelError(Exception):
    """Base class for errors that are reported to the user without a traceback."""


class ValidationError(ParcelError, ValueError):
    """An argument failed validation."""


class UnknownZone(ParcelError):
    def __init__(self, zone: str) -> None:
        super().__init__(f"unknown zone: {zone}")
        self.zone = zone
