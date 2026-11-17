import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repeated_review_reference import run_review

repo = Path(sys.argv[1])
run_review(repo)
for relative in ("docs/setup.md", "docs/guide.md", "docs/faq.md"):
    path = repo / relative
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    path.write_text("".join(re.sub(r"\b5\b", "3", line) if re.search("retr", line, re.I) else line for line in lines),
                    encoding="utf-8")
run_review(repo)
