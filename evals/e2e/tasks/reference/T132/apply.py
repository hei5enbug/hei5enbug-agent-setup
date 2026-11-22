import sys
from pathlib import Path

from patch_tools import write
from review_loop_ref import run_review

run_review(sys.argv[1], "spread")
for name in ("docs/setup.md", "docs/guide.md", "docs/faq.md"):
    text = (Path(sys.argv[1]) / name).read_text(encoding="utf-8")
    write(sys.argv[1], name, text.replace("is 5.", "is 3.").replace("at most 5 times", "at most 3 times"))
run_review(sys.argv[1], "spread")
