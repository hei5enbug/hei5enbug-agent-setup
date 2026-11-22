"""Install the fake `aside` on the PATH of the T160 run: `fake-bin/aside` beside the repository, with its call log."""

from __future__ import annotations

import shutil
import stat
import sys
from pathlib import Path

STUB = Path(__file__).resolve().parent / "fake_aside.py"
work = Path(sys.argv[1]).resolve().parent
binary = work / "fake-bin"
binary.mkdir()
program = binary / "aside"
shutil.copy(STUB, program)
program.chmod(program.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
