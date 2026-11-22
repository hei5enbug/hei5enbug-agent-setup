"""Seed the notes-cli repository with a session transcript whose stored question input holds the kana as raw characters."""

from __future__ import annotations

import sys
from pathlib import Path

from session_common import GREETING, write_transcript

if __name__ == "__main__":
    write_transcript(Path(sys.argv[1]), GREETING)
