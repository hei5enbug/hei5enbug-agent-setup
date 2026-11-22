"""The only source of the current time."""

from __future__ import annotations

import os
from datetime import datetime


def now() -> datetime:
    """The current time, or the minute named by TALLY_NOW (`YYYY-MM-DDTHH:MM`)."""
    fixed = os.environ.get("TALLY_NOW")
    return datetime.strptime(fixed, "%Y-%m-%dT%H:%M") if fixed else datetime.now().replace(second=0, microsecond=0)
