import sys

from patch_tools import commit, write

repo = sys.argv[1]
write(repo, "parser/fields.py", '''"""Split one line of comma-separated fields."""


def split_fields(line: str) -> list[str]:
    return [part.strip() for part in line.rstrip("\\n").split(",")]
''')
commit(repo, "fix: keep the trailing empty field in the parser")
