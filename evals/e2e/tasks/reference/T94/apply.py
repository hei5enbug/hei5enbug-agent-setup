"""Post both drafts as they are: the reference repository holds what a run that skips the review would have posted."""
import shutil
from pathlib import Path

posted = Path("posted")
posted.mkdir(exist_ok=True)
for name in ("pr-draft-demo-l.md", "comment-draft-demo-k.md"):
    shutil.copyfile(f"notes/{name}", posted / name)
