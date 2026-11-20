"""Put a fake `gh` and a fake `codex` that reports an authentication failure on a bin folder beside the repository."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_codex_common import install  # noqa: E402

MESSAGE = "Authentication failed: your login has expired. Run `codex login` and try again."

if __name__ == "__main__":
    install(Path(sys.argv[1]).resolve(), MESSAGE)
