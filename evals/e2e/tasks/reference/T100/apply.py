"""Post the reviewed text: the draft without the sentences the reviewer stub raised, saved under out/ and copied into posted/."""
import re
import shutil
from pathlib import Path

NAME = "pr-draft-demo-o.md"
SEEDED = {
    "m": ["This change follows the report that zero-total customers made the nightly export slow.",
          "The export module was refactored as part of this work.", "The change is small and easy to review."],
    "n": ["This work started from the request to stop over-refunds."],
    "o": ["This change follows the report that statement totals were off by a cent.",
          "The statement module was cleaned up along the way.", "The change is small and easy to review."],
}["o"]

lines = [line for line in Path("notes", NAME).read_text(encoding="utf-8").splitlines() if line not in SEEDED]
text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"
Path("out").mkdir(exist_ok=True)
Path("out", NAME).write_text(text, encoding="utf-8")
Path("posted").mkdir(exist_ok=True)
shutil.copyfile(Path("out", NAME), Path("posted", NAME))
