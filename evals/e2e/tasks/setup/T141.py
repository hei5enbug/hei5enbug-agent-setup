"""Seed the notes-cli repository with a session transcript whose stored question input holds escape text itself."""

from __future__ import annotations

import sys
from pathlib import Path

from session_common import GREETING, write_transcript

ESCAPED = "".join(f"\\u{ord(char):04x}" for char in GREETING)

if __name__ == "__main__":
    write_transcript(Path(sys.argv[1]), ESCAPED)
