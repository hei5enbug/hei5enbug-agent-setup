import subprocess
import sys
from pathlib import Path

repo = Path(sys.argv[1])
SKIP = {".git", "__pycache__", ".pytest_cache"}
REPLACEMENTS = (("Memo", "Note"), ("memo", "note"), ("MEMO", "NOTE"), ("메모", "노트"))


def convert(text: str) -> str:
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    return text


for path in sorted(repo.rglob("*")):
    if path.is_file() and not (set(path.relative_to(repo).parts) & SKIP):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        converted = convert(text)
        if converted != text:
            path.write_text(converted, encoding="utf-8")

for old, new in (("notes_cli/memo.py", "notes_cli/note.py"), ("tests/test_memo.py", "tests/test_note.py")):
    subprocess.run(["mv", str(repo / old), str(repo / new)], check=True)
