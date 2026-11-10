#!/usr/bin/env python3
"""Print {"status", "findings"} for the harsh words found in the file given as the only argument."""

import json
import sys
from pathlib import Path

HARSH = ("obviously", "as I said", "you must")
text = Path(sys.argv[1]).read_text(encoding="utf-8").lower()
findings = [word for word in HARSH if word in text]
print(json.dumps({"status": "matches" if findings else "clean", "findings": findings}))
