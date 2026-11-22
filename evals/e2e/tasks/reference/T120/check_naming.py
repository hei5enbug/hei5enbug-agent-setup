"""Check candidate for the memo-for-note class: fails when an identifier of the package or its tests starts with memo."""

import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
found = [f"{path.relative_to(root)}: {match.group(0)}" for folder in ("tally", "tests")
         for path in sorted((root / folder).rglob("*.py"))
         for match in re.finditer(r"\bmemo\w*", path.read_text(encoding="utf-8"), re.IGNORECASE)]
if found:
    print("use note, not memo, in names:\n" + "\n".join(found))
    sys.exit(1)
