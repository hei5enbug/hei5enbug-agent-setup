"""Post the draft as it is: the reference repository holds what a run that skips the review would have posted."""
import shutil
from pathlib import Path

posted = Path("posted")
posted.mkdir(exist_ok=True)
shutil.copyfile("notes/pr-draft-demo-j.md", posted / "pr-draft-demo-j.md")
