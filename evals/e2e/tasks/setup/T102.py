"""Put a fake `gh` and a fake `codex` that reports a used-up usage limit on a bin folder beside the repository."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_codex_common import install  # noqa: E402

MESSAGE = "You have reached your usage limit. Try again later."

if __name__ == "__main__":
    install(Path(sys.argv[1]).resolve(), MESSAGE)
