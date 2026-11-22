"""Seed the stub gh for T80: a tracker with two unrelated issues and none that covers the weekly-report gap."""

from __future__ import annotations

import sys
from pathlib import Path

from gh_stub_common import CLOSED, OTHER_OPEN, install

install(Path(sys.argv[1]).resolve().parent, [CLOSED, OTHER_OPEN])
