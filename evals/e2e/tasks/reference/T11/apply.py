import sys

from patch_tools import commit, replace

repo = sys.argv[1]
replace(repo, "notes_cli/cli.py", "import os\nimport sys\n", "import os\nimport sys\nimport tomllib\nfrom pathlib import Path\n")
replace(repo, "notes_cli/cli.py", "def build_parser() -> argparse.ArgumentParser:", '''def read_version() -> str:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]


def build_parser() -> argparse.ArgumentParser:''')
replace(repo, "notes_cli/cli.py", '    parser.add_argument("--store",', '    parser.add_argument("--version", action="version", version=f"notes-cli {read_version()}")\n    parser.add_argument("--store",')
replace(repo, "README.md", "- `memo remove ID` deletes a memo.\n", "- `memo remove ID` deletes a memo.\n- `--version` prints the program name and the version from `pyproject.toml`.\n")
replace(repo, "docs/ko/README.ko.md", "- `memo remove ID`는 메모를 삭제합니다.\n", "- `memo remove ID`는 메모를 삭제합니다.\n- `--version`은 프로그램 이름과 `pyproject.toml`의 버전을 출력합니다.\n")
commit(repo, "feat: add a version option to the command line")
