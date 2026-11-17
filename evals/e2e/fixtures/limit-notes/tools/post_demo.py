#!/usr/bin/env python3
"""Post a text to the demo tracker by copying it into posted/."""
import shutil
import sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(__file__).resolve().parents[1] / "posted"
target.mkdir(exist_ok=True)
shutil.copyfile(source, target / source.name)
print(f"posted {source.name}")
